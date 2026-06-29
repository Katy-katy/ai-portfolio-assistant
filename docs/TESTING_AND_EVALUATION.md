# Testing and Evaluation Guide

This document describes the testing framework and evaluation system for the AI Portfolio Assistant.

---

## 🧪 Testing Architecture

The project uses a **three-tier testing approach**:

### 1. Unit Tests (`tests/unit/`)

Basic functionality tests for individual components.

**Run unit tests:**
```bash
cd backend
uv run pytest tests/unit/
```

**Example test file:** `test_dummy.py`

---

### 2. Integration Tests (`tests/integration/`)

Comprehensive tests for multi-agent orchestration, FastAPI endpoints, and system workflows.

#### **`test_multi_agent_orchestration.py`**

Tests the `MultiAgentOrchestrator` class and agent workflow.

**Test Classes:**
- `TestValidationAgent` — Validates on/off-topic classification
- `TestRoutingAgent` — Tests agent routing logic
- `TestSpecializedAgents` — Tests resume, skills, and project agents
- `TestAnswerSynthesis` — Tests answer synthesis
- `TestFullOrchestration` — Tests complete workflow end-to-end
- `TestDatabaseLogging` — Tests database persistence
- `TestErrorHandling` — Tests error scenarios and recovery
- `TestTextExtraction` — Tests response text extraction

**Run these tests:**
```bash
uv run pytest tests/integration/test_multi_agent_orchestration.py -v
```

#### **`test_fastapi_endpoint.py`**

Tests the FastAPI `/run-multi-agent` endpoint.

**Test Classes:**
- `TestMultiAgentEndpoint` — Tests POST endpoint behavior
- `TestHealthEndpoint` — Tests health check
- `TestValidateQuestionEndpoint` — Tests validation endpoint
- `TestErrorHandling` — Tests error responses
- `TestConcurrentRequests` — Tests session isolation

**Run these tests:**
```bash
uv run pytest tests/integration/test_fastapi_endpoint.py -v
```

#### **`test_server_e2e.py`**

End-to-end server tests.

#### **Run all integration tests:**
```bash
uv run pytest tests/integration/ -v
```

#### **Run all tests (unit + integration):**
```bash
uv run pytest tests/ -v
```

---

## 📊 Evaluation System

### Overview

The evaluation system uses a **golden dataset** of 30 hand-crafted questions to assess agent quality. Questions are scored using **LLM-as-judge** (Gemini 2.5 Flash) with 7 semantic metrics.

**Dataset location:** `backend/tests/eval/datasets/eval_questions.json`

**Evaluation script:** `backend/scripts/run_evals.py`

### Dataset Structure

Each eval case contains:

```json
{
  "id": "q01_skills_overview",
  "question": "What are Kate's core AI and NLP skills?",
  "expected_topics": ["ai", "nlp", "skills"],
  "expected_project_references": [],
  "expected_key_points": [
    "Kate has AI and NLP expertise",
    "Mentions LLM or generative AI capabilities",
    "Mentions frameworks/tools relevant to ML/NLP"
  ],
  "forbidden_claims": [
    "Unrelated personal details",
    "Claims not present in profile context"
  ],
  "should_refuse": false
}
```

### Question Categories

| Category | Count | Purpose |
|----------|-------|---------|
| **Answerable** | 20 | Core skill, experience, and project questions |
| **Refusable** | 5 | Off-topic (weather, politics, sports, personal) |
| **Hallucination Guards** | 5 | Mixed topics, unsupported claims (e.g., SpaceX robotics) |

**Examples of question types:**
- ✅ "What are Kate's core AI and NLP skills?"
- ✅ "Tell me more about Lamabot and what problem it solved."
- ✅ "How has Kate built LLM agents in production?"
- ❌ "What is the weather in San Francisco today?" (should refuse)
- ❌ "Did Kate build robotics systems at SpaceX?" (hallucination guard)

---

## 📈 Scoring System

### 7 Key Metrics

Each eval case is scored on 0-1 scale by Gemini LLM:

| Metric | Scale | Description |
|--------|-------|-------------|
| **semantic_relevance** | 0-1 | Does answer address the question and expected topics? |
| **factual_grounding** | 0-1 | Are claims grounded in knowledge base (no hallucinations)? |
| **completeness** | 0-1 | Are expected key points and project references covered? |
| **clarity** | 0-1 | Is answer clear, well-structured, and concise? |
| **refusal_appropriateness** | 0-1 | Are off-topic questions refused correctly? |
| **overall_semantic_score** | 0-1 | Aggregate quality score combining all above |
| **topic_coverage** | 0-1 | Percentage of expected topics found in answer |

### Pass Logic

An eval case **PASSES** if:

#### For Answerable Questions (`should_refuse=false`):
1. ✅ **Topic coverage** ≥ 50%
2. ✅ **Project coverage** ≥ 50% (if applicable)
3. ✅ **Refusal detection** is correct (false positives = fail)
4. ✅ **overall_semantic_score** ≥ 0.65 (configurable threshold)

#### For Refusal Questions (`should_refuse=true`):
1. ✅ **Refusal detected** correctly
2. ✅ **refusal_appropriateness** ≥ 0.65

### Refusal Detection

The system looks for refusal markers in the answer:
```python
REFUSAL_MARKERS = (
    "i'm designed to answer questions about kate's professional experience",
    "ask me about her skills, projects, or career background",
)
```

---

## 🚀 Running Evaluations

### Prerequisites

Ensure the backend is running:
```bash
cd backend
uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8000 --reload
```

### Default Evaluation (All 30 Questions)

```bash
cd backend
uv run python scripts/run_evals.py
```

### With Options

```bash
uv run python scripts/run_evals.py \
  --base-url http://localhost:8000 \
  --dataset tests/eval/datasets/eval_questions.json \
  --limit 10                              # Run only first 10 questions
  --judge-model gemini-2.5-flash         # LLM judge model
  --semantic-threshold 0.65               # Pass threshold (0-1)
  --disable-semantic                      # Skip LLM judge (fast check)
```

### Command-Line Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--base-url` | `http://localhost:8000` | Backend API URL |
| `--dataset` | `tests/eval/datasets/eval_questions.json` | Path to eval dataset |
| `--limit` | 0 (all) | Max questions to run |
| `--judge-model` | `gemini-2.5-flash` | LLM model for scoring |
| `--semantic-threshold` | 0.65 | Pass threshold for semantic score |
| `--disable-semantic` | false | Skip LLM judge (checks only coverage/refusal) |

### Output Examples

```
Running 30 eval cases (run_id=abc123def456)
[1/30] q01_skills_overview ... PASS
[2/30] q02_resume_summary ... PASS
[3/30] q03_linkedin_projects ... PASS
...
[30/30] q30_followup_projects ... PASS

Summary:
- Total: 30
- Passed: 29
- Failed: 1
- Topic Coverage Avg: 0.92
- Overall Semantic Score Avg: 0.87
```

---

## 💾 Results Storage

### Database Schema

Evaluation results are stored in SQLite (`database/portfolio.db`):

**Table:** `eval_results`

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | UUID | Unique evaluation run identifier |
| `eval_case_id` | String | Case ID from dataset |
| `question` | String | Original question |
| `expected_topics` | JSON | Expected topic array |
| `expected_projects` | JSON | Expected project references |
| `expected_key_points` | JSON | Expected key points |
| `forbidden_claims` | JSON | Forbidden claims array |
| `should_refuse` | Integer | 1 if should refuse, 0 otherwise |
| `answer` | String | Agent's response (full text) |
| `topic_coverage` | Float | 0-1 coverage score |
| `project_coverage` | Float | 0-1 coverage score |
| `refusal_correct` | Integer | 1 if refusal behavior correct |
| `semantic_relevance` | Float | 0-1 judge score |
| `factual_grounding` | Float | 0-1 judge score |
| `completeness` | Float | 0-1 judge score |
| `clarity` | Float | 0-1 judge score |
| `refusal_appropriateness` | Float | 0-1 judge score |
| `overall_semantic_score` | Float | 0-1 judge score |
| `semantic_pass` | Integer | 1 if semantic score ≥ threshold |
| `judge_model` | String | Model used for scoring |
| `passed` | Integer | 1 if case passed overall |
| `created_at` | Timestamp | When result was created |

### Querying Results

```bash
# Query most recent eval run
sqlite3 database/portfolio.db \
  "SELECT run_id, COUNT(*), AVG(overall_semantic_score) 
   FROM eval_results 
   GROUP BY run_id 
   ORDER BY created_at DESC 
   LIMIT 1;"

# Export results to CSV
sqlite3 database/portfolio.db \
  ".mode csv" \
  ".output eval_results.csv" \
  "SELECT * FROM eval_results WHERE run_id='<your-run-id>';"
```

---

## 🔧 Troubleshooting

### Backend Not Responding
```bash
# Check if backend is running
curl http://localhost:8000/health

# If not, start it
cd backend
uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8000 --reload
```

### Eval Script Timeout
```bash
# Increase timeout or run with smaller limit
uv run python scripts/run_evals.py --limit 5
```

### Database Errors
```bash
# Reset database (deletes all results)
rm database/portfolio.db

# Database will be recreated on next run
uv run python scripts/run_evals.py
```

### Import Errors
```bash
# Ensure dependencies are installed
cd backend
uv sync
```

---

## 📚 Related Documentation

- [CLAUDE.md](../CLAUDE.md) — Project architecture and setup
- [architecture.md](architecture.md) — Technical design
- [INTEGRATION_TESTS_SUMMARY.md](INTEGRATION_TESTS_SUMMARY.md) — Integration test details
- [backend/tests/eval/datasets/eval_questions.json](../backend/tests/eval/datasets/eval_questions.json) — Full eval dataset

---

## ✅ Best Practices

1. **Run evals frequently** — After code changes to catch regressions
2. **Track eval runs** — Use `run_id` to compare performance over time
3. **Use semantic threshold** — Adjust based on quality requirements (0.6-0.8)
4. **Review failures** — Check `notes` and `judge_raw` for failure reasons
5. **Iterate on agent prompt** — Use eval feedback to improve agent behavior

---

**Last Updated**: 2026-06-29
