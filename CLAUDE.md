# CLAUDE.md

## Project Overview

**myAccount-QA-agent** — An AI-powered QA testing platform that uses Gemini API and Chrome DevTools Protocol to autonomously test website login flows, capture account information, and extract offers.

The platform consists of 3 microservices deployed on GKE:
- **UI** — Web frontend for uploading test plans and viewing results
- **Distributor** — AI-powered orchestrator: reads any Excel format, picks worker skills, dispatches tasks
- **Worker** — Runs AI-powered browser agent with pluggable skill system

## Implementation Status

| Service | Status | Notes |
|---|---|---|
| **UI** | ✅ Done | Dashboard with upload, execution tracking, and results display |
| **Distributor** | ✅ Done | AI-powered Excel parser, skill discovery, concurrent task dispatch |
| **Worker** | ✅ Done | Skill plugin system with `login_checker`, generic agent runner |

## Repository Structure

```
myAccount-QA-agent/
├── ui/                        # Frontend service (port 3000)
│   ├── app.py                 # FastAPI app — serves UI pages (TODO)
│   ├── stitchUI               # Stitch design mockup (reference HTML)
│   ├── Dockerfile
│   └── requirements.txt
│
├── distributor/               # Backend orchestrator service (port 8080)
│   ├── app.py                 # FastAPI app — FULLY IMPLEMENTED
│   ├── Dockerfile
│   └── requirements.txt       # fastapi, uvicorn, openpyxl, httpx, python-multipart
│
├── worker/                    # Browser agent service (port 8090)
│   ├── app.py                 # FastAPI wrapper — routes by skill name
│   ├── agent.py               # Generic skill runner (skill-agnostic)
│   ├── browser.py             # Chrome DevTools Protocol browser session
│   ├── config.py              # Environment config loader
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── base.py            # BaseSkill ABC — the standard contract
│   │   ├── registry.py        # Auto-discovers skills, no manual registration
│   │   └── login_checker.py   # First skill implementation
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

### UI Service (port 3000) — TODO
- Single-page web app for uploading Excel test plans and viewing results
- Stitch design mockup exists at `ui/stitchUI` (reference HTML)
- Calls Distributor API at `DISTRIBUTOR_URL` env var
- Tech: FastAPI + Jinja2 templates + httpx
- **Status**: Scaffold only — needs implementation by UI agent

### Distributor Service (port 8080) — FULLY IMPLEMENTED
- AI-powered Excel parser using Gemini (handles any column naming/format)
- Discovers worker skills dynamically via `GET /api/skills`
- Routes tasks to the appropriate worker skill based on AI analysis
- Accepts optional user description to guide test execution
- **Status**: Complete. See "Distributor Implementation Details" below.

### Worker Service (port 8090) — IMPLEMENTED
- Plugin-based skill system: drop a `.py` in `worker/skills/` and it auto-registers
- `POST /api/execute` — Run a task using the requested skill
- `GET /api/skills` — List all registered skills (used by distributor for routing)
- `GET /api/screenshots/{task_id}/{filename}` — Serve screenshot files
- `GET /health` — Health check (verifies Chromium + API key + loaded skills)
- **Status**: Complete with `login_checker` skill.

## Distributor Implementation Details

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/test-runs` | Upload Excel + optional description, AI-parse, dispatch to workers |
| `GET` | `/api/test-runs/{run_id}` | Poll run status and all task results |
| `GET` | `/api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}` | Serve screenshot files |
| `POST` | `/api/test-runs/{run_id}/tasks/{task_id}/result` | Callback for workers to push results |
| `GET` | `/health` | Health check |

### How Upload Works (POST /api/test-runs)

1. Accepts multipart form: `file` (Excel .xlsx) + `description` (optional text)
2. Converts Excel to text via `_excel_to_text()` (pipe-delimited, all rows)
3. Calls `GET WORKER_URL/api/skills` to discover available worker skills
4. Sends spreadsheet text + skills list + user description to **Gemini AI**
5. Gemini returns a JSON array where each item has: `skill`, `target_url`, `username`, `password`, `instructions`
6. Creates a run (in-memory dict), dispatches all tasks concurrently to workers
7. Returns `run_id` immediately — tasks execute in background

### AI-Powered Excel Parsing

The distributor does NOT require fixed column names. The Gemini prompt:
- Receives the raw spreadsheet text (any format, any column names)
- Receives the list of AVAILABLE WORKER SKILLS with descriptions
- Receives the optional USER DESCRIPTION
- Returns structured JSON with the best skill + extracted fields per row

This means Excel files with columns like "Site URL", "Email", "pwd", "Login Page", "User Account", etc. all work automatically.

### Shared API Contract (Current)

**Distributor → Worker request:**
```json
{
  "task_id": "uuid",
  "skill": "login_checker",
  "target_url": "https://example.com/login",
  "credentials": {"username": "...", "password": "..."},
  "instructions": "optional extra steps from AI + user description"
}
```

**Worker → Distributor response:**
```json
{
  "task_id": "uuid",
  "skill": "login_checker",
  "success": true,
  "summary": "Login succeeded...",
  "data": {"account_info": "...", "offers": "...", "login_duration": 5.2},
  "screenshots": ["account_overview.png", "offers_page.png"],
  "logs": ["step 1...", "step 2..."],
  "duration": 12.5
}
```

**Poll response (GET /api/test-runs/{run_id}):**
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
      "skill": "login_checker",
      "status": "pending | running | completed | failed",
      "result": { ...worker response... }
    }
  ]
}
```

### Screenshot Flow

1. Worker saves screenshots to `/tmp/screenshots/{task_id}/`
2. Worker serves them at `GET /api/screenshots/{task_id}/{filename}`
3. Distributor downloads them after task completes → saves to local temp dir
4. UI/clients access via `GET /api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}`

## Implementation Tasks Per Service

### UI Agent — `ui/` folder only — TODO

Implement a single-page web app with 3 sections (Stitch design at `ui/stitchUI`):

1. **Upload Section** — Form to upload an Excel (.xlsx) file + optional description textarea. On submit, POST multipart to Distributor at `DISTRIBUTOR_URL/api/test-runs` with fields `file` and `description`. Show a spinner while uploading.

2. **Progress Section** — After upload, poll `GET DISTRIBUTOR_URL/api/test-runs/{run_id}` every 3 seconds. Show a progress bar or task-level status table (task_id, skill, target_url, status). Stop polling when all tasks are `completed` or `failed`.

3. **Results Section** — When a run finishes, display a results table with columns: Target URL, Skill, Status (pass/fail), Summary, Data (account_info, offers, etc.), Duration, Screenshots (clickable links). Screenshot URLs: `DISTRIBUTOR_URL/api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}`.

Tech: FastAPI + Jinja2 templates + httpx. The UI calls the Distributor API — it does NOT call the Worker directly.

### Distributor Agent — `distributor/` folder only — DONE

All endpoints implemented. See "Distributor Implementation Details" above.

### Worker Agent — `worker/` folder only — DONE

Skill plugin system implemented. To add new skills, drop a file in `worker/skills/`:

```python
# worker/skills/payment_checker.py
from skills.base import BaseSkill

class PaymentCheckerSkill(BaseSkill):
    name = "payment_checker"
    description = "Verify payment processing flow."
    system_instruction = "You are a QA agent. Test the payment flow..."

    def build_user_message(self, request): ...
    def parse_done(self, args): ...
```

The registry auto-discovers it and the distributor will route tasks to it automatically.

### Excel Test Plan Format

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

1. Distributor sends a task with a `skill` field to `POST /api/execute`
2. Worker looks up the skill in the auto-discovery registry
3. Skill provides: system instruction, tool declarations, done-tool schema
4. `agent.py` runs the Gemini agent loop with the skill's configuration
5. `browser.py` executes each tool via Chrome DevTools Protocol
6. When AI calls `done()`, the skill's `parse_done()` extracts structured data
7. Worker returns standardised response with `success`, `summary`, `data`, `screenshots`, `logs`

## Key Conventions

- Python 3.10+, zero external deps for core agent
- Gemini API (free tier) with function calling (`mode: "ANY"` forces tool use)
- Chrome DevTools Protocol for browser automation (no Playwright/Selenium)
- Config via `.env` file (never commit secrets)
- Monorepo with per-service Dockerfiles
- GKE deployment with 3 Deployments + Services
- Both Distributor and Worker use Gemini API key from K8s Secret (`qa-agent-secrets`)
- Worker skills are auto-discovered — no manual registration needed
- Distributor dynamically adapts to available skills — no code changes needed when new skills are added
