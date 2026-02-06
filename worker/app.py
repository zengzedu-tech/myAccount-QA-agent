"""Worker Service — wraps the QA agent as a FastAPI HTTP endpoint."""

import os
import shutil
import time
import traceback

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="QA Agent Worker Service")

SCREENSHOT_BASE_DIR = "/tmp/screenshots"


class ExecuteRequest(BaseModel):
    task_id: str
    type: str  # e.g. "login_test"
    target_url: str
    credentials: dict  # {"username": "...", "password": "..."}
    instructions: str = ""


class ExecuteResponse(BaseModel):
    task_id: str
    success: bool
    summary: str
    account_info: str = ""
    offers: str = ""
    screenshots: list[str] = []
    logs: list[str] = []
    duration: float | None = None


@app.get("/health")
def health():
    """Health check — verifies Chromium is installed and GEMINI_API_KEY is set."""
    checks = {}

    # Check GEMINI_API_KEY
    api_key = os.getenv("GEMINI_API_KEY", "")
    checks["gemini_api_key"] = "configured" if api_key else "missing"

    # Check Chromium binary
    chrome_paths = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]
    chrome_found = None
    for path in chrome_paths:
        if os.path.isfile(path):
            chrome_found = path
            break
    checks["chromium"] = chrome_found if chrome_found else "not found"

    healthy = bool(api_key) and chrome_found is not None
    return {
        "status": "ok" if healthy else "unhealthy",
        "checks": checks,
    }


@app.post("/api/execute", response_model=ExecuteResponse)
def execute_task(req: ExecuteRequest):
    """Execute a QA test task. Each request gets its own browser session."""
    from agent import run_login_test

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return ExecuteResponse(
            task_id=req.task_id,
            success=False,
            summary="GEMINI_API_KEY not configured",
        )

    # Per-task screenshot directory
    screenshot_dir = os.path.join(SCREENSHOT_BASE_DIR, req.task_id)
    os.makedirs(screenshot_dir, exist_ok=True)

    start_time = time.time()
    try:
        result = run_login_test(
            target_url=req.target_url,
            username=req.credentials.get("username", ""),
            password=req.credentials.get("password", ""),
            api_key=api_key,
            headless=True,
            screenshot_dir=screenshot_dir,
        )
    except Exception as e:
        elapsed = time.time() - start_time
        return ExecuteResponse(
            task_id=req.task_id,
            success=False,
            summary=f"Agent error: {e}",
            logs=[traceback.format_exc()],
            duration=round(elapsed, 2),
        )

    elapsed = time.time() - start_time

    # Collect screenshot filenames from the task directory
    screenshots = []
    if os.path.isdir(screenshot_dir):
        screenshots = sorted(os.listdir(screenshot_dir))

    return ExecuteResponse(
        task_id=req.task_id,
        success=result.get("success", False),
        summary=result.get("summary", ""),
        account_info=result.get("account_info", ""),
        offers=result.get("offers", ""),
        screenshots=screenshots,
        logs=result.get("steps", []),
        duration=result.get("login_duration") or round(elapsed, 2),
    )


@app.get("/api/screenshots/{task_id}/{filename}")
def get_screenshot(task_id: str, filename: str):
    """Serve a screenshot file for a given task."""
    # Prevent path traversal
    safe_task_id = os.path.basename(task_id)
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(SCREENSHOT_BASE_DIR, safe_task_id, safe_filename)

    if not os.path.isfile(filepath):
        return {"error": "Screenshot not found"}, 404

    return FileResponse(filepath, media_type="image/png")
