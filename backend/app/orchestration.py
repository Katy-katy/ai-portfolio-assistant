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

"""Multi-agent orchestration service.

Manages the workflow:
1. Validation - Check if question is on-topic
2. Routing - Determine which specialized agents to call
3. Specialization - Run relevant agents (resume, skills, project)
4. Synthesis - Generate final answer
5. Logging - Record all agent runs to database
"""

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .multi_agent import (
    validation_agent,
    routing_agent,
    resume_agent,
    skills_agent,
    project_agent,
    answer_agent,
)
from .database import AgentRun, Question

logger = logging.getLogger(__name__)


class MultiAgentOrchestrator:
    """Orchestrates multi-agent workflow for portfolio assistant."""

    def __init__(self, db: Session):
        """Initialize orchestrator with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.agent_runs: list[dict] = []

    def validate_question(self, question: str) -> bool:
        """Validate if question is on-topic.

        Args:
            question: User's question

        Returns:
            True if on-topic, False otherwise
        """
        start_time = datetime.utcnow()
        try:
            # Run validation agent
            response = validation_agent.run(question)
            end_time = datetime.utcnow()

            # Extract response text
            response_text = self._extract_text(response)
            is_valid = "ON_TOPIC" in response_text.upper()

            # Log agent run
            self._log_agent_run(
                agent_name="validation_agent",
                start_time=start_time,
                end_time=end_time,
                status="success",
                output=response_text,
            )

            return is_valid
        except Exception as e:
            logger.error(f"Validation agent failed: {str(e)}")
            end_time = datetime.utcnow()
            self._log_agent_run(
                agent_name="validation_agent",
                start_time=start_time,
                end_time=end_time,
                status="error",
                output=str(e),
            )
            return False

    def route_question(self, question: str) -> list[str]:
        """Route question to appropriate specialized agents.

        Args:
            question: User's question

        Returns:
            List of agent names to invoke
        """
        start_time = datetime.utcnow()
        try:
            # Run routing agent
            response = routing_agent.run(question)
            end_time = datetime.utcnow()

            # Extract response text and parse JSON
            response_text = self._extract_text(response)
            try:
                routing_result = json.loads(response_text)
                agents = routing_result.get("agents", [])
            except json.JSONDecodeError:
                logger.warning(f"Could not parse routing response: {response_text}")
                agents = ["resume_agent", "skills_agent", "project_agent"]

            # Log agent run
            self._log_agent_run(
                agent_name="routing_agent",
                start_time=start_time,
                end_time=end_time,
                status="success",
                output=response_text,
            )

            return agents
        except Exception as e:
            logger.error(f"Routing agent failed: {str(e)}")
            end_time = datetime.utcnow()
            self._log_agent_run(
                agent_name="routing_agent",
                start_time=start_time,
                end_time=end_time,
                status="error",
                output=str(e),
            )
            # Fallback: return all agents
            return ["resume_agent", "skills_agent", "project_agent"]

    def run_specialized_agents(
        self, question: str, agents_to_run: list[str]
    ) -> dict[str, str]:
        """Run specialized agents based on routing.

        Args:
            question: User's question
            agents_to_run: List of agent names to invoke

        Returns:
            Dict mapping agent names to their outputs
        """
        outputs = {}
        agent_map = {
            "resume_agent": resume_agent,
            "skills_agent": skills_agent,
            "project_agent": project_agent,
        }

        for agent_name in agents_to_run:
            if agent_name not in agent_map:
                logger.warning(f"Unknown agent: {agent_name}")
                continue

            start_time = datetime.utcnow()
            try:
                agent = agent_map[agent_name]
                response = agent.run(question)
                end_time = datetime.utcnow()

                # Extract response text
                response_text = self._extract_text(response)
                outputs[agent_name] = response_text

                # Log agent run
                self._log_agent_run(
                    agent_name=agent_name,
                    start_time=start_time,
                    end_time=end_time,
                    status="success",
                    output=response_text,
                )
            except Exception as e:
                logger.error(f"{agent_name} failed: {str(e)}")
                end_time = datetime.utcnow()
                self._log_agent_run(
                    agent_name=agent_name,
                    start_time=start_time,
                    end_time=end_time,
                    status="error",
                    output=str(e),
                )

        return outputs

    def synthesize_answer(
        self, question: str, specialized_outputs: dict[str, str]
    ) -> str:
        """Synthesize final answer from specialized agent outputs.

        Args:
            question: Original user question
            specialized_outputs: Outputs from specialized agents

        Returns:
            Final synthesized answer
        """
        start_time = datetime.utcnow()
        try:
            # Prepare synthesis prompt
            outputs_text = "\n".join(
                [f"## {agent}\n{output}" for agent, output in specialized_outputs.items()]
            )
            synthesis_prompt = f"""User Question: {question}

Agent Outputs:
{outputs_text}

Now synthesize these outputs into a cohesive, professional final answer."""

            # Run answer agent
            response = answer_agent.run(synthesis_prompt)
            end_time = datetime.utcnow()

            # Extract response text
            response_text = self._extract_text(response)

            # Log agent run
            self._log_agent_run(
                agent_name="answer_agent",
                start_time=start_time,
                end_time=end_time,
                status="success",
                output=response_text,
            )

            return response_text
        except Exception as e:
            logger.error(f"Answer agent failed: {str(e)}")
            end_time = datetime.utcnow()
            self._log_agent_run(
                agent_name="answer_agent",
                start_time=start_time,
                end_time=end_time,
                status="error",
                output=str(e),
            )
            # Fallback: return concatenated outputs
            return "\n".join(specialized_outputs.values()) or str(e)

    def run(self, question: str) -> str:
        """Run full orchestration workflow.

        Args:
            question: User's question

        Returns:
            Final synthesized answer
        """
        self.agent_runs = []

        # Step 1: Validate
        if not self.validate_question(question):
            return "I'm designed to answer questions about Kate's professional experience. Ask me about her skills, projects, or career background!"

        # Step 2: Route
        agents_to_run = self.route_question(question)

        # Step 3: Run specialized agents
        specialized_outputs = self.run_specialized_agents(question, agents_to_run)

        # Step 4: Synthesize
        final_answer = self.synthesize_answer(question, specialized_outputs)

        return final_answer

    def save_agent_runs(self, question_id: int) -> None:
        """Save all agent runs to database.

        Args:
            question_id: ID of the question in database
        """
        for run in self.agent_runs:
            agent_run = AgentRun(
                question_id=question_id,
                agent_name=run["agent_name"],
                start_time=run["start_time"],
                end_time=run["end_time"],
                status=run["status"],
                output=run.get("output"),
                tools_called=run.get("tools_called"),
                tokens_used=run.get("tokens_used"),
            )
            self.db.add(agent_run)
        self.db.commit()

    def _log_agent_run(
        self,
        agent_name: str,
        start_time: datetime,
        end_time: datetime,
        status: str,
        output: str | None = None,
        tools_called: str | None = None,
        tokens_used: int | None = None,
    ) -> None:
        """Log an agent run.

        Args:
            agent_name: Name of agent
            start_time: When agent started
            end_time: When agent ended
            status: success or error
            output: Agent output text
            tools_called: Comma-separated tool names called
            tokens_used: Number of tokens used
        """
        self.agent_runs.append(
            {
                "agent_name": agent_name,
                "start_time": start_time,
                "end_time": end_time,
                "status": status,
                "output": output,
                "tools_called": tools_called,
                "tokens_used": tokens_used,
            }
        )

    def _extract_text(self, response: Any) -> str:
        """Extract text from agent response.

        Args:
            response: Agent response (could be string, dict, or other)

        Returns:
            Extracted text
        """
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            if "text" in response:
                return response["text"]
            if "content" in response:
                return response["content"]
        if hasattr(response, "text"):
            return response.text
        if hasattr(response, "__str__"):
            return str(response)
        return str(response)
