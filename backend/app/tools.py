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

# Resolve the project root directory
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def get_skills() -> dict:
    """Gets Kate's core technical skills and competencies.

    Returns:
        A dict containing the technical skills classified by category.
    """
    path = os.path.join(BASE_DIR, "knowledge", "skills.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "content": content}
    except Exception as e:
        return {"status": "error", "message": f"Could not read skills: {str(e)}"}

def get_aboutme() -> dict:
    """Gets background information about Kate.

    Returns:
        A dict containing Kate's professional summary.
    """
    path = os.path.join(BASE_DIR, "knowledge", "aboutme.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "content": content}
    except Exception as e:
        return {"status": "error", "message": f"Could not read aboutme: {str(e)}"}

def get_resume() -> dict:
    """Gets Kate's full professional resume including experience, education, publications, and certifications.

    Returns:
        A dict containing Kate's complete resume text.
    """
    path = os.path.join(BASE_DIR, "knowledge", "resume.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "content": content}
    except Exception as e:
        return {"status": "error", "message": f"Could not read resume: {str(e)}"}

def get_projects_list() -> dict:
    """Gets a list of projects Kate has worked on.

    Returns:
        A dict containing a list of project names.
    """
    projects_dir = os.path.join(BASE_DIR, "knowledge", "projects")
    try:
        if not os.path.exists(projects_dir):
            return {"status": "success", "projects": []}
        projects = [f.replace(".md", "") for f in os.listdir(projects_dir) if f.endswith(".md")]
        return {"status": "success", "projects": projects}
    except Exception as e:
        return {"status": "error", "message": f"Could not list projects: {str(e)}"}

def get_project_details(project_name: str) -> dict:
    """Gets detailed information about a specific project including role, problem, contributions, and technologies used.

    Args:
        project_name: The name of the project (e.g. 'lamabot', 'babyyoda', 'ticketclassification').

    Returns:
        A dict containing the details of the project.
    """
    # Normalize project name
    name = project_name.lower().strip().replace(" ", "")
    path = os.path.join(BASE_DIR, "knowledge", "projects", f"{name}.md")
    try:
        if not os.path.exists(path):
            return {"status": "error", "message": f"Project '{project_name}' not found."}
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "content": content}
    except Exception as e:
        return {"status": "error", "message": f"Could not read project details: {str(e)}"}
