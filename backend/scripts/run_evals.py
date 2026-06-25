#!/usr/bin/env python3
"""Run golden question evals against /run-multi-agent and persist results."""

from __future__ import annotations

import argparse
import json
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, request

from app.database import EvalResult, SessionLocal, init_db

DEFAULT_DATASET_PATH = Path("tests/eval/datasets/eval_questions.json")
DEFAULT_BASE_URL = "http://localhost:8000"
REFUSAL_MARKERS = (
    "i'm designed to answer questions about kate's professional experience",
    "ask me about her skills, projects, or career background",
)


@dataclass
class EvalCase:
    case_id: str
    question: str
    expected_topics: list[str]
    expected_project_references: list[str]
    should_refuse: bool


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _contains_phrase(text: str, phrase: str) -> bool:
    return _normalize(phrase) in _normalize(text)


def _coverage(answer: str, expected: list[str]) -> tuple[float, list[str]]:
    if not expected:
        return 1.0, []

    found = [item for item in expected if _contains_phrase(answer, item)]
    return len(found) / len(expected), found


def _is_refusal(answer: str) -> bool:
    lowered = answer.lower()
    return any(marker in lowered for marker in REFUSAL_MARKERS)


def _load_cases(dataset_path: Path) -> list[EvalCase]:
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases", [])
    cases: list[EvalCase] = []

    for row in raw_cases:
        cases.append(
            EvalCase(
                case_id=str(row["id"]),
                question=str(row["question"]),
                expected_topics=list(row.get("expected_topics", [])),
                expected_project_references=list(
                    row.get("expected_project_references", [])
                ),
                should_refuse=bool(row.get("should_refuse", False)),
            )
        )

    return cases


def _call_agent(base_url: str, session_id: str, question: str) -> dict[str, Any]:
    payload = json.dumps({"session_id": session_id, "message": question}).encode("utf-8")
    req = request.Request(
        f"{base_url.rstrip('/')}/run-multi-agent",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req, timeout=90) as response:
        body = response.read().decode("utf-8")
        return json.loads(body)


def _evaluate_case(case: EvalCase, answer: str) -> dict[str, Any]:
    topic_coverage, found_topics = _coverage(answer, case.expected_topics)
    project_coverage, found_projects = _coverage(answer, case.expected_project_references)

    refusal_detected = _is_refusal(answer)
    refusal_correct = refusal_detected == case.should_refuse

    if case.should_refuse:
        passed = refusal_correct
    else:
        topic_ok = topic_coverage >= 0.5
        project_ok = (
            project_coverage >= 0.5
            if case.expected_project_references
            else True
        )
        passed = refusal_correct and topic_ok and project_ok

    note = {
        "found_topics": found_topics,
        "found_project_references": found_projects,
        "refusal_detected": refusal_detected,
    }

    return {
        "topic_coverage": round(topic_coverage, 4),
        "project_coverage": round(project_coverage, 4),
        "refusal_correct": int(refusal_correct),
        "passed": int(passed),
        "notes": json.dumps(note, separators=(",", ":"), sort_keys=True),
    }


def _store_results(run_id: str, rows: list[dict[str, Any]]) -> None:
    db = SessionLocal()
    try:
        for row in rows:
            db.add(
                EvalResult(
                    run_id=run_id,
                    eval_case_id=row["eval_case_id"],
                    question=row["question"],
                    expected_topics=row["expected_topics"],
                    expected_projects=row["expected_projects"],
                    should_refuse=row["should_refuse"],
                    answer=row["answer"],
                    topic_coverage=row["topic_coverage"],
                    project_coverage=row["project_coverage"],
                    refusal_correct=row["refusal_correct"],
                    passed=row["passed"],
                    notes=row["notes"],
                )
            )
        db.commit()
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run golden question evaluations")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    init_db()
    cases = _load_cases(dataset_path)
    if args.limit > 0:
        cases = cases[: args.limit]

    run_id = str(uuid.uuid4())
    session_id = f"eval-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    rows: list[dict[str, Any]] = []

    print(f"Running {len(cases)} eval cases (run_id={run_id})")

    for index, case in enumerate(cases, start=1):
        answer = ""
        error_text = None
        try:
            result = _call_agent(args.base_url, session_id, case.question)
            answer = str(result.get("answer", ""))
            if result.get("status") != "success":
                error_text = str(result.get("message", "unknown error"))
        except error.URLError as e:
            error_text = f"request_error: {e}"
        except Exception as e:
            error_text = f"unexpected_error: {e}"

        eval_result = _evaluate_case(case, answer)
        if error_text:
            eval_result["passed"] = 0
            eval_result["notes"] = json.dumps(
                {"error": error_text},
                separators=(",", ":"),
                sort_keys=True,
            )

        rows.append(
            {
                "eval_case_id": case.case_id,
                "question": case.question,
                "expected_topics": json.dumps(case.expected_topics),
                "expected_projects": json.dumps(case.expected_project_references),
                "should_refuse": int(case.should_refuse),
                "answer": answer,
                **eval_result,
            }
        )

        print(
            f"[{index:02d}/{len(cases):02d}] {case.case_id}: "
            f"passed={bool(eval_result['passed'])} "
            f"topic_cov={eval_result['topic_coverage']:.2f} "
            f"proj_cov={eval_result['project_coverage']:.2f} "
            f"refusal_ok={bool(eval_result['refusal_correct'])}"
        )

    _store_results(run_id, rows)

    pass_rate = statistics.mean(row["passed"] for row in rows) if rows else 0.0
    topic_avg = statistics.mean(row["topic_coverage"] for row in rows) if rows else 0.0
    project_avg = (
        statistics.mean(row["project_coverage"] for row in rows) if rows else 0.0
    )
    refusal_rate = (
        statistics.mean(row["refusal_correct"] for row in rows) if rows else 0.0
    )

    print("\nEval summary")
    print(f"run_id: {run_id}")
    print(f"cases: {len(rows)}")
    print(f"pass_rate: {pass_rate:.3f}")
    print(f"avg_topic_coverage: {topic_avg:.3f}")
    print(f"avg_project_coverage: {project_avg:.3f}")
    print(f"refusal_correctness_rate: {refusal_rate:.3f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
