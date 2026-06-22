# CLAUDE.md - AI Portfolio Assistant Development Guide

This document provides architecture, commands, coding standards, and safety rules for the AI Portfolio Assistant project.

---

## 📋 Project Overview

**Kate's AI Portfolio Assistant** is a local prototype for a smart, conversational portfolio agent built with:
- **ADK 2.0** (Google Agent Development Kit)
- **FastAPI** backend with Gemini 3.5 Flash
- **Vanilla JS + HTML/CSS** frontend
- **SQLite** for persistent session storage

**Purpose**: Allow prospective employers and collaborators to chat with an AI agent to learn about Kate's skills, experience, and projects through a grounded (no-hallucination) conversational interface.

---

## 🏗️ Architecture

### Three-Tier Design

```
Frontend (SPA)
    ↓ HTTP/JSON
Backend (FastAPI + ADK 2.0)
    ├─ portfolio_agent (gemini-3.5-flash)
    ├─ 5 custom tools (markdown readers)
    └─ Session management
    ↓
SQLite Database (database/portfolio.db)
    ├─ user_sessions
    ├─ questions
    ├─ agent_runs
    └─ feedback
```

### Key Components

#### **Frontend** (`frontend/`)
- **index.html**: Main UI layout with glassmorphic design, light/dark theme toggle
- **app.js**: State management, API integration, message rendering, session handling
- **style.css**: Responsive styling with animations
- **Dependencies**: marked.js (Markdown rendering), FontAwesome (icons)

#### **Backend** (`backend/app/`)
- **agent.py**: Agent definition with Gemini model, instruction, and tools
- **tools.py**: 5 tools that read markdown files from `knowledge/`:
  - `get_resume()` → `knowledge/resume.md`
  - `get_skills()` → `knowledge/skills.md`
  - `get_aboutme()` → `knowledge/aboutme.md`
  - `get_projects_list()` → Lists `knowledge/projects/*.md`
  - `get_project_details(project_name)` → Loads specific project
- **fast_api_app.py**: FastAPI server setup, session service config, Cloud Logging
- **database.py**: SQLAlchemy ORM models and database initialization
- **app_utils/telemetry.py**: OpenTelemetry setup for prompt-response logging

#### **Knowledge Base** (`knowledge/`)
- Raw markdown files that ground the agent (prevent hallucinations)
- Structure:
  ```
  knowledge/
  ├── resume.md          # Full professional resume
  ├── skills.md          # Technical skills matrix
  ├── aboutme.md         # Career overview
  └── projects/
      ├── lamabot.md
      ├── babyyoda.md
      └── ticketclassification.md
  ```

#### **Database** (`database/`)
- SQLite database created automatically on backend startup
- Stores chat history, session metadata, feedback, and telemetry
- Location: `database/portfolio.db`

### Communication Flow

1. **Frontend sends message**: `POST /run` with session ID and user message
2. **Backend processes**: Agent runs, tools execute, Gemini generates response
3. **Backend returns**: Array of events (tool calls, agent responses)
4. **Frontend renders**: Tool badges, markdown content, typing indicators

---

## 🚀 Quick Start Commands

### Backend Setup & Running

```bash
# Navigate to backend
cd backend

# Install dependencies
uv sync

# Run development server with auto-reload
uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8000 --reload

# Access API docs at http://localhost:8000/docs
```

### Frontend

```bash
# Option 1: Open directly in browser
# Double-click frontend/index.html

# Option 2: Run HTTP server (avoids CORS issues)
cd frontend
python3 -m http.server 8080
# Visit http://localhost:8080
```

### Testing

```bash
cd backend

# Run all tests
uv run pytest tests/

# Run only unit tests
uv run pytest tests/unit/

# Run only integration tests
uv run pytest tests/integration/
```

### Linting & Code Quality

```bash
cd backend

# Run Ruff linter
uv run ruff check app/

# Format code
uv run ruff format app/

# Run type checking
uv run ty
```

### Agent Development Tools

```bash
cd backend

# Launch interactive playground
agents-cli playground

# Evaluate agent behavior
agents-cli eval

# Deploy to production
agents-cli deploy

# Enhance project with CI/CD
agents-cli scaffold enhance
```

---

## 💻 Coding Standards

### Python Backend

#### Style & Formatting
- **Line length**: 88 characters (Ruff default)
- **Formatter**: Ruff format
- **Linter**: Ruff with rules:
  - `E` (pycodestyle)
  - `F` (pyflakes)
  - `W` (warnings)
  - `I` (isort - import ordering)
  - `C` (flake8-comprehensions)
  - `B` (flake8-bugbear)
  - `UP` (pyupgrade)
  - `RUF` (ruff-specific)
- **Ignored**: E501 (line length), C901 (complexity), B006 (mutable defaults)

#### Type Hints
- Required for all function signatures
- Use Python 3.11+ syntax (`str | None` instead of `Optional[str]`)
- Enable type checking with `uv run ty`

#### Imports
- Organize with isort: stdlib → third-party → local
- Known first-party packages: `app`, `frontend`
- No wildcard imports

#### Documentation
- Add docstrings to all tools and public functions
- Format: Google-style docstrings with Args, Returns, Raises
- Example:
  ```python
  def get_resume() -> dict:
      """Gets Kate's full professional resume including experience, education, publications, and certifications.

      Returns:
          A dict containing Kate's complete resume text.
      """
  ```

#### Error Handling
- Use specific exception types, not bare `except`
- Log errors with context before raising
- Return error dicts from tools: `{"status": "error", "message": "..."}`

### JavaScript Frontend

#### Code Style
- **No linter configured** — use Ruff for backend only
- Manual conventions:
  - Camel case for variables/functions: `currentSessionId`, `fetchSessions()`
  - UPPER_CASE for constants: `API_BASE`, `USER_ID`
  - PascalCase for classes (if using OOP)

#### Modularity
- Top section: Configuration & global state
- Sections marked with `// ========` comments
- Group related functions (session, messaging, theme)

#### Error Handling
- Wrap fetch calls in try-catch
- Log errors to console with context
- Provide user-friendly fallback messages
- Never expose internal error details to UI

#### DOM Manipulation
- Use `querySelector`, not jQuery
- Event delegation for dynamic elements
- Clean up event listeners on removal

#### Performance
- Debounce rapid clicks on suggestion cards
- Lazy-load sessions (currently fetches all at once)
- Virtualize long message lists in future

### Markdown Files

#### Knowledge Base
- **Target audience**: LLM model (ensure clarity for AI parsing)
- **Format**: Valid Markdown with clear structure
- **Headers**: Use `#` for sections, `##` for subsections
- **Lists**: Use `-` for unordered, numbers for ordered
- **Code**: Use triple backticks with language identifier
- **Length**: Keep projects < 2000 words for context efficiency

---

## 🔒 Safety & Anti-Hallucination Rules

### Agent Design
1. **Tool-First Approach**: Agent MUST use tools to retrieve information. Tools read from markdown files on disk.
2. **No Out-of-Band Knowledge**: Agent is prohibited (via system prompt) from making up facts not in knowledge base.
3. **Instruction Clause**: System prompt explicitly states: "Do NOT make up (hallucinate) any experience, project details, or skills that are not present in the files."

### Tool Safety
- **No External APIs**: Tools only read local markdown files
- **Path Validation**: `get_project_details()` normalizes project names to prevent directory traversal
  - Converts to lowercase, strips whitespace, removes spaces
  - Validates `.md` file exists before reading
- **Error Reporting**: Tools return status codes and error messages instead of crashing
  - Success: `{"status": "success", "content": "..."}`
  - Error: `{"status": "error", "message": "..."}`

### Database Safety
- **SQLite**: No sensitive data stored (only chat history and metadata)
- **No passwords**: Credentials managed via environment variables (GCP auth)
- **SQL injection**: Protected by SQLAlchemy ORM (parameterized queries)

### Frontend Safety
- **CORS**: Configured for development (`allow_origins = ["*"]`)
  - **Change before production**: Restrict to specific domain
- **XSS Prevention**:
  - User messages: Rendered as plaintext, not HTML
  - Agent responses: Parsed with `marked.js` (handles sanitization)
  - No `innerHTML` for user input
- **API Validation**: Validate session IDs and user IDs from API responses

### Environment Variables
- **LOGS_BUCKET_NAME**: GCS bucket for telemetry (optional)
- **OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT**: "NO_CONTENT" mode (metadata only, no prompts)
- **ALLOW_ORIGINS**: Restrict CORS in production
- **GOOGLE_CLOUD_PROJECT**: Set automatically on startup

### Deployment Safety
- **Before Production**:
  - [ ] Set `ALLOW_ORIGINS` to specific domain
  - [ ] Enable `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`
  - [ ] Configure `LOGS_BUCKET_NAME` for telemetry
  - [ ] Set up Cloud Logging with proper retention
  - [ ] Review and update system prompt if needed
  - [ ] Test all tools with various inputs
  - [ ] Add rate limiting to `/run` and `/feedback` endpoints
  - [ ] Implement authentication (if needed)

---

## 📝 File Conventions

### Naming
- **Python files**: lowercase with underscores: `fast_api_app.py`, `test_agent.py`
- **JavaScript**: lowercase with underscores: `app.js`
- **CSS**: lowercase: `style.css`
- **Markdown**: Title-cased: `CLAUDE.md`, `architecture.md`

### Structure
```
ai-portfolio-assistant/
├── backend/                  # FastAPI + ADK backend
│   ├── app/
│   │   ├── __init__.py
│   │   ├── agent.py         # Agent definition
│   │   ├── tools.py         # Tool implementations
│   │   ├── database.py      # ORM models
│   │   ├── fast_api_app.py  # Server setup
│   │   └── app_utils/
│   │       ├── telemetry.py
│   │       └── typing.py
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── eval/
│   ├── pyproject.toml       # Dependencies
│   ├── README.md            # Backend-specific docs
│   └── agents-cli-manifest.yaml
├── frontend/                # Vanilla JS SPA
│   ├── index.html
│   ├── app.js
│   └── style.css
├── database/                # SQLite storage
│   └── portfolio.db         # Auto-created on startup
├── knowledge/               # Markdown grounding files
│   ├── resume.md
│   ├── skills.md
│   ├── aboutme.md
│   └── projects/
├── docs/
│   └── architecture.md
├── CLAUDE.md               # This file
└── README.md               # Project root docs
```

---

## 🔍 Testing Conventions

### Unit Tests
- **Location**: `backend/tests/unit/`
- **Pattern**: `test_<module>.py`
- **Naming**: `test_<function_name>`
- **Mocking**: Mock file I/O in tool tests
- **Assertions**: Use pytest syntax

Example:
```python
def test_get_skills_success(tmp_path):
    """Test successful skills retrieval."""
    skills_file = tmp_path / "skills.md"
    skills_file.write_text("# Skills\nPython\n")
    
    result = get_skills()  # Would need to mock BASE_DIR
    assert result["status"] == "success"
    assert "Python" in result["content"]
```

### Integration Tests
- **Location**: `backend/tests/integration/`
- **Pattern**: Test full workflows (agent + database)
- **Database**: Use temporary SQLite file
- **Example**: `test_agent.py`, `test_server_e2e.py`

### Evaluation Tests
- **Location**: `backend/tests/eval/`
- **Dataset**: `basic-dataset.json` (questions with expected outputs)
- **Config**: `eval_config.yaml`
- **Purpose**: Assess agent quality, grounding, tool usage

---

## 🎯 Key Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| **SQLite over Postgres** | Local development simplicity; files travel with project |
| **Vanilla JS over React** | Minimal dependencies for prototype; easier to review |
| **Markdown grounding** | Simple, version-controllable source of truth; prevents hallucinations |
| **ADK 2.0 framework** | Official Google framework; built-in session management, logging, deployment |
| **Gemini 3.5 Flash** | Fast, cost-effective, good for portfolio domain |
| **Tool-based design** | Transparent, auditable, user can see what files are being read |

---

## 🔧 Troubleshooting

### Backend won't start
```bash
# Check Python version (3.11+)
python3 --version

# Reinstall dependencies
cd backend && uv sync

# Clear cache
rm -rf .venv __pycache__ *.egg-info

# Check port 8000 isn't in use
lsof -i :8000
```

### Database issues
```bash
# Reset database (deletes all chat history)
rm database/portfolio.db

# Will be recreated on next backend start
```

### Frontend API errors
```bash
# Ensure backend is running on port 8000
# Check browser console (F12) for network errors
# Verify CORS headers: curl -i http://localhost:8000/docs
```

### Tool failures
- Check markdown files exist in `knowledge/` directory
- Verify file permissions (readable by backend process)
- Check file encoding (must be UTF-8)

---

## 📚 Related Documentation

- [README.md](README.md) — Quick start guide
- [docs/architecture.md](docs/architecture.md) — Detailed technical design
- [backend/README.md](backend/README.md) — Backend-specific commands
- [backend/GEMINI.md](backend/GEMINI.md) — AI-assisted development guide

---

## ✅ Pre-Interview Checklist

- [ ] Run `uv run pytest tests/` — all tests pass
- [ ] Run `uv run ruff check app/` — no linting errors
- [ ] Test all 5 tools in agent (resume, skills, projects, etc.)
- [ ] Test session creation, switching, deletion
- [ ] Test light/dark theme toggle
- [ ] Test suggested question cards
- [ ] Verify error handling (disconnect backend, try sending message)
- [ ] Review system prompt in `agent.py` — articulate anti-hallucination strategy
- [ ] Prepare talking points: architecture decisions, tool design, grounding strategy

---

**Last Updated**: 2026-06-22  
**Project Status**: Polished prototype, ready for interview discussions
