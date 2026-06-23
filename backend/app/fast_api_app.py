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
from datetime import datetime
from typing import Any

import google.auth
from fastapi import FastAPI, Depends
from google.adk.cli.fast_api import get_fast_api_app
from google.cloud import logging as google_cloud_logging
from sqlalchemy.orm import Session

from app.app_utils.telemetry import setup_telemetry
from app.app_utils.typing import Feedback
from app.tools import is_question_on_topic
from app.database import get_db, Question, UserSession, init_db
from app.orchestration import MultiAgentOrchestrator

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


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


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

        # Run orchestrator
        orchestrator = MultiAgentOrchestrator(db)
        answer = orchestrator.run(message)

        # Save agent runs
        orchestrator.save_agent_runs(question_record.id)

        # Update question record with answer
        question_record.answer = answer
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
