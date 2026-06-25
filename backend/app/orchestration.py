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
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
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
from .tools import is_question_on_topic

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
        self._adk_session_service = InMemorySessionService()

    def validate_question(self, question: str) -> bool:
        """Validate if question is on-topic.

        Args:
            question: User's question

        Returns:
            True if on-topic, False otherwise
        """
        # Fast local guardrail: clearly profile-related questions should pass
        # even if the validation model is overly strict on wording.
        if self._is_clearly_on_topic(question):
            self._log_agent_run(
                agent_name="validation_agent",
                start_time=datetime.utcnow(),
                end_time=datetime.utcnow(),
                status="success",
                output="ON_TOPIC (local heuristic)",
            )
            return True

        start_time = datetime.utcnow()
        try:
            # Run validation agent
            response_text, tools_called = self._run_agent_text(
                agent=validation_agent,
                prompt=question,
                runner_prefix="validation",
            )
            end_time = datetime.utcnow()

            is_valid = "ON_TOPIC" in response_text.upper()

            # Log agent run
            self._log_agent_run(
                agent_name="validation_agent",
                start_time=start_time,
                end_time=end_time,
                status="success",
                output=response_text,
                tools_called=",".join(tools_called) if tools_called else None,
            )

            return is_valid
        except Exception as e:
            logger.error(f"Validation agent failed: {str(e)}")
            end_time = datetime.utcnow()
            # If the model call fails, fallback to keyword matcher rather than
            # rejecting the question outright.
            fallback_valid = is_question_on_topic(question)
            self._log_agent_run(
                agent_name="validation_agent",
                start_time=start_time,
                end_time=end_time,
                status="success" if fallback_valid else "error",
                output=(
                    f"ON_TOPIC (fallback keyword matcher) after error: {str(e)}"
                    if fallback_valid
                    else str(e)
                ),
            )
            return fallback_valid

    def _is_clearly_on_topic(self, question: str) -> bool:
        """Return True for clear profile-related questions.

        This reduces false negatives from the validation agent while keeping
        off-topic filtering strict for generic queries.
        """
        text = question.lower()

        # Mention of Kate/her profile context.
        has_profile_subject = bool(
            re.search(r"\b(kate|ekaterina|tcareva|her|she)\b", text)
        )

        # Professional/portfolio intent.
        has_professional_intent = bool(
            re.search(
                r"\b(experience|skills?|projects?|career|resume|cv|background|"
                r"education|certifications?|publications?|accomplishments?|"
                r"achievements?)\b",
                text,
            )
        )

        # Explicit domain phrases that are frequently asked.
        has_technical_focus = bool(
            re.search(r"\b(ai|ml|machine learning|llm|nlp|agent|python|fastapi)\b", text)
        )

        return has_profile_subject and (has_professional_intent or has_technical_focus)

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
            response_text, tools_called = self._run_agent_text(
                agent=routing_agent,
                prompt=question,
                runner_prefix="routing",
            )
            end_time = datetime.utcnow()

            # Parse JSON
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
                tools_called=",".join(tools_called) if tools_called else None,
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

        selected_agents: list[tuple[int, str, Any]] = []
        for order, agent_name in enumerate(agents_to_run):
            if agent_name not in agent_map:
                logger.warning(f"Unknown agent: {agent_name}")
                continue
            selected_agents.append((order, agent_name, agent_map[agent_name]))

        if not selected_agents:
            return outputs

        runs: list[dict[str, Any]] = []
        if len(selected_agents) == 1:
            order, agent_name, agent = selected_agents[0]
            runs.append(self._execute_specialized_agent(order, agent_name, agent, question))
        else:
            max_workers = min(3, len(selected_agents))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(
                        self._execute_specialized_agent,
                        order,
                        agent_name,
                        agent,
                        question,
                    ): (order, agent_name)
                    for order, agent_name, agent in selected_agents
                }

                for future in as_completed(future_map):
                    order, agent_name = future_map[future]
                    try:
                        runs.append(future.result())
                    except Exception as e:
                        logger.error(f"{agent_name} failed in parallel execution: {str(e)}")
                        end_time = datetime.utcnow()
                        runs.append(
                            {
                                "order": order,
                                "agent_name": agent_name,
                                "start_time": end_time,
                                "end_time": end_time,
                                "status": "error",
                                "output": str(e),
                                "tools_called": None,
                            }
                        )

        for run in sorted(runs, key=lambda item: item["order"]):
            if run["status"] == "success":
                outputs[run["agent_name"]] = run["output"]

            self._log_agent_run(
                agent_name=run["agent_name"],
                start_time=run["start_time"],
                end_time=run["end_time"],
                status=run["status"],
                output=run.get("output"),
                tools_called=run.get("tools_called"),
            )

        return outputs

    def _execute_specialized_agent(
        self,
        order: int,
        agent_name: str,
        agent: Any,
        question: str,
    ) -> dict[str, Any]:
        """Run one specialized agent and return structured run metadata."""
        start_time = datetime.utcnow()
        try:
            response_text, tools_called = self._run_agent_text(
                agent=agent,
                prompt=question,
                runner_prefix=agent_name,
            )
            end_time = datetime.utcnow()

            return {
                "order": order,
                "agent_name": agent_name,
                "start_time": start_time,
                "end_time": end_time,
                "status": "success",
                "output": response_text,
                "tools_called": ",".join(tools_called) if tools_called else None,
            }
        except Exception as e:
            logger.error(f"{agent_name} failed: {str(e)}")
            end_time = datetime.utcnow()
            return {
                "order": order,
                "agent_name": agent_name,
                "start_time": start_time,
                "end_time": end_time,
                "status": "error",
                "output": str(e),
                "tools_called": None,
            }

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
            response_text, tools_called = self._run_agent_text(
                agent=answer_agent,
                prompt=synthesis_prompt,
                runner_prefix="answer",
            )
            end_time = datetime.utcnow()

            # Log agent run
            self._log_agent_run(
                agent_name="answer_agent",
                start_time=start_time,
                end_time=end_time,
                status="success",
                output=response_text,
                tools_called=",".join(tools_called) if tools_called else None,
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

        # Fast path: if exactly one specialist returned output, skip synthesis.
        if len(specialized_outputs) == 1:
            return next(iter(specialized_outputs.values()))

        # Step 4: Synthesize
        final_answer = self.synthesize_answer(question, specialized_outputs)

        return final_answer

    def save_agent_runs(
        self,
        question_id: int,
        cache_request_stats: dict[str, Any] | None = None,
    ) -> None:
        """Save all agent runs to database.

        Args:
            question_id: ID of the question in database
            cache_request_stats: Request-level retrieval cache counters
        """
        for run in self.agent_runs:
            cache_stats = self._cache_stats_for_agent(
                agent_name=run["agent_name"],
                cache_request_stats=cache_request_stats,
            )
            latency_ms = int(
                max(
                    0.0,
                    (run["end_time"] - run["start_time"]).total_seconds() * 1000,
                )
            )
            agent_run = AgentRun(
                question_id=question_id,
                agent_name=run["agent_name"],
                start_time=run["start_time"],
                end_time=run["end_time"],
                status=run["status"],
                output=run.get("output"),
                tools_called=run.get("tools_called"),
                tokens_used=run.get("tokens_used"),
                latency_ms=latency_ms,
                cache_hits=cache_stats.get("hits"),
                cache_misses=cache_stats.get("misses"),
                cache_expired=cache_stats.get("expired"),
                cache_sets=cache_stats.get("sets"),
                cache_lookups=cache_stats.get("lookups"),
                cache_hit_rate=cache_stats.get("hit_rate"),
                cache_by_category=cache_stats.get("by_category"),
            )
            self.db.add(agent_run)
        self.db.commit()

    def _cache_stats_for_agent(
        self,
        agent_name: str,
        cache_request_stats: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Map request-level cache stats to a single agent run context."""
        if not cache_request_stats:
            return {}

        category_by_agent = {
            "resume_agent": "resume",
            "skills_agent": "skills",
            "project_agent": "projects",
        }
        by_category = cache_request_stats.get("by_category") or {}
        category = category_by_agent.get(agent_name)
        if not category:
            return {}

        category_stats = by_category.get(category, {}) if category else {}

        if category_stats:
            return {
                "hits": int(category_stats.get("hits", 0)),
                "misses": int(category_stats.get("misses", 0)),
                "expired": int(category_stats.get("expired", 0)),
                "sets": int(category_stats.get("sets", 0)),
                "lookups": int(category_stats.get("lookups", 0)),
                "hit_rate": float(category_stats.get("hit_rate", 0.0)),
                "by_category": json.dumps(
                    {category: category_stats},
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }

        return {}

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

    def _run_agent_text(
        self, agent: Any, prompt: str, runner_prefix: str
    ) -> tuple[str, list[str]]:
        """Run an ADK agent and normalize output text.

        For compatibility with existing tests that mock `agent.run(prompt)`,
        this first attempts the direct call. If that fails with ADK runtime
        signature errors, it falls back to Runner-based execution.
        """
        try:
            direct_response = agent.run(prompt)
            return self._extract_text(direct_response), []
        except TypeError as e:
            error_text = str(e)
            if "BaseNode.run()" not in error_text and "positional argument" not in error_text:
                raise
            return self._run_agent_with_runner(agent, prompt, runner_prefix)

    def _run_agent_with_runner(
        self, agent: Any, prompt: str, runner_prefix: str
    ) -> tuple[str, list[str]]:
        """Run agent using ADK Runner and extract final text output."""
        runner = Runner(
            app_name="portfolio_orchestrator",
            agent=agent,
            session_service=self._adk_session_service,
            auto_create_session=True,
        )

        session_id = f"{runner_prefix}-{uuid.uuid4()}"
        user_message = types.Content(
            role="user",
            parts=[types.Part(text=prompt)],
        )

        output_fragments: list[str] = []
        tools_called: list[str] = []
        for event in runner.run(
            user_id="portfolio_orchestrator",
            session_id=session_id,
            new_message=user_message,
        ):
            tool_name = self._extract_tool_name_from_event(event)
            if tool_name:
                tools_called.append(tool_name)
            text = self._extract_text_from_event(event)
            if text:
                output_fragments.append(text)

        return (
            "\n".join(fragment for fragment in output_fragments if fragment).strip(),
            tools_called,
        )

    def _extract_text_from_event(self, event: Any) -> str:
        """Extract human-readable text from ADK event payloads."""
        content = getattr(event, "content", None)
        if not content:
            return ""

        parts = getattr(content, "parts", None) or []
        texts: list[str] = []
        for part in parts:
            text = getattr(part, "text", None)
            if text:
                texts.append(text)

        return "\n".join(texts).strip()

    def _extract_tool_name_from_event(self, event: Any) -> str | None:
        """Extract tool name from ADK function-call event parts."""
        content = getattr(event, "content", None)
        if not content:
            return None

        parts = getattr(content, "parts", None) or []
        for part in parts:
            function_call = getattr(part, "function_call", None)
            if function_call and getattr(function_call, "name", None):
                return function_call.name

        return None
