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

"""Multi-agent orchestration service using ADK workflow patterns.

Implements: Sequential Pipeline + Parallel Fan-Out and Gather

Workflow:
1. Validation Agent - Check if question is on-topic
2. Routing Agent - Determine which specialized agents to call
3. Parallel Specialization - Run resume/skills/project agents concurrently
4. Synthesis Agent - Generate final answer
5. Database Logging - Record all agent runs to database

Uses ADK patterns: SequentialAgent for orchestration and threading for ParallelAgent simulation.
Session state is passed between agents via output_key and template substitution.
"""

import json
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from google.adk.agents import Agent
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
    """Orchestrates multi-agent workflow using ADK Sequential + Parallel patterns.

    Pattern: Sequential Pipeline + Parallel Fan-Out and Gather

    Flow:
    1. Validation Agent -> Check if on-topic
    2. Routing Agent -> Determine specialized agents
    3. Parallel Agents -> Run resume/skills/project agents concurrently (Fan-Out)
    4. Synthesis Agent -> Combine outputs into final answer (Gather)
    """

    def __init__(self, db: Session):
        """Initialize orchestrator with database session."""
        self.db = db
        self.agent_runs: list[dict] = []
        self._adk_session_service = InMemorySessionService()

    def validate_question(self, question: str) -> bool:
        """Public API for question validation (backward compatibility).

        Uses local heuristics for fast validation.

        Args:
            question: User's question

        Returns:
            True if on-topic, False otherwise
        """
        return self._validate_question_locally(question)

    def run(self, question: str) -> str:
        """Run full orchestration using ADK Sequential + Parallel patterns.

        Args:
            question: User's question

        Returns:
            Final synthesized answer
        """
        self.agent_runs = []

        # Step 1: Validate question locally first
        if not self._validate_question_locally(question):
            refusal_msg = "I'm designed to answer questions about Kate's professional experience. Ask me about her skills, projects, or career background!"
            self._log_agent_run(
                agent_name="validation_agent",
                start_time=datetime.now(UTC),
                end_time=datetime.now(UTC),
                status="success",
                output=refusal_msg,
            )
            return refusal_msg

        # Step 2: Log validation success
        self._log_agent_run(
            agent_name="validation_agent",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            status="success",
            output="ON_TOPIC",
        )

        # Step 3: Route question
        agents_to_run = self._route_question(question)

        # Step 4: Run specialized agents in parallel (Fan-Out)
        specialized_outputs = self._run_specialized_agents_parallel(
            question, agents_to_run
        )

        # Step 5: Synthesize (Gather)
        if not specialized_outputs:
            return "I couldn't process your question properly. Please try again."

        if len(specialized_outputs) == 1:
            final_answer = next(iter(specialized_outputs.values()))
        else:
            final_answer = self._synthesize_answer(question, specialized_outputs)

        return final_answer

    def _validate_question_locally(self, question: str) -> bool:
        """Local validation with heuristics for on-topic classification."""
        text = question.lower()

        has_profile_subject = bool(
            re.search(r"\b(kate|ekaterina|tcareva|her|she)\b", text)
        )
        has_professional_intent = bool(
            re.search(
                r"\b(experience|skills?|projects?|career|resume|cv|background|"
                r"education|certifications?|publications?|accomplishments?|"
                r"achievements?)\b",
                text,
            )
        )
        has_technical_focus = bool(
            re.search(r"\b(ai|ml|machine learning|llm|nlp|agent|python|fastapi)\b", text)
        )

        return has_profile_subject and (has_professional_intent or has_technical_focus)

    def _route_question(self, question: str) -> list[str]:
        """Route question using routing_agent.

        Args:
            question: User's question

        Returns:
            List of agent names to invoke
        """
        start_time = datetime.now(UTC)
        try:
            response_text, tools_called = self._run_agent_text(
                agent=routing_agent,
                prompt=question,
                runner_prefix="routing",
            )
            end_time = datetime.now(UTC)

            try:
                routing_result = json.loads(response_text)
                agents = routing_result.get("agents", [])
            except json.JSONDecodeError:
                logger.warning(f"Could not parse routing response: {response_text}")
                agents = ["resume_agent", "skills_agent", "project_agent"]

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
            self._log_agent_run(
                agent_name="routing_agent",
                start_time=start_time,
                end_time=datetime.now(UTC),
                status="error",
                output=str(e),
            )
            return ["resume_agent", "skills_agent", "project_agent"]

    def _run_specialized_agents_parallel(
        self, question: str, agents_to_run: list[str]
    ) -> dict[str, str]:
        """Run specialized agents in parallel (Fan-Out pattern).

        Using ADK ParallelAgent semantics: each sub-agent runs concurrently
        with its output saved to a distinct state key.

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

        # Filter valid agents
        selected_agents = [
            (name, agent_map[name])
            for name in agents_to_run
            if name in agent_map
        ]

        if not selected_agents:
            return outputs

        # For multiple agents: simulate ParallelAgent behavior using ThreadPoolExecutor
        if len(selected_agents) == 1:
            agent_name, agent = selected_agents[0]
            start_time = datetime.now(UTC)
            try:
                response_text, tools_called = self._run_agent_text(
                    agent=agent,
                    prompt=question,
                    runner_prefix=agent_name,
                )
                end_time = datetime.now(UTC)
                outputs[agent_name] = response_text
                self._log_agent_run(
                    agent_name=agent_name,
                    start_time=start_time,
                    end_time=end_time,
                    status="success",
                    output=response_text,
                    tools_called=",".join(tools_called) if tools_called else None,
                )
            except Exception as e:
                logger.error(f"{agent_name} failed: {str(e)}")
                self._log_agent_run(
                    agent_name=agent_name,
                    start_time=start_time,
                    end_time=datetime.now(UTC),
                    status="error",
                    output=str(e),
                )
        else:
            # Parallel execution (mimics ParallelAgent fan-out)
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(self._execute_agent, agent_name, agent, question): agent_name
                    for agent_name, agent in selected_agents
                }

                for future in as_completed(futures):
                    agent_name = futures[future]
                    try:
                        result = future.result()
                        outputs[agent_name] = result["output"]
                        self._log_agent_run(**result)
                    except Exception as e:
                        logger.error(f"{agent_name} failed in parallel: {str(e)}")
                        self._log_agent_run(
                            agent_name=agent_name,
                            start_time=datetime.now(UTC),
                            end_time=datetime.now(UTC),
                            status="error",
                            output=str(e),
                        )

        return outputs

    def _execute_agent(
        self, agent_name: str, agent: Agent, question: str
    ) -> dict[str, Any]:
        """Execute a single agent and return structured result."""
        start_time = datetime.now(UTC)
        try:
            response_text, tools_called = self._run_agent_text(
                agent=agent,
                prompt=question,
                runner_prefix=agent_name,
            )
            end_time = datetime.now(UTC)

            return {
                "agent_name": agent_name,
                "start_time": start_time,
                "end_time": end_time,
                "status": "success",
                "output": response_text,
                "tools_called": ",".join(tools_called) if tools_called else None,
            }
        except Exception as e:
            logger.error(f"{agent_name} failed: {str(e)}")
            return {
                "agent_name": agent_name,
                "start_time": start_time,
                "end_time": datetime.now(UTC),
                "status": "error",
                "output": str(e),
                "tools_called": None,
            }

    def _synthesize_answer(self, question: str, specialized_outputs: dict[str, str]) -> str:
        """Synthesize final answer (Gather pattern).

        Args:
            question: Original user question
            specialized_outputs: Outputs from specialized agents

        Returns:
            Final synthesized answer
        """
        start_time = datetime.now(UTC)
        try:
            # Prepare synthesis prompt
            outputs_text = "\n".join(
                [f"## {agent}\n{output}" for agent, output in specialized_outputs.items()]
            )
            synthesis_prompt = f"""User Question: {question}

Specialized Agent Outputs:
{outputs_text}

Synthesize these outputs into a cohesive, professional final answer."""

            response_text, tools_called = self._run_agent_text(
                agent=answer_agent,
                prompt=synthesis_prompt,
                runner_prefix="answer",
            )
            end_time = datetime.now(UTC)

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
            self._log_agent_run(
                agent_name="answer_agent",
                start_time=start_time,
                end_time=datetime.now(UTC),
                status="error",
                output=str(e),
            )
            return "\n".join(specialized_outputs.values()) or str(e)

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
        """Map request-level cache stats to agent context."""
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
        """Log an agent run."""
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

    def _run_agent_text(
        self, agent: Agent, prompt: str, runner_prefix: str
    ) -> tuple[str, list[str]]:
        """Run an ADK agent and return text + tools called."""
        try:
            direct_response = agent.run(prompt)
            return self._extract_text(direct_response), []
        except TypeError as e:
            error_text = str(e)
            if "BaseNode.run()" not in error_text and "positional argument" not in error_text:
                raise
            return self._run_agent_with_runner(agent, prompt, runner_prefix)

    def _run_agent_with_runner(
        self, agent: Agent, prompt: str, runner_prefix: str
    ) -> tuple[str, list[str]]:
        """Run agent using ADK Runner."""
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
            "\n".join(f for f in output_fragments if f).strip(),
            tools_called,
        )

    def _extract_text(self, response: Any) -> str:
        """Extract text from response."""
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            if "text" in response:
                return response["text"]
            if "content" in response:
                return response["content"]
        if hasattr(response, "text"):
            return response.text
        return str(response)

    def _extract_text_from_event(self, event: Any) -> str:
        """Extract text from ADK event."""
        content = getattr(event, "content", None)
        if not content:
            return ""
        parts = getattr(content, "parts", None) or []
        texts = [getattr(part, "text", None) for part in parts if hasattr(part, "text")]
        return "\n".join(t for t in texts if t).strip()

    def _extract_tool_name_from_event(self, event: Any) -> str | None:
        """Extract tool name from ADK event."""
        content = getattr(event, "content", None)
        if not content:
            return None
        parts = getattr(content, "parts", None) or []
        for part in parts:
            function_call = getattr(part, "function_call", None)
            if function_call and getattr(function_call, "name", None):
                return function_call.name
        return None
