"""Distributor Service — parses test plans and dispatches tasks to workers."""

import asyncio
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import openpyxl
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

app = FastAPI(title="QA Agent Distributor Service")

WORKER_URL = os.getenv("WORKER_URL", "http://localhost:8090")

# In-memory storage for test runs and tasks
test_runs: dict[str, dict] = {}

# Temp directory for screenshots received from workers
SCREENSHOT_DIR = Path(tempfile.gettempdir()) / "qa-agent-screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/health")
def health():
    return {"status": "ok", "worker_url": WORKER_URL}


# ---------------------------------------------------------------------------
# POST /api/test-runs — Upload Excel test plan, parse rows, dispatch tasks
# ---------------------------------------------------------------------------

@app.post("/api/test-runs")
async def create_test_run(file: UploadFile = File(...)):
    """Accept an Excel file upload, parse rows, create tasks, and dispatch to workers."""
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File must be an Excel (.xlsx) file")

    # Save uploaded file to a temp location for openpyxl to read
    content = await file.read()
    tmp_path = Path(tempfile.gettempdir()) / f"upload_{uuid.uuid4().hex}.xlsx"
    tmp_path.write_bytes(content)

    try:
        tasks = _parse_excel(tmp_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        tmp_path.unlink(missing_ok=True)

    if not tasks:
        raise HTTPException(status_code=400, detail="No valid rows found in the Excel file")

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
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_excel(path: Path) -> list[dict]:
    """Parse an Excel test plan file. Expected columns: target_url, username, password, instructions."""
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    if ws is None:
        raise ValueError("Excel file has no active sheet")

    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        raise ValueError("Excel file must have a header row and at least one data row")

    # Normalise headers to lowercase, stripped
    headers = [str(h).strip().lower() if h else "" for h in rows[0]]

    required = {"target_url", "username", "password"}
    if not required.issubset(set(headers)):
        missing = required - set(headers)
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    col_map = {name: idx for idx, name in enumerate(headers)}
    tasks = []

    for row_num, row in enumerate(rows[1:], start=2):
        target_url = _cell_str(row, col_map.get("target_url"))
        username = _cell_str(row, col_map.get("username"))
        password = _cell_str(row, col_map.get("password"))
        instructions = _cell_str(row, col_map.get("instructions"))

        if not target_url or not username or not password:
            continue  # skip incomplete rows

        tasks.append({
            "target_url": target_url,
            "username": username,
            "password": password,
            "instructions": instructions,
        })

    wb.close()
    return tasks


def _cell_str(row: tuple, idx: int | None) -> str:
    """Safely extract a string from a row tuple."""
    if idx is None or idx >= len(row) or row[idx] is None:
        return ""
    return str(row[idx]).strip()


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
        result = {
            "task_id": task_id,
            "success": False,
            "summary": f"Worker request failed: {e}",
            "screenshots": [],
            "logs": [],
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
    """Download screenshot files from the worker's screenshot directory."""
    dest_dir = SCREENSHOT_DIR / run_id / task_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    for filename in filenames:
        try:
            url = f"{WORKER_URL}/screenshots/{task_id}/{filename}"
            resp = await client.get(url)
            if resp.status_code == 200:
                (dest_dir / filename).write_bytes(resp.content)
        except Exception:
            pass  # screenshot download is best-effort
