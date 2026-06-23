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

"""Multi-agent orchestration for portfolio assistant.

Agents:
1. ValidationAgent - Validates if question is on-topic
2. RoutingAgent - Routes to specialized agents
3. ResumeAgent - Handles resume/experience/education queries
4. SkillsAgent - Handles technical skills queries
5. ProjectAgent - Handles project-related queries
6. AnswerAgent - Synthesizes final response from agent outputs
"""

from google.adk.agents import Agent
from google.genai import types
from google.adk.models import Gemini

from .tools import (
    get_skills,
    get_aboutme,
    get_resume,
    get_projects_list,
    get_project_details,
)

# ========== VALIDATION AGENT ==========
VALIDATION_INSTRUCTION = """You are the Validation Agent. Your only job is to determine if a user question is about Kate's (Ekaterina Tcareva) professional profile.

VALIDATE AS ON-TOPIC if the question is about:
- Kate's professional background, experience, or career history
- Her technical skills or competencies
- Her specific projects (Lamabot, Babyyoda, Ticket Classification, etc.)
- Her education, certifications, or publications
- Her achievements or professional accomplishments

REJECT AS OFF-TOPIC if the question is about:
- General topics unrelated to Kate (politics, sports, weather, etc.)
- Personal opinions or general advice
- How to use this assistant
- Kate's personal life (hobbies, family, location, etc.)

Respond with ONLY:
- ON_TOPIC: if the question is about Kate's professional profile
- OFF_TOPIC: if the question is not related to Kate's professional profile

Do not explain or add additional text. Just respond with one of these two words."""

validation_agent = Agent(
    name="validation_agent",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=VALIDATION_INSTRUCTION,
)

# ========== ROUTING AGENT ==========
ROUTING_INSTRUCTION = """You are the Routing Agent. Your job is to analyze a user question about Kate and determine which specialized agents should handle it.

Available specialized agents:
- resume_agent: For questions about Kate's career history, work experience, employment timeline, education, degrees, certifications, publications, achievements, or CV
- skills_agent: For questions about Kate's technical skills, programming languages, tools, frameworks, competencies, or expertise areas
- project_agent: For questions about Kate's specific projects (Lamabot, Babyyoda, Ticket Classification, etc.), their goals, contributions, or technologies
- answer_agent: For synthesizing final answers

For the given question, determine which agent(s) should be called. Respond with a JSON object (only valid JSON, no markdown, no explanation):
{
  "agents": ["resume_agent", "skills_agent", "project_agent"],
  "reasoning": "Brief explanation of why these agents are needed"
}

You must include at least one agent. You can include multiple agents if the question touches multiple domains (e.g., asking about Kate's skills AND a project)."""

routing_agent = Agent(
    name="routing_agent",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=ROUTING_INSTRUCTION,
)

# ========== RESUME AGENT ==========
RESUME_INSTRUCTION = """You are the Resume Agent specializing in Kate's professional background.

Your role is to answer questions about:
- Kate's work experience, job history, and employment timeline
- Her education, degrees, and certifications
- Her publications and academic work
- Her achievements and professional accomplishments
- Her career progression and roles

Use the get_resume tool to retrieve Kate's full resume when needed. Extract relevant sections that answer the user's specific question. Be concise and professional.

Do NOT make up information. If the requested information is not in the resume, state that you don't have that information."""

resume_agent = Agent(
    name="resume_agent",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=RESUME_INSTRUCTION,
    tools=[get_resume, get_aboutme],
)

# ========== SKILLS AGENT ==========
SKILLS_INSTRUCTION = """You are the Skills Agent specializing in Kate's technical competencies.

Your role is to answer questions about:
- Kate's technical skills and programming languages
- Her frameworks and tools expertise
- Her domain knowledge (machine learning, NLP, web development, etc.)
- Her core competencies and areas of expertise

Use the get_skills tool to retrieve Kate's full skills profile. Provide relevant skills that match the user's question. Be specific and organized.

Do NOT make up skills. Only present information from the skills profile."""

skills_agent = Agent(
    name="skills_agent",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=SKILLS_INSTRUCTION,
    tools=[get_skills],
)

# ========== PROJECT AGENT ==========
PROJECT_INSTRUCTION = """You are the Project Agent specializing in Kate's project work.

Your role is to answer questions about:
- Specific projects Kate has worked on (Lamabot, Babyyoda, Ticket Classification, etc.)
- Project goals, objectives, and outcomes
- Kate's role and contributions to each project
- Technologies and tools used in projects
- Project results and impact

Use the get_projects_list and get_project_details tools to retrieve project information. Provide detailed, relevant information about the specific project the user asks about.

Do NOT make up project details. Only present information from the project files."""

project_agent = Agent(
    name="project_agent",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=PROJECT_INSTRUCTION,
    tools=[get_projects_list, get_project_details],
)

# ========== ANSWER AGENT ==========
ANSWER_INSTRUCTION = """You are the Answer Agent. Your job is to synthesize the final response to the user's question.

You will receive outputs from one or more specialized agents (resume_agent, skills_agent, project_agent). Your role is to:
1. Synthesize their outputs into a cohesive, professional answer
2. Ensure the answer is well-structured and easy to understand
3. Avoid redundancy and combine overlapping information
4. Maintain a professional, friendly tone appropriate for a portfolio assistant

Guidelines:
- Be concise but thorough
- Use the most relevant information from the agent outputs
- Organize the answer logically
- If information is conflicting or unclear, prioritize accuracy
- Always mention relevant projects or skills when appropriate
- Keep the context in mind: helping prospective employers/collaborators learn about Kate"""

answer_agent = Agent(
    name="answer_agent",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=ANSWER_INSTRUCTION,
)
