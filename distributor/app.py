"""Distributor Service — parses test plans and dispatches tasks to workers."""

# TODO: Implement by Distributor coding agent
# See task description for full API spec

from fastapi import FastAPI

app = FastAPI(title="QA Agent Distributor Service")


@app.get("/health")
def health():
    return {"status": "ok"}


# POST /api/test-runs           — Upload test plan, dispatch tasks
# GET  /api/test-runs/{run_id}  — Poll status/results
# GET  /api/test-runs/{run_id}/tasks/{task_id}/screenshots/{filename} — Download screenshot
