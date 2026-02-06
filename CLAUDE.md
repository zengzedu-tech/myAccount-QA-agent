# CLAUDE.md

## Project Overview

**myAccount-QA-agent** — An AI-powered QA testing platform that uses Gemini API and Chrome DevTools Protocol to autonomously test website login flows, capture account information, and extract offers.

The platform consists of 3 microservices deployed on GKE:
- **UI** — Web frontend for uploading test plans and viewing results
- **Distributor** — Parses test plans (Excel) and dispatches tasks to workers
- **Worker** — Runs the AI-powered browser agent against target sites

## Implementation Status

| Service | Status | Notes |
|---|---|---|
| **UI** | ✅ Done | Dashboard with upload, execution tracking, and results display |
| **Distributor** | ⬜ Not started | `distributor/app.py` is scaffolded (stub only) |
| **Worker** | ⬜ Not started | `worker/app.py` is scaffolded; `agent.py` and `browser.py` exist but need integration |

## Repository Structure

```
myAccount-QA-agent/
├── ui/                        # Frontend service (port 3000) ✅ IMPLEMENTED
│   ├── app.py                 # FastAPI app — proxy endpoints + template serving
│   ├── templates/
│   │   └── index.html         # Jinja2 dashboard (Tailwind + Material Icons)
│   ├── stitchUI               # Original Stitch design reference (static HTML)
│   ├── Dockerfile
│   └── requirements.txt
│
├── distributor/               # Backend orchestrator service (port 8080)
│   ├── app.py                 # FastAPI app — test run management
│   ├── Dockerfile
│   └── requirements.txt
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

### UI Service (port 3000) — ✅ IMPLEMENTED
- Single-page web app for uploading Excel test plans and viewing results
- Calls Distributor API at `DISTRIBUTOR_URL` env var
- Tech: FastAPI + Jinja2 templates + httpx
- **`ui/app.py`** endpoints:
  - `GET /` — Dashboard page (Jinja2 template)
  - `POST /api/upload` — Proxies file + instructions to `DISTRIBUTOR_URL/api/test-runs`
  - `GET /api/runs/{run_id}` — Proxies run status from Distributor
  - `GET /api/runs/{run_id}/tasks/{task_id}/screenshots/{filename}` — Proxies screenshots
  - `GET /api/sample-template` — Downloads sample CSV test plan
  - `GET /health` — Health check
- **`ui/templates/index.html`** — Dashboard with 3 sections:
  1. Upload: drag-and-drop file picker, instructions textarea, run button
  2. Execution: progress bar, task status table, terminal-style log viewer
  3. Results: stats grid (total/passed/failed/duration), expandable cards per task with summary, account info, offers, screenshots, step logs
- Design: Tailwind CSS, Inter font, Material Symbols, dark mode, mobile bottom nav

### Distributor Service (port 8080)
- `POST /api/test-runs` — Upload Excel test plan, parse rows, create tasks, dispatch to workers
- `GET /api/test-runs/{run_id}` — Poll status and aggregated results
- `GET /api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}` — Download screenshot
- Calls Worker API at `WORKER_URL` env var
- Tech: FastAPI + openpyxl

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

### UI Agent — `ui/` folder only — ✅ DONE

Fully implemented. Key files:
- **`ui/app.py`** — FastAPI backend with proxy endpoints to Distributor API (upload, poll, screenshots, sample template)
- **`ui/templates/index.html`** — Full dashboard matching `ui/stitchUI` design reference

What was built:
1. **Upload Section** — Drag-and-drop file picker (.xlsx/.csv), instructions textarea, "Run Tests" button (disabled until file selected), sample template download link
2. **Progress Section** — Polls `GET /api/runs/{run_id}` every 3s. Shows progress bar, task status table (URL + badge), terminal log viewer with color-coded entries. Stops polling when status is `completed` or `failed`
3. **Results Section** — Stats grid (total/passed/failed/duration), expandable cards per task showing: agent summary, account info, offers, screenshot thumbnails (clickable), agent step logs in terminal view
4. **Extras** — Dark mode toggle, mobile bottom nav, "New Run" reset button

The UI proxies all API calls through its own backend (never calls Worker directly). The frontend JS expects the Distributor API response shape documented in the Shared API Contract section above.

### Distributor Agent — `distributor/` folder only

Implement the orchestration backend:

1. **`POST /api/test-runs`** — Accept Excel file upload. Parse rows with openpyxl. Expected columns: `target_url`, `username`, `password`, `instructions` (optional). Create a `run_id` (uuid4). For each row, create a task and dispatch it to the Worker at `WORKER_URL/api/execute` asynchronously (use `httpx.AsyncClient` or background threads). Store run and task state in memory (dict).

2. **`GET /api/test-runs/{run_id}`** — Return run status and all task results. Response shape:
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

3. **`GET /api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}`** — Proxy screenshot files returned by the Worker. Store screenshots in a local temp directory.

4. **`POST /api/test-runs/{run_id}/tasks/{task_id}/result`** — Callback endpoint for workers to post results back (alternative to synchronous dispatch).

Tech: FastAPI + openpyxl + httpx. The Distributor calls the Worker API — it does NOT run browser automation itself.

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

The uploaded `.xlsx` file has these columns (row 1 = headers):

| Column | Required | Description |
|---|---|---|
| `target_url` | Yes | Login page URL to test |
| `username` | Yes | Login username/email |
| `password` | Yes | Login password |
| `instructions` | No | Extra instructions for the agent |

Example:
```
target_url                                          | username        | password  | instructions
https://myaccount-s.westlakefinancial.com/.../login | user@test.com   | Pass123   |
https://another-site.com/login                      | admin@test.com  | Secret1   | Check rewards page too
```

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
| `GEMINI_API_KEY` | Google Gemini API key ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)) |
| `TARGET_URL` | Login page URL to test |
| `LOGIN_USERNAME` | Username/email for login |
| `LOGIN_PASSWORD` | Password for login |
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
- Worker stores Gemini API key in K8s Secret (`qa-agent-secrets`)
