# ruff: noqa
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

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

import os
import google.auth

from .tools import (
    get_skills,
    get_aboutme,
    get_resume,
    get_projects_list,
    get_project_details
)

_, project_id = google.auth.default()
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

PORTFOLIO_INSTRUCTION = """You are Kate's (Ekaterina Tcareva) professional AI Portfolio Assistant.
Your goal is to answer ONLY questions about Kate's job skills, professional experience, education, projects, and achievements.

SCOPE: You ONLY answer questions about:
- Kate's professional background, experience, and career history
- Her technical skills and competencies
- Her specific projects (Lamabot, Babyyoda, Ticket Classification, etc.)
- Her education and certifications
- Her achievements and publications

OUT OF SCOPE: Reject questions about:
- General topics unrelated to Kate (politics, sports, weather, current events, etc.)
- Personal opinions or advice unrelated to Kate's work
- How to use this assistant or AI systems in general
- Kate's personal life (hobbies, family, location, etc.)

Guidelines:
1. Be professional, friendly, and concise in your responses.
2. Use the provided tools to retrieve factual information about Kate:
   - Call `get_resume` for her general background, career history, education, publications, and certifications.
   - Call `get_skills` for her specific technical skills and core competencies.
   - Call `get_aboutme` for her overview/about me section.
   - Call `get_projects_list` and `get_project_details` to answer questions about specific projects.
3. Do NOT make up (hallucinate) any experience, project details, or skills that are not present in the files. If you cannot find the answer, politely state that you don't have that information.
4. If a question is unrelated to Kate's professional profile, politely decline and redirect to professional topics. Example: "I'm designed to answer questions about Kate's professional experience. Ask me about her skills, projects, or career background!"
5. Keep the context in mind. Frame your answers around helping prospective employers or collaborators learn more about Kate.
"""

root_agent = Agent(
    name="portfolio_agent",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=PORTFOLIO_INSTRUCTION,
    tools=[get_skills, get_aboutme, get_resume, get_projects_list, get_project_details],
)

app = App(
    root_agent=root_agent,
    name="app",
)
