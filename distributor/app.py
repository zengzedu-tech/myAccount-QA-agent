"""Distributor Service — parses test plans with AI and dispatches tasks to workers."""

import asyncio
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import openpyxl
from fastapi import FastAPI, Form, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

app = FastAPI(title="QA Agent Distributor Service")
logger = logging.getLogger("distributor")
logging.basicConfig(level=logging.INFO)

WORKER_URL = os.getenv("WORKER_URL", "http://localhost:8090")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# In-memory storage for test runs and tasks
test_runs: dict[str, dict] = {}

# Temp directory for screenshots received from workers
SCREENSHOT_DIR = Path(tempfile.gettempdir()) / "qa-agent-screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/health")
def health():
    return {"status": "ok", "worker_url": WORKER_URL}


# ---------------------------------------------------------------------------
# POST /api/test-runs — Upload test plan, AI-parse it, dispatch tasks
# ---------------------------------------------------------------------------

@app.post("/api/test-runs")
async def create_test_run(
    file: UploadFile = File(...),
    description: str = Form(""),
):
    """Accept an Excel file upload with optional description, use AI to analyze it, and dispatch tasks."""
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File must be an Excel (.xlsx) file")

    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured on distributor")

    # Save uploaded file to a temp location for openpyxl to read
    content = await file.read()
    tmp_path = Path(tempfile.gettempdir()) / f"upload_{uuid.uuid4().hex}.xlsx"
    tmp_path.write_bytes(content)

    try:
        raw_text = _excel_to_text(tmp_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        tmp_path.unlink(missing_ok=True)

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Excel file appears to be empty")

    # Use Gemini AI to analyze the spreadsheet and extract tasks
    user_description = description.strip()
    try:
        tasks = await _ai_parse_test_plan(raw_text, user_description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not tasks:
        raise HTTPException(
            status_code=400,
            detail="AI could not extract any valid test tasks from the file. "
                   "Each task needs at least a target_url, username, and password.",
        )

    run_id = str(uuid.uuid4())
    run = {
        "run_id": run_id,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_tasks": len(tasks),
        "completed_tasks": 0,
        "tasks": {},
    }

    for task in tasks:
        task_id = str(uuid.uuid4())
        run["tasks"][task_id] = {
            "task_id": task_id,
            "target_url": task["target_url"],
            "username": task["username"],
            "password": task["password"],
            "instructions": task.get("instructions", ""),
            "status": "pending",
            "result": None,
        }

    test_runs[run_id] = run

    # Dispatch all tasks to workers asynchronously
    asyncio.create_task(_dispatch_all_tasks(run_id))

    return {
        "run_id": run_id,
        "status": "running",
        "total_tasks": len(tasks),
    }


# ---------------------------------------------------------------------------
# GET /api/test-runs/{run_id} — Poll status and aggregated results
# ---------------------------------------------------------------------------

@app.get("/api/test-runs/{run_id}")
def get_test_run(run_id: str):
    """Return run status and all task results."""
    run = test_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found")

    tasks_list = []
    for task in run["tasks"].values():
        tasks_list.append({
            "task_id": task["task_id"],
            "target_url": task["target_url"],
            "status": task["status"],
            "result": task["result"],
        })

    return {
        "run_id": run["run_id"],
        "status": run["status"],
        "total_tasks": run["total_tasks"],
        "completed_tasks": run["completed_tasks"],
        "tasks": tasks_list,
    }


# ---------------------------------------------------------------------------
# GET /api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}
# ---------------------------------------------------------------------------

@app.get("/api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}")
def get_screenshot(run_id: str, task_id: str, filename: str):
    """Serve a screenshot file for a specific task."""
    run = test_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found")

    task = run["tasks"].get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    screenshot_path = SCREENSHOT_DIR / run_id / task_id / filename
    if not screenshot_path.is_file():
        raise HTTPException(status_code=404, detail="Screenshot not found")

    return FileResponse(screenshot_path, media_type="image/png")


# ---------------------------------------------------------------------------
# POST /api/test-runs/{run_id}/tasks/{task_id}/result — Worker callback
# ---------------------------------------------------------------------------

@app.post("/api/test-runs/{run_id}/tasks/{task_id}/result")
async def receive_task_result(run_id: str, task_id: str, result: dict):
    """Callback endpoint for workers to post results back."""
    run = test_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found")

    task = run["tasks"].get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    _apply_result(run, task_id, result)

    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# AI-powered Excel parsing via Gemini
# ---------------------------------------------------------------------------

PARSE_PROMPT = """\
You are a QA test plan parser. You will receive the raw text content of an Excel spreadsheet, and optionally a description from the user explaining what they want to test.

Your job is to analyze the spreadsheet — regardless of how columns are named, ordered, or formatted — and extract a list of QA test tasks.

For each row that represents a test case, extract:
- **target_url**: The website URL / login page to test
- **username**: The login username or email
- **password**: The login password
- **instructions**: Specific testing instructions for the worker agent. This is CRITICAL — combine any per-row notes from the spreadsheet with the user's overall description to produce clear, actionable instructions for each task. If the user provided a description, incorporate it into every task's instructions so the worker knows exactly what to do beyond the basic login test.

Rules:
- Column headers may use different names (e.g. "URL", "Site", "Login Page", "Email", "User", "Pass", "pwd", etc.) — use your judgement to map them
- Skip header rows, empty rows, and rows that are clearly not test cases
- If a column has URLs, that's likely the target_url
- If columns contain what look like email addresses or usernames, that's the username
- If a column has short strings that look like passwords, that's the password
- Any remaining notes/comments columns contribute to the per-row instructions
- If the user provided a description, prepend it to each task's instructions so the worker agent understands the overall testing goal
- If you cannot identify the required fields (target_url, username, password), return an empty array

Respond with ONLY a valid JSON array. No markdown, no explanation. Example:
[
  {{"target_url": "https://example.com/login", "username": "user@test.com", "password": "Pass123", "instructions": "After login, navigate to the rewards page and verify the points balance is displayed."}},
  {{"target_url": "https://other.com/login", "username": "admin@test.com", "password": "Secret1", "instructions": "After login, check the offers section."}}
]
"""


def _excel_to_text(path: Path) -> str:
    """Read all cells from an Excel file and convert to a text table."""
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    if ws is None:
        raise ValueError("Excel file has no active sheet")

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Excel file is empty")

    # Build a pipe-delimited text representation of the spreadsheet
    lines = []
    for i, row in enumerate(rows):
        cells = [str(c).strip() if c is not None else "" for c in row]
        # Skip completely empty rows
        if not any(cells):
            continue
        prefix = f"Row {i + 1}"
        lines.append(f"{prefix}: | {' | '.join(cells)} |")

    wb.close()
    return "\n".join(lines)


async def _ai_parse_test_plan(raw_text: str, user_description: str = "") -> list[dict]:
    """Send the spreadsheet text to Gemini and get structured task data back."""
    url = GEMINI_API_URL.format(model=GEMINI_MODEL) + f"?key={GEMINI_API_KEY}"

    # Build the full prompt with optional user description
    prompt_parts = [PARSE_PROMPT]
    if user_description:
        prompt_parts.append(f"USER DESCRIPTION:\n{user_description}\n")
    prompt_parts.append(f"SPREADSHEET CONTENT:\n{raw_text}")
    full_prompt = "\n".join(prompt_parts)

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": full_prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload)

    if resp.status_code != 200:
        logger.error("Gemini API error %d: %s", resp.status_code, resp.text)
        raise ValueError(f"AI analysis failed (HTTP {resp.status_code}). Check GEMINI_API_KEY.")

    body = resp.json()

    # Extract text from Gemini response
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        logger.error("Unexpected Gemini response: %s", json.dumps(body)[:500])
        raise ValueError("AI returned an unexpected response format")

    # Parse the JSON array
    text = text.strip()
    # Strip markdown fences if the model wraps output
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        tasks = json.loads(text)
    except json.JSONDecodeError:
        logger.error("AI returned invalid JSON: %s", text[:500])
        raise ValueError("AI returned invalid JSON. The file may not be a valid test plan.")

    if not isinstance(tasks, list):
        raise ValueError("AI returned non-list response. The file may not be a valid test plan.")

    # Validate each task has required fields
    valid_tasks = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        target_url = str(t.get("target_url", "")).strip()
        username = str(t.get("username", "")).strip()
        password = str(t.get("password", "")).strip()
        instructions = str(t.get("instructions", "")).strip()

        if target_url and username and password:
            valid_tasks.append({
                "target_url": target_url,
                "username": username,
                "password": password,
                "instructions": instructions,
            })

    return valid_tasks


# ---------------------------------------------------------------------------
# Task dispatch and result handling
# ---------------------------------------------------------------------------

async def _dispatch_all_tasks(run_id: str):
    """Dispatch all tasks in a run to the worker service concurrently."""
    run = test_runs.get(run_id)
    if not run:
        return

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        coros = []
        for task_id, task in run["tasks"].items():
            coros.append(_dispatch_single_task(client, run_id, task_id, task))
        await asyncio.gather(*coros, return_exceptions=True)

    # After all tasks finish, update run status
    _update_run_status(run_id)


async def _dispatch_single_task(
    client: httpx.AsyncClient,
    run_id: str,
    task_id: str,
    task: dict,
):
    """Send a single task to the worker and store the result."""
    run = test_runs.get(run_id)
    if not run:
        return

    # Mark task as running
    task["status"] = "running"

    payload = {
        "task_id": task_id,
        "type": "login_test",
        "target_url": task["target_url"],
        "credentials": {
            "username": task["username"],
            "password": task["password"],
        },
        "instructions": task.get("instructions", ""),
    }

    try:
        resp = await client.post(f"{WORKER_URL}/api/execute", json=payload)
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        logger.error("Worker request failed for task %s: %s", task_id, e)
        result = {
            "task_id": task_id,
            "success": False,
            "summary": f"Worker request failed: {e}",
            "account_info": "",
            "offers": "",
            "screenshots": [],
            "logs": [],
            "duration": None,
        }

    _apply_result(run, task_id, result)

    # Download screenshots from worker if any filenames are listed
    screenshots = result.get("screenshots", [])
    if screenshots:
        await _download_screenshots(client, run_id, task_id, screenshots)


def _apply_result(run: dict, task_id: str, result: dict):
    """Apply a worker result to the task and update counters."""
    task = run["tasks"].get(task_id)
    if not task:
        return

    task["result"] = result
    task["status"] = "completed" if result.get("success") else "failed"

    # Recount completed tasks
    run["completed_tasks"] = sum(
        1 for t in run["tasks"].values() if t["status"] in ("completed", "failed")
    )
    _update_run_status(run["run_id"])


def _update_run_status(run_id: str):
    """Set run status to 'completed' when all tasks are done."""
    run = test_runs.get(run_id)
    if not run:
        return
    all_done = all(
        t["status"] in ("completed", "failed") for t in run["tasks"].values()
    )
    if all_done:
        run["status"] = "completed"


async def _download_screenshots(
    client: httpx.AsyncClient,
    run_id: str,
    task_id: str,
    filenames: list[str],
):
    """Download screenshot files from the worker's screenshot endpoint."""
    dest_dir = SCREENSHOT_DIR / run_id / task_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    for filename in filenames:
        try:
            url = f"{WORKER_URL}/api/screenshots/{task_id}/{filename}"
            resp = await client.get(url)
            if resp.status_code == 200:
                (dest_dir / filename).write_bytes(resp.content)
        except Exception:
            pass  # screenshot download is best-effort
