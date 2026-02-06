# CLAUDE.md

## Project Overview

**myAccount-QA-agent** — An AI-powered QA testing platform that uses Gemini API and Chrome DevTools Protocol to autonomously test website login flows, capture account information, and extract offers.

The platform consists of 3 microservices deployed on GKE:
- **UI** — Web frontend for uploading test plans and viewing results
- **Distributor** — Parses test plans (Excel) and dispatches tasks to workers
- **Worker** — Runs AI-powered browser agent with pluggable skills

## Repository Structure

```
myAccount-QA-agent/
├── ui/                        # Frontend service (port 3000)
│   ├── app.py                 # FastAPI app — serves UI pages
│   ├── Dockerfile
│   └── requirements.txt
│
├── distributor/               # Backend orchestrator service (port 8080)
│   ├── app.py                 # FastAPI app — test run management
│   ├── Dockerfile
│   └── requirements.txt
│
├── worker/                    # Browser agent service (port 8090)
│   ├── app.py                 # FastAPI wrapper — routes tasks to skills
│   ├── agent.py               # Generic skill runner (skill-agnostic)
│   ├── browser.py             # Chrome DevTools Protocol browser session
│   ├── config.py              # Environment config loader (stdlib only)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── skills/                # Plugin directory — drop a file to add a skill
│       ├── __init__.py
│       ├── base.py            # BaseSkill ABC — the standard contract
│       ├── registry.py        # Auto-discovers skills on startup
│       └── login_checker.py   # First skill: login test + account info
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

### Distributor Service (port 8080)
- `POST /api/test-runs` — Upload Excel test plan, parse rows, dispatch to workers
- `GET /api/test-runs/{run_id}` — Poll status and aggregated results
- `GET /api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}` — Download screenshot
- Calls Worker API at `WORKER_URL` env var
- Tech: FastAPI + openpyxl + httpx

### Worker Service (port 8090) — Skill Plugin Architecture
- `POST /api/execute` — Run a QA task using a named skill
- `GET /api/skills` — List all registered skills (for distributor routing)
- `GET /health` — Health check (Chromium + API key + skills count)
- `GET /api/screenshots/{task_id}/{filename}` — Serve screenshot files
- Zero external deps for core agent logic (stdlib only)
- Tech: FastAPI + Chromium (installed in Docker image)

## Worker Skill Plugin System

The worker uses a **plugin architecture**. Each QA capability is a self-contained "skill" that the generic agent runner can execute. Skills are auto-discovered — no manual registration needed.

### Current Skills

| Skill Name | File | Description |
|---|---|---|
| `login_checker` | `worker/skills/login_checker.py` | Tests login flow, captures account info and offers |

### How Skills Work

1. Distributor sends `POST /api/execute` with a `skill` field
2. `app.py` looks up the skill in the registry
3. `agent.py` (generic runner) wires up the skill's tools + system instruction
4. Gemini runs the function-calling loop using the skill's configuration
5. Skill's `parse_done()` extracts structured results from the AI's `done()` call
6. Results returned in standardised `ExecuteResponse`

### How to Add a New Skill

Create a single file in `worker/skills/`. That's it — the registry auto-discovers it.

```python
# worker/skills/my_new_skill.py
from skills.base import BaseSkill

class MyNewSkill(BaseSkill):
    name = "my_new_skill"                        # unique ID used in API
    description = "What this skill does."        # shown in GET /api/skills

    system_instruction = "..."                   # Gemini system prompt

    @property
    def done_tool_declaration(self) -> dict:      # what done() returns
        return { "name": "done", "parameters": { ... } }

    def build_user_message(self, request: dict) -> str:
        return f"Test {request['target_url']} ..."

    def parse_done(self, args: dict) -> dict:     # must return {success, summary, ...}
        return {"success": args["result"] == "pass", "summary": args["reason"]}

    # Optional: override for custom metrics
    def on_tool_call(self, tool_name, tool_args, tool_result): ...
```

### BaseSkill Contract (`worker/skills/base.py`)

| Member | Type | Required | Description |
|---|---|---|---|
| `name` | property | Yes | Unique skill identifier |
| `description` | property | Yes | Human-readable description |
| `system_instruction` | property | Yes | Gemini system prompt |
| `done_tool_declaration` | property | No | Custom `done()` tool params (default: pass/fail) |
| `extra_tool_declarations` | property | No | Additional tools beyond browser + done |
| `max_turns` | property | No | Agent loop limit (default: 25) |
| `build_user_message(request)` | method | Yes | Build initial prompt from request |
| `parse_done(args)` | method | Yes | Extract structured result from done() |
| `on_tool_call(name, args, result)` | method | No | Hook for timing/metrics |

All skills automatically get the 9 standard browser tools (navigate, click, fill, get_page_text, get_page_html, screenshot, get_current_url, press_key, wait).

### Shared API Contract

**Distributor → Worker request:**
```json
{
  "task_id": "uuid",
  "skill": "login_checker",
  "target_url": "https://example.com/login",
  "credentials": {"username": "...", "password": "..."},
  "instructions": "optional extra steps"
}
```

**Worker → Distributor response:**
```json
{
  "task_id": "uuid",
  "skill": "login_checker",
  "success": true,
  "summary": "Login succeeded...",
  "data": {
    "account_info": "...",
    "offers": "...",
    "login_duration": 3.5
  },
  "screenshots": ["account_overview.png", "offers_page.png"],
  "logs": ["[Turn 1] navigate(...)", "..."],
  "duration": 15.2
}
```

Note: `data` is a free-form dict — each skill returns its own fields there. Standard fields (`success`, `summary`, `screenshots`, `logs`, `duration`) are always present.

## Implementation Tasks Per Service

### UI Agent — `ui/` folder only

Implement a single-page web app with 3 sections:

1. **Upload Section** — Form to upload an Excel (.xlsx) test plan file. On submit, POST the file to Distributor at `DISTRIBUTOR_URL/api/test-runs` (multipart form upload). Show a spinner while uploading.

2. **Progress Section** — After upload, poll `GET DISTRIBUTOR_URL/api/test-runs/{run_id}` every 3 seconds. Show a progress bar or task-level status table (task_id, target_url, status). Stop polling when all tasks are `completed` or `failed`.

3. **Results Section** — When a run finishes, display a results table with columns: Target URL, Status (pass/fail), Summary, Account Info, Offers, Duration, Screenshots (clickable links). Screenshot URLs: `DISTRIBUTOR_URL/api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}`.

Tech: FastAPI + Jinja2 templates + httpx. The UI calls the Distributor API — it does NOT call the Worker directly.

### Distributor Agent — `distributor/` folder only

Implement the orchestration backend:

1. **`POST /api/test-runs`** — Accept Excel file upload. Parse rows with openpyxl. Expected columns: `target_url`, `username`, `password`, `instructions` (optional). Create a `run_id` (uuid4). For each row, create a task and dispatch it to the Worker at `WORKER_URL/api/execute` asynchronously. Store run and task state in memory (dict). The distributor should query `GET WORKER_URL/api/skills` to know what skills are available and include the `skill` field in dispatch requests.

2. **`GET /api/test-runs/{run_id}`** — Return run status and all task results.

3. **`GET /api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}`** — Proxy screenshot files from Worker.

4. **`POST /api/test-runs/{run_id}/tasks/{task_id}/result`** — Callback endpoint for workers to post results back (alternative to synchronous dispatch).

### Worker Agent — `worker/` folder only — DONE

All worker tasks are complete:

- [x] `_find_chrome()` in `browser.py` — Linux paths added for Docker
- [x] `app.py` — Routes tasks to skills via registry, error handling, async-safe
- [x] Screenshot handling — Per-task dirs at `/tmp/screenshots/{task_id}/`
- [x] Health check — Verifies Chromium + API key + skills count
- [x] Skill plugin architecture — `skills/base.py`, `skills/registry.py`
- [x] Login checker skill — `skills/login_checker.py` (4-phase: login, account info, offers, report)
- [x] `GET /api/skills` endpoint — Distributor can discover available skills
- [x] Generic skill runner — `agent.py` is skill-agnostic, works with any BaseSkill

### Excel Test Plan Format

The uploaded `.xlsx` file has these columns (row 1 = headers):

| Column | Required | Description |
|---|---|---|
| `target_url` | Yes | Login page URL to test |
| `username` | Yes | Login username/email |
| `password` | Yes | Login password |
| `instructions` | No | Extra instructions for the agent |

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
| `GEMINI_API_KEY` | Google Gemini API key |
| `TARGET_URL` | Login page URL to test |
| `LOGIN_USERNAME` | Username/email for login |
| `LOGIN_PASSWORD` | Password for login |
| `HEADLESS` | Run browser headless (default: `true`) |
| `DISTRIBUTOR_URL` | (UI only) Distributor service URL |
| `WORKER_URL` | (Distributor only) Worker service URL |

## Key Conventions

- Python 3.10+, zero external deps for core agent
- Gemini API (free tier) with function calling (`mode: "ANY"` forces tool use)
- Chrome DevTools Protocol for browser automation (no Playwright/Selenium)
- Config via `.env` file (never commit secrets)
- Monorepo with per-service Dockerfiles
- GKE deployment with 3 Deployments + Services
- Worker stores Gemini API key in K8s Secret (`qa-agent-secrets`)
- Worker skills are auto-discovered — drop a file in `worker/skills/` to add one
