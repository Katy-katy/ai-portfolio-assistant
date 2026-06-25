#!/usr/bin/env python3
"""Run golden question evals against /run-multi-agent and persist results."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request

from google.genai import Client

from app.database import EvalResult, SessionLocal, init_db

DEFAULT_DATASET_PATH = Path("tests/eval/datasets/eval_questions.json")
DEFAULT_BASE_URL = "http://localhost:8000"
REFUSAL_MARKERS = (
    "i'm designed to answer questions about kate's professional experience",
    "ask me about her skills, projects, or career background",
)
DEFAULT_JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gemini-2.5-flash")


@dataclass
class EvalCase:
    case_id: str
    question: str
    expected_topics: list[str]
    expected_project_references: list[str]
    expected_key_points: list[str]
    forbidden_claims: list[str]
    should_refuse: bool


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract first JSON object from potentially noisy LLM output."""
    stripped = text.strip()
    try:
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", stripped)
    if not match:
        raise ValueError("Judge output does not contain a JSON object")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("Judge output JSON is not an object")
    return payload


def _semantic_eval_prompt(case: EvalCase, answer: str) -> str:
    """Construct judge prompt for semantic quality scoring."""
    rubric = {
        "semantic_relevance": "How well the answer addresses the user question and expected_topics (0 to 1)",
        "factual_grounding": "How well the answer avoids unsupported claims and stays grounded (0 to 1)",
        "completeness": "How well expected_key_points and expected_project_references are covered (0 to 1)",
        "clarity": "How clear, structured, and concise the answer is (0 to 1)",
        "refusal_appropriateness": "Whether refusal behavior is correct for should_refuse (0 to 1)",
        "overall_semantic_score": "Overall semantic quality score considering all criteria (0 to 1)",
    }

    return (
        "You are an evaluation judge for a portfolio QA assistant. "
        "Score the answer using ONLY the provided inputs. Return strict JSON only.\n\n"
        f"Question: {case.question}\n"
        f"Should Refuse: {case.should_refuse}\n"
        f"Expected Topics: {json.dumps(case.expected_topics)}\n"
        f"Expected Project References: {json.dumps(case.expected_project_references)}\n"
        f"Expected Key Points: {json.dumps(case.expected_key_points)}\n"
        f"Forbidden Claims: {json.dumps(case.forbidden_claims)}\n"
        f"Answer: {answer}\n\n"
        "Scoring rubric (0..1):\n"
        f"{json.dumps(rubric, indent=2)}\n\n"
        "Return JSON with EXACT keys:\n"
        "semantic_relevance, factual_grounding, completeness, clarity, refusal_appropriateness, overall_semantic_score, missing_key_points, notes\n"
        "- missing_key_points must be a JSON array of strings.\n"
        "- notes must be a concise string.\n"
        "- Values must be numeric between 0 and 1."
    )


def _semantic_scores(
    client: Client,
    model: str,
    case: EvalCase,
    answer: str,
) -> dict[str, Any]:
    """Run LLM judge and return normalized semantic score payload."""
    prompt = _semantic_eval_prompt(case, answer)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
    )
    judge_text = (response.text or "").strip()
    parsed = _extract_json_object(judge_text)

    scores = {
        "semantic_relevance": min(1.0, max(0.0, _safe_float(parsed.get("semantic_relevance")))),
        "factual_grounding": min(1.0, max(0.0, _safe_float(parsed.get("factual_grounding")))),
        "completeness": min(1.0, max(0.0, _safe_float(parsed.get("completeness")))),
        "clarity": min(1.0, max(0.0, _safe_float(parsed.get("clarity")))),
        "refusal_appropriateness": min(
            1.0,
            max(0.0, _safe_float(parsed.get("refusal_appropriateness"))),
        ),
        "overall_semantic_score": min(
            1.0,
            max(0.0, _safe_float(parsed.get("overall_semantic_score"))),
        ),
        "missing_key_points": parsed.get("missing_key_points", []),
        "notes": str(parsed.get("notes", "")),
        "judge_raw": judge_text,
    }
    if not isinstance(scores["missing_key_points"], list):
        scores["missing_key_points"] = []
    return scores


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
                expected_key_points=list(row.get("expected_key_points", [])),
                forbidden_claims=list(row.get("forbidden_claims", [])),
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


def _evaluate_case(
    case: EvalCase,
    answer: str,
    semantic_scores: dict[str, Any] | None,
    semantic_threshold: float,
) -> dict[str, Any]:
    topic_coverage, found_topics = _coverage(answer, case.expected_topics)
    project_coverage, found_projects = _coverage(answer, case.expected_project_references)

    refusal_detected = _is_refusal(answer)
    refusal_correct = refusal_detected == case.should_refuse

    if case.should_refuse:
        semantic_pass = (
            _safe_float((semantic_scores or {}).get("refusal_appropriateness"), 0.0)
            >= semantic_threshold
            if semantic_scores is not None
            else True
        )
        passed = refusal_correct and semantic_pass
    else:
        topic_ok = topic_coverage >= 0.5
        project_ok = (
            project_coverage >= 0.5
            if case.expected_project_references
            else True
        )
        semantic_pass = (
            _safe_float((semantic_scores or {}).get("overall_semantic_score"), 0.0)
            >= semantic_threshold
            if semantic_scores is not None
            else True
        )
        passed = refusal_correct and topic_ok and project_ok and semantic_pass

    note = {
        "found_topics": found_topics,
        "found_project_references": found_projects,
        "refusal_detected": refusal_detected,
    }
    if semantic_scores is not None:
        note["semantic_judge"] = {
            "missing_key_points": semantic_scores.get("missing_key_points", []),
            "notes": semantic_scores.get("notes", ""),
        }

    return {
        "topic_coverage": round(topic_coverage, 4),
        "project_coverage": round(project_coverage, 4),
        "refusal_correct": int(refusal_correct),
        "semantic_relevance": round(
            _safe_float((semantic_scores or {}).get("semantic_relevance"), 0.0),
            4,
        ),
        "factual_grounding": round(
            _safe_float((semantic_scores or {}).get("factual_grounding"), 0.0),
            4,
        ),
        "completeness": round(
            _safe_float((semantic_scores or {}).get("completeness"), 0.0),
            4,
        ),
        "clarity": round(
            _safe_float((semantic_scores or {}).get("clarity"), 0.0),
            4,
        ),
        "refusal_appropriateness": round(
            _safe_float((semantic_scores or {}).get("refusal_appropriateness"), 0.0),
            4,
        ),
        "overall_semantic_score": round(
            _safe_float((semantic_scores or {}).get("overall_semantic_score"), 0.0),
            4,
        ),
        "semantic_pass": int(semantic_pass),
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
                    expected_key_points=row["expected_key_points"],
                    forbidden_claims=row["forbidden_claims"],
                    should_refuse=row["should_refuse"],
                    answer=row["answer"],
                    topic_coverage=row["topic_coverage"],
                    project_coverage=row["project_coverage"],
                    refusal_correct=row["refusal_correct"],
                    semantic_relevance=row["semantic_relevance"],
                    factual_grounding=row["factual_grounding"],
                    completeness=row["completeness"],
                    clarity=row["clarity"],
                    refusal_appropriateness=row["refusal_appropriateness"],
                    overall_semantic_score=row["overall_semantic_score"],
                    semantic_pass=row["semantic_pass"],
                    judge_model=row["judge_model"],
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
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--semantic-threshold", type=float, default=0.65)
    parser.add_argument("--disable-semantic", action="store_true")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    init_db()
    cases = _load_cases(dataset_path)
    if args.limit > 0:
        cases = cases[: args.limit]

    run_id = str(uuid.uuid4())
    session_id = f"eval-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    rows: list[dict[str, Any]] = []
    judge_client: Client | None = None

    if not args.disable_semantic:
        judge_client = Client()

    print(f"Running {len(cases)} eval cases (run_id={run_id})")

    for index, case in enumerate(cases, start=1):
        answer = ""
        error_text = None
        semantic_scores: dict[str, Any] | None = None
        try:
            result = _call_agent(args.base_url, session_id, case.question)
            answer = str(result.get("answer", ""))
            if result.get("status") != "success":
                error_text = str(result.get("message", "unknown error"))

            if judge_client is not None:
                semantic_scores = _semantic_scores(
                    client=judge_client,
                    model=args.judge_model,
                    case=case,
                    answer=answer,
                )
        except error.URLError as e:
            error_text = f"request_error: {e}"
        except Exception as e:
            error_text = f"unexpected_error: {e}"

        eval_result = _evaluate_case(
            case,
            answer,
            semantic_scores=semantic_scores,
            semantic_threshold=args.semantic_threshold,
        )
        if error_text:
            eval_result["passed"] = 0
            eval_result["semantic_pass"] = 0
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
                "expected_key_points": json.dumps(case.expected_key_points),
                "forbidden_claims": json.dumps(case.forbidden_claims),
                "should_refuse": int(case.should_refuse),
                "judge_model": args.judge_model if not args.disable_semantic else None,
                "answer": answer,
                **eval_result,
            }
        )

        print(
            f"[{index:02d}/{len(cases):02d}] {case.case_id}: "
            f"passed={bool(eval_result['passed'])} "
            f"topic_cov={eval_result['topic_coverage']:.2f} "
            f"proj_cov={eval_result['project_coverage']:.2f} "
            f"semantic={eval_result['overall_semantic_score']:.2f} "
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
    semantic_avg = (
        statistics.mean(row["overall_semantic_score"] for row in rows)
        if rows
        else 0.0
    )
    semantic_pass_rate = (
        statistics.mean(row["semantic_pass"] for row in rows)
        if rows
        else 0.0
    )

    print("\nEval summary")
    print(f"run_id: {run_id}")
    print(f"cases: {len(rows)}")
    print(f"pass_rate: {pass_rate:.3f}")
    print(f"avg_topic_coverage: {topic_avg:.3f}")
    print(f"avg_project_coverage: {project_avg:.3f}")
    print(f"avg_overall_semantic_score: {semantic_avg:.3f}")
    print(f"semantic_pass_rate: {semantic_pass_rate:.3f}")
    print(f"refusal_correctness_rate: {refusal_rate:.3f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
