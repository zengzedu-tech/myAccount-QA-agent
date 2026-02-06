"""Worker Service — wraps the QA agent as a FastAPI HTTP endpoint."""

from fastapi import FastAPI
from pydantic import BaseModel
import os
import uuid

app = FastAPI(title="QA Agent Worker Service")


class ExecuteRequest(BaseModel):
    task_id: str
    type: str  # e.g. "login"
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
    return {"status": "ok"}


@app.post("/api/execute", response_model=ExecuteResponse)
def execute_task(req: ExecuteRequest):
    """Execute a QA test task."""
    from agent import run_login_test

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return ExecuteResponse(
            task_id=req.task_id,
            success=False,
            summary="GEMINI_API_KEY not configured",
        )

    # Set screenshot dir per task
    screenshot_dir = os.path.join("screenshots", req.task_id)
    os.makedirs(screenshot_dir, exist_ok=True)

    result = run_login_test(
        target_url=req.target_url,
        username=req.credentials.get("username", ""),
        password=req.credentials.get("password", ""),
        api_key=api_key,
        headless=True,
    )

    # Collect screenshot filenames
    screenshots = []
    if os.path.isdir(screenshot_dir):
        screenshots = os.listdir(screenshot_dir)

    return ExecuteResponse(
        task_id=req.task_id,
        success=result["success"],
        summary=result["summary"],
        account_info=result.get("account_info", ""),
        offers=result.get("offers", ""),
        screenshots=screenshots,
        logs=result.get("steps", []),
        duration=result.get("login_duration"),
    )
