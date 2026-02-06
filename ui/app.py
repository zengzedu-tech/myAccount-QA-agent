"""UI Service — serves the web frontend for uploading test plans and viewing results."""

# TODO: Implement by UI coding agent
# See task description for full page spec

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

app = FastAPI(title="QA Agent UI Service")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!DOCTYPE html>
<html>
<head><title>QA Agent</title></head>
<body>
<h1>QA Agent — Test Runner</h1>
<p>UI coming soon.</p>
</body>
</html>"""


# Pages to implement:
# GET  /                — Main page: upload test plan, trigger run, view results
# The UI should call the Distributor API at DISTRIBUTOR_URL (env var)
