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

"""Integration tests for multi-agent orchestration."""

import os
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Question, UserSession, AgentRun, init_db
from app.orchestration import MultiAgentOrchestrator


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    yield SessionLocal()

    # Cleanup
    os.unlink(db_path)


@pytest.fixture
def orchestrator(temp_db):
    """Create an orchestrator with test database."""
    return MultiAgentOrchestrator(temp_db)


class TestValidationAgent:
    """Test validation agent functionality."""

    def test_validation_accepts_on_topic_question(self, orchestrator):
        """Validation agent should accept on-topic questions about Kate."""
        with patch("app.orchestration.validation_agent") as mock_agent:
            mock_agent.run.return_value = "ON_TOPIC"

            result = orchestrator.validate_question("What are Kate's skills?")

            assert result is True
            mock_agent.run.assert_called_once()

    def test_validation_rejects_off_topic_question(self, orchestrator):
        """Validation agent should reject off-topic questions."""
        with patch("app.orchestration.validation_agent") as mock_agent:
            mock_agent.run.return_value = "OFF_TOPIC"

            result = orchestrator.validate_question("What is the weather?")

            assert result is False
            mock_agent.run.assert_called_once()

    def test_validation_agent_logs_to_runs(self, orchestrator):
        """Validation agent execution should be logged."""
        with patch("app.orchestration.validation_agent") as mock_agent:
            mock_agent.run.return_value = "ON_TOPIC"

            orchestrator.validate_question("Test question")

            assert len(orchestrator.agent_runs) == 1
            assert orchestrator.agent_runs[0]["agent_name"] == "validation_agent"
            assert orchestrator.agent_runs[0]["status"] == "success"
            assert orchestrator.agent_runs[0]["output"] == "ON_TOPIC"

    def test_validation_agent_error_handling(self, orchestrator):
        """Validation agent should handle errors gracefully."""
        with patch("app.orchestration.validation_agent") as mock_agent:
            mock_agent.run.side_effect = Exception("API Error")

            result = orchestrator.validate_question("Test question")

            assert result is False
            assert len(orchestrator.agent_runs) == 1
            assert orchestrator.agent_runs[0]["status"] == "error"


class TestRoutingAgent:
    """Test routing agent functionality."""

    def test_routing_returns_agent_list(self, orchestrator):
        """Routing agent should return list of agents to invoke."""
        with patch("app.orchestration.routing_agent") as mock_agent:
            mock_agent.run.return_value = '{"agents": ["resume_agent", "skills_agent"], "reasoning": "Career and skills question"}'

            result = orchestrator.route_question("Tell me about Kate's background")

            assert isinstance(result, list)
            assert "resume_agent" in result
            assert "skills_agent" in result

    def test_routing_handles_single_agent(self, orchestrator):
        """Routing should work for single agent routing."""
        with patch("app.orchestration.routing_agent") as mock_agent:
            mock_agent.run.return_value = '{"agents": ["skills_agent"]}'

            result = orchestrator.route_question("What programming languages does Kate know?")

            assert result == ["skills_agent"]

    def test_routing_agent_logs_output(self, orchestrator):
        """Routing agent output should be logged."""
        with patch("app.orchestration.routing_agent") as mock_agent:
            mock_agent.run.return_value = '{"agents": ["project_agent"]}'

            orchestrator.route_question("Tell me about Lamabot")

            assert len(orchestrator.agent_runs) == 1
            assert "project_agent" in orchestrator.agent_runs[0]["output"]

    def test_routing_fallback_on_parse_error(self, orchestrator):
        """Routing should fallback to all agents on parse error."""
        with patch("app.orchestration.routing_agent") as mock_agent:
            mock_agent.run.return_value = "Invalid JSON response"

            result = orchestrator.route_question("Question")

            # Should fallback to all three specialized agents
            assert len(result) == 3
            assert "resume_agent" in result
            assert "skills_agent" in result
            assert "project_agent" in result


class TestSpecializedAgents:
    """Test specialized agent execution."""

    def test_resume_agent_execution(self, orchestrator):
        """Resume agent should be executed for career questions."""
        with patch("app.orchestration.resume_agent") as mock_agent:
            mock_agent.run.return_value = "Kate has 5+ years experience in AI and ML"

            outputs = orchestrator.run_specialized_agents(
                "Tell me about Kate's experience",
                ["resume_agent"]
            )

            assert "resume_agent" in outputs
            assert "5+ years" in outputs["resume_agent"]

    def test_skills_agent_execution(self, orchestrator):
        """Skills agent should be executed for skills questions."""
        with patch("app.orchestration.skills_agent") as mock_agent:
            mock_agent.run.return_value = "Kate's skills: Python, JavaScript, ML frameworks"

            outputs = orchestrator.run_specialized_agents(
                "What are Kate's technical skills?",
                ["skills_agent"]
            )

            assert "skills_agent" in outputs
            assert "Python" in outputs["skills_agent"]

    def test_project_agent_execution(self, orchestrator):
        """Project agent should be executed for project questions."""
        with patch("app.orchestration.project_agent") as mock_agent:
            mock_agent.run.return_value = "Lamabot is an AI project..."

            outputs = orchestrator.run_specialized_agents(
                "Tell me about Lamabot",
                ["project_agent"]
            )

            assert "project_agent" in outputs
            assert "Lamabot" in outputs["project_agent"]

    def test_multiple_agents_execution(self, orchestrator):
        """Multiple specialized agents should run sequentially."""
        with patch("app.orchestration.resume_agent") as mock_resume, \
             patch("app.orchestration.skills_agent") as mock_skills:
            mock_resume.run.return_value = "Career info"
            mock_skills.run.return_value = "Skills info"

            outputs = orchestrator.run_specialized_agents(
                "Tell me everything about Kate",
                ["resume_agent", "skills_agent"]
            )

            assert len(outputs) == 2
            assert outputs["resume_agent"] == "Career info"
            assert outputs["skills_agent"] == "Skills info"

    def test_unknown_agent_skipped(self, orchestrator):
        """Unknown agent names should be skipped."""
        outputs = orchestrator.run_specialized_agents(
            "Question",
            ["unknown_agent", "resume_agent"]
        )

        # Resume agent should be called
        assert len(outputs) <= 1


class TestAnswerSynthesis:
    """Test answer synthesis."""

    def test_answer_agent_synthesizes(self, orchestrator):
        """Answer agent should synthesize outputs into final answer."""
        with patch("app.orchestration.answer_agent") as mock_agent:
            mock_agent.run.return_value = "Based on Kate's background and skills..."

            specialized_outputs = {
                "resume_agent": "Career info",
                "skills_agent": "Skills info"
            }

            answer = orchestrator.synthesize_answer(
                "Question about Kate",
                specialized_outputs
            )

            assert "Based on Kate's background" in answer
            mock_agent.run.assert_called_once()

    def test_synthesis_logs_agent_run(self, orchestrator):
        """Answer synthesis should log agent run."""
        with patch("app.orchestration.answer_agent") as mock_agent:
            mock_agent.run.return_value = "Final answer"

            orchestrator.synthesize_answer("Question", {"agent": "output"})

            assert any(r["agent_name"] == "answer_agent" for r in orchestrator.agent_runs)

    def test_synthesis_fallback_on_error(self, orchestrator):
        """Synthesis should fallback on answer agent error."""
        with patch("app.orchestration.answer_agent") as mock_agent:
            mock_agent.run.side_effect = Exception("API Error")

            specialized_outputs = {
                "resume_agent": "Resume content",
                "skills_agent": "Skills content"
            }

            answer = orchestrator.synthesize_answer("Question", specialized_outputs)

            # Should return concatenated outputs
            assert "Resume content" in answer
            assert "Skills content" in answer


class TestFullOrchestration:
    """Test full orchestration workflow."""

    def test_full_workflow_on_topic_question(self, orchestrator):
        """Full workflow should process on-topic question."""
        with patch("app.orchestration.validation_agent") as mock_val, \
             patch("app.orchestration.routing_agent") as mock_route, \
             patch("app.orchestration.skills_agent") as mock_skills, \
             patch("app.orchestration.answer_agent") as mock_answer:

            mock_val.run.return_value = "ON_TOPIC"
            mock_route.run.return_value = '{"agents": ["skills_agent"]}'
            mock_skills.run.return_value = "Kate's skills include..."
            mock_answer.run.return_value = "Final synthesized answer"

            result = orchestrator.run("What are Kate's skills?")

            assert "Final synthesized answer" in result
            assert len(orchestrator.agent_runs) == 4  # val + route + skills + answer

    def test_full_workflow_off_topic_question(self, orchestrator):
        """Full workflow should reject off-topic questions."""
        with patch("app.orchestration.validation_agent") as mock_val:
            mock_val.run.return_value = "OFF_TOPIC"

            result = orchestrator.run("What's the weather?")

            assert "I'm designed to answer questions about Kate's professional experience" in result
            assert len(orchestrator.agent_runs) == 1  # Only validation

    def test_workflow_respects_routing(self, orchestrator):
        """Workflow should only call agents specified in routing."""
        with patch("app.orchestration.validation_agent") as mock_val, \
             patch("app.orchestration.routing_agent") as mock_route, \
             patch("app.orchestration.resume_agent") as mock_resume, \
             patch("app.orchestration.skills_agent") as mock_skills, \
             patch("app.orchestration.project_agent") as mock_project, \
             patch("app.orchestration.answer_agent") as mock_answer:

            mock_val.run.return_value = "ON_TOPIC"
            mock_route.run.return_value = '{"agents": ["resume_agent"]}'
            mock_resume.run.return_value = "Resume info"
            mock_answer.run.return_value = "Final answer"

            orchestrator.run("Tell me about Kate's experience")

            # Resume agent should be called
            mock_resume.run.assert_called_once()
            # Other agents should NOT be called
            mock_skills.run.assert_not_called()
            mock_project.run.assert_not_called()


class TestDatabaseLogging:
    """Test database logging of agent runs."""

    def test_save_agent_runs_to_database(self, temp_db, orchestrator):
        """Agent runs should be saved to database."""
        # Create a session and question
        session = UserSession(session_id="test_session")
        temp_db.add(session)
        temp_db.commit()

        question = Question(
            session_id="test_session",
            question="Test question",
            created_at=datetime.utcnow()
        )
        temp_db.add(question)
        temp_db.commit()

        # Manually add agent runs
        orchestrator.agent_runs = [
            {
                "agent_name": "test_agent",
                "start_time": datetime.utcnow(),
                "end_time": datetime.utcnow(),
                "status": "success",
                "output": "Test output",
                "tools_called": "tool1,tool2",
                "tokens_used": 1200,
            }
        ]

        # Save to database
        orchestrator.save_agent_runs(question.id)

        # Verify in database
        runs = temp_db.query(AgentRun).filter(AgentRun.question_id == question.id).all()
        assert len(runs) == 1
        assert runs[0].agent_name == "test_agent"
        assert runs[0].status == "success"
        assert runs[0].output == "Test output"
        assert runs[0].tools_called == "tool1,tool2"
        assert runs[0].tokens_used == 1200

    def test_agent_run_has_correct_timing(self, temp_db, orchestrator):
        """Agent runs should have correct timing."""
        session = UserSession(session_id="test_session")
        temp_db.add(session)
        temp_db.commit()

        question = Question(session_id="test_session", question="Test")
        temp_db.add(question)
        temp_db.commit()

        start = datetime.utcnow()
        orchestrator._log_agent_run(
            agent_name="test_agent",
            start_time=start,
            end_time=datetime.utcnow(),
            status="success",
            output="Test"
        )

        orchestrator.save_agent_runs(question.id)

        runs = temp_db.query(AgentRun).filter(AgentRun.question_id == question.id).all()
        assert runs[0].start_time == start
        assert runs[0].end_time >= runs[0].start_time

    def test_multiple_agent_runs_logged(self, temp_db, orchestrator):
        """Multiple agent runs should all be logged."""
        session = UserSession(session_id="test_session")
        temp_db.add(session)
        temp_db.commit()

        question = Question(session_id="test_session", question="Test")
        temp_db.add(question)
        temp_db.commit()

        # Log multiple runs
        for i in range(3):
            orchestrator._log_agent_run(
                agent_name=f"agent_{i}",
                start_time=datetime.utcnow(),
                end_time=datetime.utcnow(),
                status="success",
                output=f"Output {i}"
            )

        orchestrator.save_agent_runs(question.id)

        runs = temp_db.query(AgentRun).filter(AgentRun.question_id == question.id).all()
        assert len(runs) == 3
        for i, run in enumerate(runs):
            assert run.agent_name == f"agent_{i}"


class TestErrorHandling:
    """Test error handling in orchestration."""

    def test_agent_failure_doesnt_crash_workflow(self, orchestrator):
        """Agent failure should not crash orchestration."""
        with patch("app.orchestration.resume_agent") as mock_resume, \
             patch("app.orchestration.skills_agent") as mock_skills:
            mock_resume.run.side_effect = Exception("API Error")
            mock_skills.run.return_value = "Skills info"

            outputs = orchestrator.run_specialized_agents(
                "Question",
                ["resume_agent", "skills_agent"]
            )

            # Skills agent output should still be captured
            assert "skills_agent" in outputs
            # Resume agent should have logged error
            assert any(r["status"] == "error" for r in orchestrator.agent_runs)

    def test_validation_error_returns_false(self, orchestrator):
        """Validation error should return False."""
        with patch("app.orchestration.validation_agent") as mock_agent:
            mock_agent.run.side_effect = Exception("Network error")

            result = orchestrator.validate_question("Question")

            assert result is False
            assert orchestrator.agent_runs[0]["status"] == "error"

    def test_routing_error_fallback(self, orchestrator):
        """Routing error should fallback to all agents."""
        with patch("app.orchestration.routing_agent") as mock_agent:
            mock_agent.run.side_effect = Exception("API error")

            result = orchestrator.route_question("Question")

            # Should return all three agents as fallback
            assert len(result) == 3
            assert orchestrator.agent_runs[0]["status"] == "error"


class TestTextExtraction:
    """Test text extraction from various response formats."""

    def test_extract_string_response(self, orchestrator):
        """Should extract text from string response."""
        result = orchestrator._extract_text("Simple string response")
        assert result == "Simple string response"

    def test_extract_dict_with_text_key(self, orchestrator):
        """Should extract text from dict with 'text' key."""
        response = {"text": "Extracted text"}
        result = orchestrator._extract_text(response)
        assert result == "Extracted text"

    def test_extract_dict_with_content_key(self, orchestrator):
        """Should extract text from dict with 'content' key."""
        response = {"content": "Content text"}
        result = orchestrator._extract_text(response)
        assert result == "Content text"

    def test_extract_object_with_text_attribute(self, orchestrator):
        """Should extract text from object with text attribute."""
        mock_obj = MagicMock()
        mock_obj.text = "Object text"
        result = orchestrator._extract_text(mock_obj)
        assert result == "Object text"
