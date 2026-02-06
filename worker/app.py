"""Worker Service — receives task requests from the distributor and runs skills."""

import os
import time
import traceback

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from skills.registry import get_skill, list_skills

app = FastAPI(title="QA Agent Worker Service")

SCREENSHOT_BASE_DIR = "/tmp/screenshots"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    """Task payload sent by the distributor."""
    task_id: str
    skill: str  # skill name, e.g. "login_checker"
    target_url: str
    credentials: dict = {}  # {"username": "...", "password": "..."}
    instructions: str = ""


class ExecuteResponse(BaseModel):
    """Standardised response returned to the distributor."""
    task_id: str
    skill: str
    success: bool
    summary: str
    data: dict = {}  # skill-specific structured output
    screenshots: list[str] = []
    logs: list[str] = []
    duration: float | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Health check — verifies Chromium is installed and GEMINI_API_KEY is set."""
    checks = {}

    api_key = os.getenv("GEMINI_API_KEY", "")
    checks["gemini_api_key"] = "configured" if api_key else "missing"

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

    available = list_skills()
    checks["skills_loaded"] = len(available)

    healthy = bool(api_key) and chrome_found is not None
    return {
        "status": "ok" if healthy else "unhealthy",
        "checks": checks,
    }


@app.get("/api/skills")
def skills_list():
    """Return metadata for all registered skills (used by distributor for routing)."""
    return {"skills": list_skills()}


@app.post("/api/execute", response_model=ExecuteResponse)
def execute_task(req: ExecuteRequest):
    """Execute a QA task using the requested skill.

    The distributor sends a task with a ``skill`` field. The worker
    looks up the matching skill, spins up a fresh browser session,
    runs the Gemini agent loop, and returns a standardised response.
    """
    from agent import run_skill

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return ExecuteResponse(
            task_id=req.task_id,
            skill=req.skill,
            success=False,
            summary="GEMINI_API_KEY not configured",
        )

    # Resolve the skill
    try:
        skill = get_skill(req.skill)
    except KeyError as e:
        return ExecuteResponse(
            task_id=req.task_id,
            skill=req.skill,
            success=False,
            summary=str(e),
        )

    # Per-task screenshot directory
    screenshot_dir = os.path.join(SCREENSHOT_BASE_DIR, req.task_id)
    os.makedirs(screenshot_dir, exist_ok=True)

    # Build a request dict that skills can read
    request = {
        "task_id": req.task_id,
        "target_url": req.target_url,
        "credentials": req.credentials,
        "instructions": req.instructions,
    }

    start_time = time.time()
    try:
        result = run_skill(
            skill=skill,
            request=request,
            api_key=api_key,
            headless=True,
            screenshot_dir=screenshot_dir,
        )
    except Exception as e:
        elapsed = time.time() - start_time
        return ExecuteResponse(
            task_id=req.task_id,
            skill=req.skill,
            success=False,
            summary=f"Agent error: {e}",
            logs=[traceback.format_exc()],
            duration=round(elapsed, 2),
        )

    elapsed = time.time() - start_time

    # Collect screenshots
    screenshots = []
    if os.path.isdir(screenshot_dir):
        screenshots = sorted(os.listdir(screenshot_dir))

    # Separate standard fields from skill-specific data
    success = result.pop("success", False)
    summary = result.pop("summary", "")
    steps = result.pop("steps", [])

    return ExecuteResponse(
        task_id=req.task_id,
        skill=req.skill,
        success=success,
        summary=summary,
        data=result,  # everything else the skill returned (account_info, offers, etc.)
        screenshots=screenshots,
        logs=steps,
        duration=round(elapsed, 2),
    )


@app.get("/api/screenshots/{task_id}/{filename}")
def get_screenshot(task_id: str, filename: str):
    """Serve a screenshot file for a given task."""
    safe_task_id = os.path.basename(task_id)
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(SCREENSHOT_BASE_DIR, safe_task_id, safe_filename)

    if not os.path.isfile(filepath):
        return JSONResponse({"error": "Screenshot not found"}, status_code=404)

    return FileResponse(filepath, media_type="image/png")
