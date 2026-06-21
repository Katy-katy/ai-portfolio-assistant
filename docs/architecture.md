# Architecture & Design Document

This document describes the design, directory layout, and running instructions for the local prototype of the **AI Portfolio Assistant**.

---

## Directory Structure

The project workspace is organized as follows:

```
ai-portfolio-assistant/
├── backend/                  # ADK 2.0 Agent & FastAPI Backend
│   ├── app/
│   │   ├── __init__.py       # Imports root agent / app
│   │   ├── agent.py          # Portfolio agent definition (gemini-3.5-flash)
│   │   ├── tools.py          # Tools to retrieve knowledge base markdown files
│   │   └── fast_api_app.py   # FastAPI server configuration
│   ├── pyproject.toml        # Backend dependencies & virtual env configuration
│   └── README.md
├── frontend/                 # Modern SPA Chat Interface (HTML/CSS/JS)
│   ├── index.html            # Main HTML layout with marked.js & FontAwesome
│   ├── style.css             # Glassmorphic, light/dark mode CSS stylesheet
│   └── app.js                # State management, API calls, and rendering logic
├── database/                 # Persistent Storage
│   └── portfolio.db          # SQLite session database (created on backend startup)
├── knowledge/                # Raw Portfolio Knowledge Base
│   ├── aboutme.md            # Career summary
│   └── projects/             # Specific project files (lamabot, babyyoda, etc.)
├── docs/                     # Documentation
│   └── architecture.md       # (This file)
├── resume.md                 # Full Professional Resume
└── skills.md                 # Technical Skills Matrix
```

---

## Technical Architecture

The architecture consists of three main components:

1. **Frontend (Presentation Layer)**
   - Single-page application built with vanilla HTML, CSS, and JS.
   - Implements a modern glassmorphic look-and-feel with automatic dark/light theme switching.
   - Communicates with the FastAPI backend via `/run` for agent interaction and `/apps/app/users/default_user/sessions` for chat session history list, session creation, and deletion.
   - Utilizes `marked.js` CDN to render Markdown content from the agent dynamically.

2. **Backend (Agent & API Layer)**
   - Built on top of **FastAPI** using ADK 2.0.
   - Defines a `portfolio_agent` using **`gemini-3.5-flash`** as the core model.
   - Integrates custom python tools (`get_resume`, `get_skills`, `get_aboutme`, `get_projects_list`, `get_project_details`) to pull factual context from the raw markdown files inside `knowledge/`, `resume.md`, and `skills.md`. This eliminates hallucination risks and grounds all responses in real data.
   - Uses `allow_origins = ["*"]` by default for local development.

3. **Database (Persistence Layer)**
   - Utilizes ADK's native `DatabaseSessionService` via **SQLAlchemy** to connect to `sqlite:///database/portfolio.db`.
   - Stores session history and conversation logs persistently so that chats can be resumed across browser refreshes or backend restarts.

---

## Instructions to Run Local Prototype

Follow these steps to run the portfolio assistant locally:

### Step 1: Start the Backend Server

1. Navigate to the `backend/` directory:
   ```bash
   cd backend
   ```
2. Run the FastAPI development server:
   ```bash
   uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8000 --reload
   ```

The backend server will start running at `http://localhost:8000`. You can access the automatic documentation at `http://localhost:8000/docs`.

### Step 2: Access the Frontend Chat UI

Since the frontend is a static SPA, you can open it directly:

1. Locate `frontend/index.html` in your file explorer.
2. Double-click the file to open it in any web browser.

Alternatively, if you prefer running it via a local HTTP server:
```bash
# E.g., using Python's built-in HTTP server:
cd frontend
python3 -m http.server 8080
# Then visit http://localhost:8080 in your browser
```

---

## Sample Invocations to Test

Here are some prompts you can try to verify the system:
- *"What projects did Kate work on at LinkedIn?"* (Tests project tool mapping and detailed retrieval)
- *"Tell me about her experience with RAG and LLM agents."* (Tests resume mapping and NLP details)
- *"What are Kate's core technical skills and programming languages?"* (Tests skills matrix mapping)
- *"Can you summarize her education?"* (Tests resume mapping for academic background)
