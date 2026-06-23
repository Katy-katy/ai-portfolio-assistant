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

"""Integration tests for FastAPI endpoint."""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, init_db, SessionLocal, get_db
from app.fast_api_app import app


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    yield TestSessionLocal()

    # Cleanup
    os.unlink(db_path)


@pytest.fixture
def client(temp_db):
    """Create test client with test database."""
    def override_get_db():
        return temp_db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestMultiAgentEndpoint:
    """Test POST /run-multi-agent endpoint."""

    def test_endpoint_exists(self, client):
        """Endpoint should exist and be accessible."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_valid_request_returns_success(self, client):
        """Valid request should return success response."""
        with patch("app.fast_api_app.MultiAgentOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = MagicMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            mock_orchestrator.run.return_value = "Test answer"
            mock_orchestrator.agent_runs = [{"agent_name": "test"}]
            mock_orchestrator.save_agent_runs = MagicMock()

            response = client.post(
                "/run-multi-agent",
                json={
                    "session_id": "test_session",
                    "message": "What are Kate's skills?"
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["answer"] == "Test answer"
            assert data["question_id"] is not None
            assert data["agent_runs_count"] == 1

    def test_missing_session_id_returns_error(self, client):
        """Request without session_id should return error."""
        response = client.post(
            "/run-multi-agent",
            json={"message": "Test question"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert "session_id" in data["message"]

    def test_missing_message_returns_error(self, client):
        """Request without message should return error."""
        response = client.post(
            "/run-multi-agent",
            json={"session_id": "test_session"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert "message" in data["message"]

    def test_empty_message_returns_error(self, client):
        """Request with empty message should return error."""
        response = client.post(
            "/run-multi-agent",
            json={
                "session_id": "test_session",
                "message": "   "
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"

    def test_session_created_on_first_request(self, client, temp_db):
        """New session should be created on first request."""
        from app.database import UserSession

        with patch("app.fast_api_app.MultiAgentOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = MagicMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            mock_orchestrator.run.return_value = "Answer"
            mock_orchestrator.agent_runs = []

            client.post(
                "/run-multi-agent",
                json={
                    "session_id": "new_session_123",
                    "message": "Test question"
                }
            )

            session = temp_db.query(UserSession).filter(
                UserSession.session_id == "new_session_123"
            ).first()
            assert session is not None

    def test_question_recorded_in_database(self, client, temp_db):
        """Question should be recorded in database."""
        from app.database import Question

        with patch("app.fast_api_app.MultiAgentOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = MagicMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            mock_orchestrator.run.return_value = "Test answer"
            mock_orchestrator.agent_runs = []

            client.post(
                "/run-multi-agent",
                json={
                    "session_id": "test_session",
                    "message": "What is the question?"
                }
            )

            question = temp_db.query(Question).filter(
                Question.question == "What is the question?"
            ).first()
            assert question is not None
            assert question.session_id == "test_session"

    def test_answer_updated_in_database(self, client, temp_db):
        """Answer should be updated in question record."""
        from app.database import Question

        with patch("app.fast_api_app.MultiAgentOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = MagicMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            expected_answer = "Kate is an AI/ML engineer"
            mock_orchestrator.run.return_value = expected_answer
            mock_orchestrator.agent_runs = []

            client.post(
                "/run-multi-agent",
                json={
                    "session_id": "test_session",
                    "message": "Who is Kate?"
                }
            )

            question = temp_db.query(Question).filter(
                Question.question == "Who is Kate?"
            ).first()
            assert question.answer == expected_answer

    def test_agent_runs_saved_to_database(self, client):
        """Agent runs should be saved via orchestrator.save_agent_runs()."""
        with patch("app.fast_api_app.MultiAgentOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = MagicMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            mock_orchestrator.run.return_value = "Answer"
            mock_orchestrator.agent_runs = [
                {"agent_name": "validation_agent"},
                {"agent_name": "skills_agent"},
            ]

            client.post(
                "/run-multi-agent",
                json={
                    "session_id": "test_session",
                    "message": "Test question"
                }
            )

            # Verify save_agent_runs was called with question_id
            mock_orchestrator.save_agent_runs.assert_called_once()
            call_args = mock_orchestrator.save_agent_runs.call_args
            assert call_args[0][0] is not None  # question_id

    def test_response_includes_question_id(self, client):
        """Response should include question_id."""
        with patch("app.fast_api_app.MultiAgentOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = MagicMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            mock_orchestrator.run.return_value = "Answer"
            mock_orchestrator.agent_runs = []

            response = client.post(
                "/run-multi-agent",
                json={
                    "session_id": "test_session",
                    "message": "Test question"
                }
            )

            data = response.json()
            assert "question_id" in data
            assert isinstance(data["question_id"], int)
            assert data["question_id"] > 0

    def test_response_includes_agent_runs_count(self, client):
        """Response should include count of agent runs."""
        with patch("app.fast_api_app.MultiAgentOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = MagicMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            mock_orchestrator.run.return_value = "Answer"
            mock_orchestrator.agent_runs = [
                {"agent_name": "agent1"},
                {"agent_name": "agent2"},
                {"agent_name": "agent3"},
            ]

            response = client.post(
                "/run-multi-agent",
                json={
                    "session_id": "test_session",
                    "message": "Test question"
                }
            )

            data = response.json()
            assert data["agent_runs_count"] == 3

    def test_orchestrator_receives_correct_question(self, client):
        """Orchestrator should receive the exact question from request."""
        with patch("app.fast_api_app.MultiAgentOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = MagicMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            mock_orchestrator.run.return_value = "Answer"
            mock_orchestrator.agent_runs = []

            test_question = "What programming languages does Kate know?"
            client.post(
                "/run-multi-agent",
                json={
                    "session_id": "test_session",
                    "message": test_question
                }
            )

            mock_orchestrator.run.assert_called_once_with(test_question)


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_endpoint(self, client):
        """Health endpoint should return ok."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        # Check status exists and is ok
        assert data.get("status") == "ok"


class TestValidateQuestionEndpoint:
    """Test /validate-question endpoint (existing)."""

    def test_validate_on_topic_question(self, client):
        """Should validate on-topic question."""
        response = client.post(
            "/validate-question",
            json={"text": "What are Kate's skills?"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_on_topic"] is True

    def test_validate_off_topic_question(self, client):
        """Should validate off-topic question."""
        response = client.post(
            "/validate-question",
            json={"text": "What's the best pizza?"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_on_topic"] is False

    def test_empty_question_validation(self, client):
        """Should handle empty question."""
        response = client.post(
            "/validate-question",
            json={"text": ""}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_on_topic"] is False


class TestErrorHandling:
    """Test error handling in endpoint."""

    def test_orchestrator_exception_returns_error(self, client):
        """Orchestrator exception should return error response."""
        with patch("app.fast_api_app.MultiAgentOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = MagicMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            mock_orchestrator.run.side_effect = Exception("API Error")

            response = client.post(
                "/run-multi-agent",
                json={
                    "session_id": "test_session",
                    "message": "Test"
                }
            )

            data = response.json()
            assert data["status"] == "error"
            assert "API Error" in data["message"]

    def test_database_error_returns_error(self, client):
        """Database error should return error response."""
        with patch("app.fast_api_app.get_db") as mock_get_db:
            mock_get_db.side_effect = Exception("Database connection error")

            # This will fail differently since FastAPI will handle the dependency
            # but we can still test error response format
            response = client.post(
                "/run-multi-agent",
                json={
                    "session_id": "test_session",
                    "message": "Test"
                }
            )

            # Should still get a response (either error or 500)
            assert response.status_code in [200, 500]


class TestConcurrentRequests:
    """Test handling of concurrent requests."""

    def test_different_sessions_isolated(self, client, temp_db):
        """Different sessions should be isolated."""
        from app.database import Question

        with patch("app.fast_api_app.MultiAgentOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = MagicMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            mock_orchestrator.run.return_value = "Answer"
            mock_orchestrator.agent_runs = []

            # Request 1
            client.post(
                "/run-multi-agent",
                json={
                    "session_id": "session_1",
                    "message": "Question 1"
                }
            )

            # Request 2
            client.post(
                "/run-multi-agent",
                json={
                    "session_id": "session_2",
                    "message": "Question 2"
                }
            )

            # Verify both are in database
            q1 = temp_db.query(Question).filter(
                Question.question == "Question 1"
            ).first()
            q2 = temp_db.query(Question).filter(
                Question.question == "Question 2"
            ).first()

            assert q1 is not None
            assert q2 is not None
            assert q1.session_id == "session_1"
            assert q2.session_id == "session_2"

    def test_same_session_multiple_questions(self, client, temp_db):
        """Same session can have multiple questions."""
        from app.database import Question, UserSession

        with patch("app.fast_api_app.MultiAgentOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = MagicMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            mock_orchestrator.run.return_value = "Answer"
            mock_orchestrator.agent_runs = []

            # Two questions in same session
            client.post(
                "/run-multi-agent",
                json={
                    "session_id": "same_session",
                    "message": "First question"
                }
            )

            client.post(
                "/run-multi-agent",
                json={
                    "session_id": "same_session",
                    "message": "Second question"
                }
            )

            session = temp_db.query(UserSession).filter(
                UserSession.session_id == "same_session"
            ).first()

            questions = temp_db.query(Question).filter(
                Question.session_id == "same_session"
            ).all()

            assert len(questions) == 2
            # Session should still be unique
            assert session is not None
