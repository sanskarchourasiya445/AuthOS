"""UI routes for the AuthOS Reviewer Interface."""
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

ui_router = APIRouter(tags=["reviewer_ui"])

_UI_HTML_PATH = Path(__file__).parent / "index.html"


@ui_router.get("/", response_class=HTMLResponse, summary="AuthOS Reviewer Desk")
@ui_router.get("/reviewer", response_class=HTMLResponse, summary="AuthOS Reviewer Desk")
def get_reviewer_desk() -> HTMLResponse:
    """Serve the single-page reviewer desk application."""
    if _UI_HTML_PATH.exists():
        html_content = _UI_HTML_PATH.read_text(encoding="utf-8")
    else:
        html_content = "<h1>AuthOS Reviewer Desk</h1><p>UI template not found.</p>"
    return HTMLResponse(content=html_content)
