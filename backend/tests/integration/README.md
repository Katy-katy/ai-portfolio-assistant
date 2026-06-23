# Integration Tests for Multi-Agent System

This directory contains comprehensive integration tests for the multi-agent orchestration system.

## Test Files

### `test_multi_agent_orchestration.py`
Tests for the `MultiAgentOrchestrator` class and agent workflow.

**Test Classes**:
- `TestValidationAgent` - Validates on/off-topic classification
- `TestRoutingAgent` - Tests agent routing logic
- `TestSpecializedAgents` - Tests resume, skills, and project agents
- `TestAnswerSynthesis` - Tests answer synthesis
- `TestFullOrchestration` - Tests complete workflow
- `TestDatabaseLogging` - Tests database persistence
- `TestErrorHandling` - Tests error scenarios
- `TestTextExtraction` - Tests response text extraction

**Example**:
```bash
uv run pytest tests/integration/test_multi_agent_orchestration.py -v
```

### `test_fastapi_endpoint.py`
Tests for the FastAPI `/run-multi-agent` endpoint.

**Test Classes**:
- `TestMultiAgentEndpoint` - Tests the POST endpoint
- `TestHealthEndpoint` - Tests health check
- `TestValidateQuestionEndpoint` - Tests validation endpoint
- `TestErrorHandling` - Tests error responses
- `TestConcurrentRequests` - Tests session isolation

**Example**:
```bash
uv run pytest tests/integration/test_fastapi_endpoint.py -v
```

## Running Tests

### All Tests
```bash
cd backend
uv run pytest tests/
```

### Integration Tests Only
```bash
uv run pytest tests/integration/
```

### Specific Test File
```bash
uv run pytest tests/integration/test_multi_agent_orchestration.py -v
```

### Specific Test Class
```bash
uv run pytest tests/integration/test_multi_agent_orchestration.py::TestValidationAgent -v
```

### Specific Test Function
```bash
uv run pytest tests/integration/test_multi_agent_orchestration.py::TestValidationAgent::test_validation_accepts_on_topic_question -v
```

### With Coverage
```bash
uv run pytest tests/integration/ --cov=app --cov-report=html
```

### With Output
```bash
uv run pytest tests/integration/ -v -s
```

## Test Coverage

### Orchestration Tests
- ✅ Validation agent on/off-topic classification
- ✅ Routing agent agent selection
- ✅ Specialized agent execution (resume, skills, project)
- ✅ Answer synthesis
- ✅ Full end-to-end workflow
- ✅ Database logging with timestamps
- ✅ Error handling and fallbacks
- ✅ Response text extraction

### Endpoint Tests
- ✅ Valid request handling
- ✅ Missing/empty parameter validation
- ✅ Session creation and management
- ✅ Question recording in database
- ✅ Answer persistence
- ✅ Agent runs logging
- ✅ Response format and metadata
- ✅ Error handling
- ✅ Session isolation
- ✅ Multiple questions per session

## Test Fixtures

### `temp_db`
Creates a temporary SQLite database for testing:
```python
@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
```

Usage:
```python
def test_something(temp_db):
    question = Question(session_id="test")
    temp_db.add(question)
    temp_db.commit()
```

### `orchestrator`
Creates an `MultiAgentOrchestrator` with test database:
```python
@pytest.fixture
def orchestrator(temp_db):
    """Create an orchestrator with test database."""
```

### `client`
Creates a FastAPI TestClient with test database:
```python
@pytest.fixture
def client(temp_db):
    """Create test client with test database."""
```

## Mocking

Tests use `unittest.mock` to mock external dependencies:

### Mocking Agents
```python
from unittest.mock import patch

with patch("app.orchestration.validation_agent") as mock_agent:
    mock_agent.run.return_value = "ON_TOPIC"
    # Test code
```

### Mocking Orchestrator
```python
with patch("app.orchestration.MultiAgentOrchestrator") as mock_class:
    mock = MagicMock()
    mock_class.return_value = mock
    mock.run.return_value = "Answer"
    # Test code
```

## Database Testing

Tests use temporary SQLite databases:

```python
def test_database_logging(temp_db, orchestrator):
    # Create test data
    session = UserSession(session_id="test")
    temp_db.add(session)
    temp_db.commit()
    
    # Verify in database
    sessions = temp_db.query(UserSession).all()
    assert len(sessions) == 1
```

## Common Patterns

### Testing Agent Success
```python
def test_agent_success(orchestrator):
    with patch("app.orchestration.validation_agent") as mock:
        mock.run.return_value = "ON_TOPIC"
        
        result = orchestrator.validate_question("Test")
        
        assert result is True
```

### Testing Agent Error
```python
def test_agent_error(orchestrator):
    with patch("app.orchestration.validation_agent") as mock:
        mock.run.side_effect = Exception("API Error")
        
        result = orchestrator.validate_question("Test")
        
        assert result is False
        assert orchestrator.agent_runs[0]["status"] == "error"
```

### Testing Endpoint
```python
def test_endpoint(client):
    response = client.post(
        "/run-multi-agent",
        json={
            "session_id": "test",
            "message": "Test question"
        }
    )
    
    assert response.status_code == 200
    assert response.json()["status"] == "success"
```

## Debugging Tests

### Run with Print Output
```bash
uv run pytest tests/integration/test_multi_agent_orchestration.py -v -s
```

### Run Single Test
```bash
uv run pytest tests/integration/test_multi_agent_orchestration.py::TestValidationAgent::test_validation_accepts_on_topic_question -v -s
```

### Run with Detailed Logging
```bash
uv run pytest tests/integration/ --log-cli-level=DEBUG
```

### Generate HTML Coverage Report
```bash
uv run pytest tests/integration/ --cov=app --cov-report=html
open htmlcov/index.html
```

## CI/CD Integration

### GitHub Actions Example
```yaml
- name: Run Integration Tests
  run: |
    cd backend
    uv run pytest tests/integration/ -v --cov=app
```

## Troubleshooting

### Import Errors
```bash
# Make sure you're in the backend directory
cd backend
uv run pytest tests/
```

### Database Locked
If you get "database is locked" errors:
- Tests use temporary files that auto-cleanup
- Make sure no other processes are using the test database
- Try clearing `__pycache__` and `.pytest_cache`

### Slow Tests
To profile slow tests:
```bash
uv run pytest tests/integration/ --durations=10
```

## Adding New Tests

1. Create test function in appropriate test class
2. Use fixtures for database and orchestrator access
3. Mock external dependencies with `patch`
4. Use clear assertion messages
5. Test both success and error cases

Example:
```python
def test_new_feature(orchestrator):
    """Test description."""
    with patch("app.orchestration.some_agent") as mock:
        mock.run.return_value = "Expected output"
        
        result = orchestrator.some_method("input")
        
        assert result == "Expected output"
        mock.run.assert_called_once_with("input")
```

## References

- [pytest Documentation](https://docs.pytest.org/)
- [unittest.mock Documentation](https://docs.python.org/3/library/unittest.mock.html)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)
