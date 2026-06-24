# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
import json
from collections import Counter
from datetime import datetime
from typing import Any

import google.auth
from fastapi import FastAPI, Depends
from google.adk.cli.fast_api import get_fast_api_app
from google.cloud import logging as google_cloud_logging
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.app_utils.telemetry import setup_telemetry
from app.app_utils.typing import Feedback
from app.tools import (
    get_retrieval_cache_stats,
    index_pgvector_documents,
    is_question_on_topic,
)
from app.database import Feedback as FeedbackRecord
from app.database import AgentRun, Question, UserSession, get_db, init_db
from app.orchestration import MultiAgentOrchestrator


def _estimate_tokens(text: str) -> int:
    """Rough token estimate when model token telemetry is unavailable.

    Uses a conservative chars/4 heuristic commonly used for English text.
    """
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)


def _cache_stats_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compute per-request delta for retrieval cache counters."""
    keys = ("hits", "misses", "expired", "sets", "lookups")
    delta = {
        key: int(after.get(key, 0)) - int(before.get(key, 0))
        for key in keys
    }
    lookups = delta["lookups"]
    delta_hit_rate = (delta["hits"] / lookups) if lookups > 0 else 0.0
    delta["hit_rate"] = round(delta_hit_rate, 4)

    before_categories = before.get("by_category") or {}
    after_categories = after.get("by_category") or {}
    category_names = set(before_categories.keys()) | set(after_categories.keys())
    by_category: dict[str, Any] = {}
    for category in sorted(category_names):
        before_category = before_categories.get(category, {})
        after_category = after_categories.get(category, {})
        category_delta = {
            key: int(after_category.get(key, 0)) - int(before_category.get(key, 0))
            for key in keys
        }
        category_lookups = category_delta["lookups"]
        category_hit_rate = (
            category_delta["hits"] / category_lookups if category_lookups > 0 else 0.0
        )
        category_delta["hit_rate"] = round(category_hit_rate, 4)
        by_category[category] = category_delta

    delta["by_category"] = by_category
    return delta

setup_telemetry()
_, project_id = google.auth.default()
logging_client = google_cloud_logging.Client()
logger = logging_client.logger(__name__)
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else ["*"]
)

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Configure persistent database storage.
# Priority:
# 1) SESSION_SERVICE_URI (explicit ADK session DB URI)
# 2) DATABASE_URL (shared app DB URI)
# 3) Local SQLite fallback
BASE_DIR = os.path.abspath(os.path.join(AGENT_DIR, ".."))
db_path = os.path.join(BASE_DIR, "database", "portfolio.db")
default_sqlite_uri = f"sqlite:///{db_path}"
session_service_uri = (
    os.environ.get("SESSION_SERVICE_URI")
    or os.environ.get("DATABASE_URL")
    or default_sqlite_uri
)

artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

# Initialize database
init_db()

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    otel_to_cloud=True,
)
app.title = "backend"
app.description = "API for interacting with the Agent backend"


@app.on_event("startup")
def startup_index_pgvector() -> None:
    """Index knowledge documents into pgvector once at application startup."""
    rag_backend = os.getenv("RAG_BACKEND", "local").strip().lower()
    should_index = os.getenv("RAG_AUTO_INGEST", "true").strip().lower() == "true"

    if rag_backend != "pgvector" or not should_index:
        return

    try:
        result = index_pgvector_documents()
        logger.log_struct(
            {
                "event": "pgvector_startup_index",
                "status": result.get("status"),
                "table": result.get("table"),
                "total_chunks": result.get("total_chunks"),
            },
            severity="INFO",
        )
    except Exception as e:
        logger.log_struct(
            {
                "event": "pgvector_startup_index",
                "status": "error",
                "error": str(e),
            },
            severity="ERROR",
        )


@app.post("/feedback")
def collect_feedback(feedback: Feedback, db: Session = Depends(get_db)) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    if feedback.question_id is None:
        return {"status": "error", "message": "question_id is required"}

    question = db.query(Question).filter(Question.id == int(feedback.question_id)).first()
    if question is None:
        return {"status": "error", "message": "question_id not found"}

    feedback_record = FeedbackRecord(
        question_id=int(feedback.question_id),
        rating=int(feedback.score),
        comments=feedback.text or "",
    )
    db.add(feedback_record)
    db.commit()

    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


@app.get("/admin/overview")
def admin_overview(limit: int = 10, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return analytics used by the admin dashboard."""
    safe_limit = max(1, min(50, int(limit)))

    total_questions = int(db.query(func.count(Question.id)).scalar() or 0)
    avg_latency_ms = float(
        db.query(func.avg(Question.latency_ms))
        .filter(Question.latency_ms.isnot(None))
        .scalar()
        or 0.0
    )

    total_feedback = int(db.query(func.count(FeedbackRecord.id)).scalar() or 0)
    positive_feedback = int(
        db.query(func.count(FeedbackRecord.id))
        .filter(FeedbackRecord.rating > 0)
        .scalar()
        or 0
    )

    feedback_submission_rate = (
        (total_feedback / total_questions) if total_questions > 0 else 0.0
    )
    positive_feedback_rate = (
        (positive_feedback / total_feedback) if total_feedback > 0 else 0.0
    )

    top_questions_rows = (
        db.query(
            Question.question,
            func.count(Question.id).label("count"),
            func.max(Question.created_at).label("last_seen_at"),
        )
        .group_by(Question.question)
        .order_by(func.count(Question.id).desc(), func.max(Question.created_at).desc())
        .limit(safe_limit)
        .all()
    )
    top_questions = [
        {
            "question": row.question,
            "count": int(row.count or 0),
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        }
        for row in top_questions_rows
    ]

    top_intents_rows = (
        db.query(Question.intent, func.count(Question.id).label("count"))
        .filter(Question.intent.isnot(None), Question.intent != "unknown")
        .group_by(Question.intent)
        .order_by(func.count(Question.id).desc())
        .limit(safe_limit)
        .all()
    )
    top_intents = [
        {"intent": row.intent, "count": int(row.count or 0)}
        for row in top_intents_rows
    ]

    skill_keywords = (
        "python",
        "llm",
        "rag",
        "nlp",
        "agent",
        "fastapi",
        "tensorflow",
        "scikit",
        "openai",
        "azure",
    )
    skill_counter: Counter[str] = Counter()
    skill_questions = (
        db.query(Question.question)
        .order_by(Question.created_at.desc())
        .limit(1000)
        .all()
    )
    for row in skill_questions:
        question_text = (row.question or "").lower()
        for keyword in skill_keywords:
            if keyword in question_text:
                skill_counter[keyword] += 1

    top_skills = [
        {"skill": skill, "count": count}
        for skill, count in skill_counter.most_common(safe_limit)
    ]

    error_question_ids = {
        int(row.question_id)
        for row in (
            db.query(AgentRun.question_id)
            .filter(AgentRun.status == "error")
            .distinct()
            .all()
        )
        if row.question_id is not None
    }

    recent_candidates = (
        db.query(Question)
        .order_by(Question.created_at.desc())
        .limit(250)
        .all()
    )
    recent_failed_or_rejected: list[dict[str, Any]] = []
    rejection_markers = (
        "i'm designed to answer questions about kate",
        "ask me about her skills, projects, or career background",
    )

    for question in recent_candidates:
        reasons: list[str] = []
        answer_text = (question.answer or "").lower()

        if question.id in error_question_ids:
            reasons.append("agent_error")
        if not question.answer:
            reasons.append("no_answer")
        if any(marker in answer_text for marker in rejection_markers):
            reasons.append("rejected_off_topic")

        if not reasons:
            continue

        recent_failed_or_rejected.append(
            {
                "question_id": question.id,
                "session_id": question.session_id,
                "question": question.question,
                "intent": question.intent,
                "latency_ms": question.latency_ms,
                "created_at": question.created_at.isoformat() if question.created_at else None,
                "reasons": reasons,
            }
        )

        if len(recent_failed_or_rejected) >= safe_limit:
            break

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "summary": {
            "total_questions": total_questions,
            "avg_latency_ms": round(avg_latency_ms, 2),
            "total_feedback": total_feedback,
            "positive_feedback": positive_feedback,
            "feedback_submission_rate": round(feedback_submission_rate, 4),
            "positive_feedback_rate": round(positive_feedback_rate, 4),
        },
        "top_questions": top_questions,
        "top_intents": top_intents,
        "top_skills": top_skills,
        "recent_failed_or_rejected": recent_failed_or_rejected,
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint for readiness probes.

    Returns:
        Status and timestamp indicating the service is healthy.
    """
    return {"status": "ok", "service": "portfolio_assistant"}


@app.post("/validate-question")
def validate_question(question: dict[str, str]) -> dict[str, bool | str]:
    """Validate if a question is about Kate's professional experience.

    Args:
        question: Dict with 'text' key containing the user's question.

    Returns:
        Dict with 'is_on_topic' boolean and 'message' if off-topic.
    """
    text = question.get("text", "").strip()
    if not text:
        return {"is_on_topic": False, "message": "Please ask a question."}

    is_on_topic = is_question_on_topic(text)
    if not is_on_topic:
        return {
            "is_on_topic": False,
            "message": "I'm designed to answer questions about Kate's professional experience. Ask me about her skills, projects, or career background!"
        }

    return {"is_on_topic": True}


@app.post("/run-multi-agent")
def run_multi_agent(
    request: dict, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Run multi-agent orchestration for user question.

    Args:
        request: Dict with 'session_id' and 'message' keys
        db: Database session

    Returns:
        Dict with answer and metadata
    """
    try:
        session_id = request.get("session_id", "").strip()
        message = request.get("message", "").strip()

        if not session_id or not message:
            return {
                "status": "error",
                "message": "Missing session_id or message"
            }

        # Get or create session
        user_session = db.query(UserSession).filter(
            UserSession.session_id == session_id
        ).first()
        if not user_session:
            user_session = UserSession(session_id=session_id)
            db.add(user_session)
            db.commit()

        # Create question record
        question_record = Question(
            session_id=session_id,
            question=message,
            created_at=datetime.utcnow(),
        )
        db.add(question_record)
        db.commit()
        db.refresh(question_record)

        # Run orchestrator and capture end-to-end latency for this question.
        started_at = datetime.utcnow()
        cache_before = get_retrieval_cache_stats()
        orchestrator = MultiAgentOrchestrator(db)
        answer = orchestrator.run(message)
        cache_after = get_retrieval_cache_stats()
        cache_request = _cache_stats_delta(cache_before, cache_after)
        finished_at = datetime.utcnow()

        # Save agent runs
        orchestrator.save_agent_runs(
            question_record.id,
            cache_request_stats=cache_request,
        )

        # Update question record with answer and run metadata
        latency_ms = int((finished_at - started_at).total_seconds() * 1000)
        specialized_agents = [
            run.get("agent_name")
            for run in orchestrator.agent_runs
            if run.get("agent_name") in {"resume_agent", "skills_agent", "project_agent"}
            and run.get("status") == "success"
        ]

        if len(set(specialized_agents)) == 1:
            intent_value = specialized_agents[0]
        elif len(set(specialized_agents)) > 1:
            intent_value = "multi_domain"
        else:
            intent_value = "unknown"

        total_tokens = sum((run.get("tokens_used") or 0) for run in orchestrator.agent_runs)
        if total_tokens <= 0:
            total_tokens = _estimate_tokens(message) + _estimate_tokens(answer)

        question_record.answer = answer
        question_record.intent = intent_value
        question_record.latency_ms = latency_ms
        question_record.tokens_used = total_tokens
        question_record.cache_hits = int(cache_request.get("hits", 0))
        question_record.cache_misses = int(cache_request.get("misses", 0))
        question_record.cache_expired = int(cache_request.get("expired", 0))
        question_record.cache_sets = int(cache_request.get("sets", 0))
        question_record.cache_lookups = int(cache_request.get("lookups", 0))
        question_record.cache_hit_rate = float(cache_request.get("hit_rate", 0.0))
        question_record.cache_by_category = json.dumps(
            cache_request.get("by_category", {}),
            separators=(",", ":"),
            sort_keys=True,
        )
        db.commit()

        logger.log_struct(
            {
                "session_id": session_id,
                "question": message,
                "status": "success",
                "agent_runs": len(orchestrator.agent_runs),
            },
            severity="INFO"
        )

        return {
            "status": "success",
            "answer": answer,
            "question_id": question_record.id,
            "agent_runs_count": len(orchestrator.agent_runs),
            "retrieval_cache": {
                "request": cache_request,
                "total": cache_after,
            },
            "agent_runs": [
                {
                    "agent_name": run.get("agent_name"),
                    "status": run.get("status"),
                    "tools_called": run.get("tools_called"),
                }
                for run in orchestrator.agent_runs
            ],
        }
    except Exception as e:
        logger.log_struct(
            {
                "error": str(e),
                "status": "error",
            },
            severity="ERROR"
        )
        return {
            "status": "error",
            "message": str(e)
        }


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
