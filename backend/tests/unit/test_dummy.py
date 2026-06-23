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
"""
Smoke tests for the portfolio assistant backend.
This is where you test your business logic, including agent functionality,
data processing, and other core components of your application.
"""
from fastapi.testclient import TestClient

from app.fast_api_app import app
from app.tools import is_question_on_topic


client = TestClient(app)


def test_health_endpoint() -> None:
    """Test that the health check endpoint returns a 200 status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "ok"


def test_question_on_topic_professional() -> None:
    """Test that professional questions are recognized as on-topic."""
    professional_questions = [
        "What projects did Kate work on?",
        "Tell me about her Python skills",
        "Where did Kate go to school?",
        "What's Kate's experience at LinkedIn?",
        "Tell me about the Lamabot project",
        "What certifications does Kate have?",
    ]
    for question in professional_questions:
        assert is_question_on_topic(question), f"Should recognize as on-topic: {question}"


def test_question_off_topic() -> None:
    """Test that off-topic questions are rejected."""
    off_topic_questions = [
        "What's the weather today?",
        "Tell me about quantum physics",
        "What are your thoughts on the latest movie?",
        "How do I cook pasta?",
        "What's 2+2?",
    ]
    for question in off_topic_questions:
        assert not is_question_on_topic(question), f"Should recognize as off-topic: {question}"


def test_validate_question_endpoint_on_topic() -> None:
    """Test the /validate-question endpoint with an on-topic question."""
    response = client.post("/validate-question", json={"text": "What are Kate's Python skills?"})
    assert response.status_code == 200
    data = response.json()
    assert data.get("is_on_topic") is True


def test_validate_question_endpoint_off_topic() -> None:
    """Test the /validate-question endpoint with an off-topic question."""
    response = client.post("/validate-question", json={"text": "What's the capital of France?"})
    assert response.status_code == 200
    data = response.json()
    assert data.get("is_on_topic") is False
    assert "professional experience" in data.get("message", "").lower()


def test_validate_question_endpoint_empty() -> None:
    """Test the /validate-question endpoint with empty input."""
    response = client.post("/validate-question", json={"text": ""})
    assert response.status_code == 200
    data = response.json()
    assert data.get("is_on_topic") is False
