# Kate's AI Portfolio Assistant 🤖💼

A local prototype for a smart, conversational portfolio assistant built with **ADK 2.0 (Agent Development Kit)** and a **FastAPI** backend. This assistant allows prospective employers and collaborators to chat with an AI agent to learn about Kate's (Ekaterina Tcareva) job skills, professional experience, education, and specific AI/NLP projects.

---

## 🏗️ Architecture & Features

This project utilizes a modern double-column single-page application structure:
* **LLM Grounding (No Hallucinations)**: The agent uses **`gemini-3.5-flash`** and is connected to custom Python tools that dynamically read raw Markdown knowledge files (resume, skills, projects) on disk.
* **Persistent Session History**: Chat history is persistently saved to a local SQLite database (`database/portfolio.db`) using ADK's native `DatabaseSessionService` via SQLAlchemy.
* **Sleek Glassmorphic Frontend**: A responsive, animated, single-page chat UI featuring:
  - Persistent session management (create, switch, and delete past conversations).
  - Dynamic tool badges showing exactly when and what files the AI is reading.
  - Interactive suggested question cards to get started quickly.
  - Smooth light/dark theme toggle.

---

## 📁 Workspace Structure

```
ai-portfolio-assistant/
├── backend/                  # ADK 2.0 Agent & FastAPI Backend
│   ├── app/
│   │   ├── agent.py          # Portfolio agent definition
│   │   ├── tools.py          # Local markdown file readers (tools)
│   │   └── fast_api_app.py   # FastAPI server
│   ├── pyproject.toml        # Backend dependencies & virtual env settings
│   └── README.md             # Backend development commands
├── frontend/                 # Static SPA Web Interface
│   ├── index.html            # Main UI layout
│   ├── style.css             # Glassmorphic, light/dark mode stylesheet
│   └── app.js                # Javascript API connection logic
├── database/                 # SQLite storage location
│   └── portfolio.db          # Created automatically on server startup
├── knowledge/                # Raw Portfolio Markdown Files
│   ├── resume.md             # Kate's full professional resume
│   ├── skills.md             # Technical skills matrix
│   ├── aboutme.md            # Career overview summary
│   └── projects/             # Specific project files (lamabot, babyyoda, etc.)
├── docs/                     # Documentation folder
│   └── architecture.md       # Detailed technical design document
└── README.md                 # Workspace Root documentation (this file)
```

---

## 🚀 Quick Start Guide

Follow these steps to run the portfolio assistant locally:

### Step 1: Start the Backend API Server
1. Navigate to the `backend/` directory:
   ```bash
   cd backend
   ```
2. Start the FastAPI development server with auto-reloading:
   ```bash
   uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8000 --reload
   ```

*The API server will start running at `http://localhost:8000`. You can access the interactive API docs at `http://localhost:8000/docs`.*

### Step 2: Open the Frontend Chat Interface
Since the frontend is a static web app, you can open it directly in your browser:
* Double-click [frontend/index.html](file:///Users/etcareva/Desktop/google_agents/ai-portfolio-assistant/frontend/index.html) in your Finder to open it.

*Alternatively, run a simple local web server to avoid browser CORS restrictions:*
```bash
python3 -m http.server 8080 --directory frontend/
```
Then visit **`http://localhost:8080`** in your browser.

---

## 💬 Suggested Questions to Try

When chatting with the assistant, you can ask questions like:
- *"What projects did Kate work on at LinkedIn?"* (Triggers project indexing and details retrieval)
- *"Tell me about her experience with RAG and LLM agents."* (Loads her resume context)
- *"What are Kate's core technical skills and programming languages?"* (Reads the skills matrix)
- *"Summarize her work on Lamabot."* (Loads specific project documents)
- *"Where did she complete her Georgia Tech Master's degree?"* (Reads her academic history)
