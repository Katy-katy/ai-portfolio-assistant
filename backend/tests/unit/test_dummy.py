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


client = TestClient(app)


def test_health_endpoint() -> None:
    """Test that the health check endpoint returns a 200 status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "ok"
