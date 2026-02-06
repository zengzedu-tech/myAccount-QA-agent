# CLAUDE.md

## Project Overview

**myAccount-QA-agent** — An AI-powered QA testing platform that uses Gemini API and Chrome DevTools Protocol to autonomously test website login flows, capture account information, and extract offers.

The platform consists of 3 microservices deployed on GKE:
- **UI** — Web frontend for uploading test plans and viewing results
- **Distributor** — AI-powered orchestrator: reads any Excel format, dispatches tasks to workers
- **Worker** — Runs the AI-powered browser agent against target sites

## Repository Structure

```
myAccount-QA-agent/
├── ui/                        # Frontend service (port 3000)
│   ├── app.py                 # FastAPI app — serves UI pages
│   ├── Dockerfile
│   └── requirements.txt
│
├── distributor/               # Backend orchestrator service (port 8080)
│   ├── app.py                 # FastAPI app — FULLY IMPLEMENTED
│   ├── Dockerfile
│   └── requirements.txt       # fastapi, uvicorn, openpyxl, httpx, python-multipart
│
├── worker/                    # Browser agent service (port 8090)
│   ├── app.py                 # FastAPI wrapper — /api/execute endpoint
│   ├── agent.py               # Gemini AI agent (direct REST API, no SDK)
│   ├── browser.py             # Chrome DevTools Protocol browser session
│   ├── config.py              # Environment config loader
│   ├── Dockerfile
│   └── requirements.txt
│
├── k8s/                       # Kubernetes manifests for GKE
│   ├── ui-deployment.yaml
│   ├── ui-service.yaml
│   ├── distributor-deployment.yaml
│   ├── distributor-service.yaml
│   ├── worker-deployment.yaml
│   └── worker-service.yaml
│
├── main.py                    # Standalone CLI runner (legacy)
├── agent.py                   # Original agent (kept for local use)
├── browser.py                 # Original browser module
├── config.py                  # Original config loader
├── .env.example               # Template for environment variables
├── .gitignore
├── CLAUDE.md                  # This file
└── README.md
```

## Service Architecture

### UI Service (port 3000)
- Single-page web app for uploading Excel test plans and viewing results
- Calls Distributor API at `DISTRIBUTOR_URL` env var
- Tech: FastAPI + Jinja2 templates + httpx

### Distributor Service (port 8080) — FULLY IMPLEMENTED
- AI-powered Excel parser using Gemini (handles any column naming/format)
- Accepts optional user description to guide test execution
- `POST /api/test-runs` — Upload Excel + optional description, AI-parse, dispatch to workers
- `GET /api/test-runs/{run_id}` — Poll status and aggregated results
- `GET /api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}` — Download screenshot
- `POST /api/test-runs/{run_id}/tasks/{task_id}/result` — Callback for workers to push results
- Calls Worker API at `WORKER_URL` env var
- Tech: FastAPI + openpyxl + httpx + Gemini AI

### Worker Service (port 8090)
- `POST /api/execute` — Run a single QA test task (login, capture info, screenshots)
- `GET /health` — Health check
- Uses Gemini API for AI reasoning + Chrome DevTools Protocol for browser automation
- Zero external deps for core agent logic (stdlib only)
- Tech: FastAPI + Chromium (installed in Docker image)

### Shared API Contract

**Distributor → Worker request:**
```json
{
  "task_id": "uuid",
  "type": "login_test",
  "target_url": "https://example.com/login",
  "credentials": {"username": "...", "password": "..."},
  "instructions": "optional extra steps"
}
```

**Worker → Distributor response:**
```json
{
  "task_id": "uuid",
  "success": true,
  "summary": "Login succeeded...",
  "account_info": "...",
  "offers": "...",
  "screenshots": ["screenshot_1.png"],
  "logs": ["step 1...", "step 2..."],
  "duration": 5.2
}
```

## Implementation Tasks Per Service

### UI Agent — `ui/` folder only

Implement a single-page web app with 3 sections:

1. **Upload Section** — Form to upload an Excel (.xlsx) test plan file. On submit, POST the file to Distributor at `DISTRIBUTOR_URL/api/test-runs` (multipart form upload). Show a spinner while uploading.

2. **Progress Section** — After upload, poll `GET DISTRIBUTOR_URL/api/test-runs/{run_id}` every 3 seconds. Show a progress bar or task-level status table (task_id, target_url, status). Stop polling when all tasks are `completed` or `failed`.

3. **Results Section** — When a run finishes, display a results table with columns: Target URL, Status (pass/fail), Summary, Account Info, Offers, Duration, Screenshots (clickable links). Screenshot URLs: `DISTRIBUTOR_URL/api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}`.

Tech: FastAPI + Jinja2 templates + httpx. The UI calls the Distributor API — it does NOT call the Worker directly.

### Distributor Agent — `distributor/` folder only — DONE

All endpoints implemented with AI-powered Excel parsing. See "Distributor Implementation Details" below.

## Distributor Implementation Details

### How Upload Works (POST /api/test-runs)

1. Accepts multipart form: `file` (Excel .xlsx) + `description` (optional text)
2. Converts Excel to text via `_excel_to_text()` (pipe-delimited, all rows)
3. Sends spreadsheet text + user description to **Gemini AI**
4. Gemini returns a JSON array where each item has: `target_url`, `username`, `password`, `instructions`
5. Creates a run (in-memory dict), dispatches all tasks concurrently to workers
6. Returns `run_id` immediately — tasks execute in background

### AI-Powered Excel Parsing

The distributor does NOT require fixed column names. The Gemini prompt:
- Receives the raw spreadsheet text (any format, any column names)
- Receives the optional USER DESCRIPTION
- Returns structured JSON with extracted fields per row

This means Excel files with columns like "Site URL", "Email", "pwd", "Login Page", "User Account", etc. all work automatically.

### Poll Response (GET /api/test-runs/{run_id})

```json
{
  "run_id": "uuid",
  "status": "running | completed",
  "total_tasks": 5,
  "completed_tasks": 3,
  "tasks": [
    {
      "task_id": "uuid",
      "target_url": "...",
      "status": "pending | running | completed | failed",
      "result": { ...worker response... }
    }
  ]
}
```

### Screenshot Flow

1. Worker saves screenshots to `screenshots/{task_id}/`
2. Worker serves them at `GET /api/screenshots/{task_id}/{filename}`
3. Distributor downloads them after task completes to local temp dir
4. UI/clients access via `GET /api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}`

### Worker Agent — `worker/` folder only

The core agent code (`agent.py`, `browser.py`, `config.py`) already exists and works. Tasks:

1. **Fix `_find_chrome()` in `browser.py`** — Add Linux paths for Docker container: `/usr/bin/chromium`, `/usr/bin/chromium-browser`, `/usr/bin/google-chrome`.

2. **Complete `app.py`** — The FastAPI wrapper is scaffolded. Make sure:
   - `POST /api/execute` correctly calls `run_login_test()` from `agent.py`
   - Screenshots are saved to a temp directory and filenames returned in the response
   - Errors are caught and returned as `success: false` with error details
   - The endpoint is async-safe (browser sessions are not shared across requests)

3. **Screenshot handling** — Save screenshots to `/tmp/screenshots/{task_id}/` and serve them or return base64 in the response.

4. **Health check** — `GET /health` should verify Chromium is installed and `GEMINI_API_KEY` is set.

Tech: FastAPI + existing CDP agent. Do NOT rewrite `agent.py` or `browser.py` — only fix/extend as needed.

### Excel Test Plan Format (shared knowledge for all agents)

The uploaded `.xlsx` file can use **any column naming convention**. The AI parser handles all formats. Examples:

```
target_url              | username        | password  | instructions
Site URL                | Email           | pwd       | Notes
Login Page              | User Account    | Secret    | Extra Steps
```

The AI identifies URLs, usernames, passwords, and instructions regardless of header names.

## Getting Started (Local Standalone)

```bash
# 1. Set up environment variables
cp .env.example .env
# Edit .env with your Gemini API key, target URL, and login credentials

# 2. Run the agent locally (no pip install needed)
python main.py
```

### Prerequisites
- **Python 3.10+**
- **Chrome or Edge** installed on the system

## Environment Variables

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Google Gemini API key — needed by both Distributor (AI parsing) and Worker (browser agent) |
| `GEMINI_MODEL` | (Distributor) Gemini model for parsing (default: `gemini-2.0-flash`) |
| `TARGET_URL` | (Legacy CLI) Login page URL to test |
| `LOGIN_USERNAME` | (Legacy CLI) Username/email for login |
| `LOGIN_PASSWORD` | (Legacy CLI) Password for login |
| `HEADLESS` | Run browser headless (default: `true`) |
| `DISTRIBUTOR_URL` | (UI only) Distributor service URL |
| `WORKER_URL` | (Distributor only) Worker service URL |

## How the Worker Agent Works

1. `agent.py` sends a prompt to Gemini REST API with browser tools via function calling
2. Gemini autonomously decides which tools to call (navigate, inspect HTML, fill fields, click, screenshot)
3. `browser.py` executes each tool via Chrome DevTools Protocol and returns results to Gemini
4. The agent runs through 4 phases:
   - **Phase 1 — Login**: Navigate, fill credentials, submit, verify URL changed
   - **Phase 2 — Account Info**: Read account overview, take screenshot
   - **Phase 3 — Offers**: Navigate to offers page, read offers, take screenshot
   - **Phase 4 — Report**: Call `done()` with all captured data

## Key Conventions

- Python 3.10+, zero external deps for core agent
- Gemini API (free tier) with function calling (`mode: "ANY"` forces tool use)
- Chrome DevTools Protocol for browser automation (no Playwright/Selenium)
- Config via `.env` file (never commit secrets)
- Monorepo with per-service Dockerfiles
- GKE deployment with 3 Deployments + Services
- Both Distributor and Worker use Gemini API key from K8s Secret (`qa-agent-secrets`)
