"""UI Service — serves the web frontend for uploading test plans and viewing results."""

import os

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
import httpx

DISTRIBUTOR_URL = os.getenv("DISTRIBUTOR_URL", "http://localhost:8080")

app = FastAPI(title="QA Agent UI Service")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

_http = httpx.AsyncClient(timeout=60.0)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/upload")
async def upload_test_plan(
    file: UploadFile = File(...),
    instructions: str = Form(""),
):
    """Forward the uploaded test plan to the Distributor service."""
    content = await file.read()
    files = {"file": (file.filename, content, file.content_type)}
    data = {}
    if instructions:
        data["instructions"] = instructions
    resp = await _http.post(
        f"{DISTRIBUTOR_URL}/api/test-runs",
        files=files,
        data=data,
    )
    return Response(content=resp.content, status_code=resp.status_code,
                    media_type="application/json")


@app.get("/api/runs/{run_id}")
async def get_run_status(run_id: str):
    """Proxy run status from the Distributor."""
    resp = await _http.get(f"{DISTRIBUTOR_URL}/api/test-runs/{run_id}")
    return Response(content=resp.content, status_code=resp.status_code,
                    media_type="application/json")


@app.get("/api/runs/{run_id}/tasks/{task_id}/screenshots/{filename}")
async def get_screenshot(run_id: str, task_id: str, filename: str):
    """Proxy screenshot download from the Distributor."""
    resp = await _http.get(
        f"{DISTRIBUTOR_URL}/api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename}"
    )
    content_type = resp.headers.get("content-type", "image/png")
    return Response(content=resp.content, status_code=resp.status_code,
                    media_type=content_type)


@app.get("/api/sample-template")
async def sample_template():
    """Return a sample CSV template for the test plan."""
    csv_content = "target_url,username,password,instructions\nhttps://example.com/login,user@test.com,Password123,\n"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=test_plan_template.csv"},
    )
