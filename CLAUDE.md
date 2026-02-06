# CLAUDE.md

## Project Overview

**myAccount-QA-agent** — An AI-powered QA testing platform that uses Gemini API and Chrome DevTools Protocol to autonomously test website login flows, capture account information, and extract offers.

The platform consists of 3 microservices deployed on GKE:
- **UI** — Web frontend for uploading test plans and viewing results
- **Distributor** — Parses test plans (Excel) and dispatches tasks to workers
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

### UI Service (port 3000)
- Single-page web app for uploading Excel test plans and viewing results
- Calls Distributor API at `DISTRIBUTOR_URL` env var
- Tech: FastAPI + Jinja2 templates + httpx

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
