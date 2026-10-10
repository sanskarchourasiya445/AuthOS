"""UI routes for the AuthOS Reviewer Interface."""
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

ui_router = APIRouter(tags=["reviewer_ui"])

_UI_HTML_PATH = Path(__file__).parent / "index.html"
_REACT_DIST_PATH = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@ui_router.get("/", response_class=HTMLResponse, summary="AuthOS Reviewer Desk")
@ui_router.get("/reviewer", response_class=HTMLResponse, summary="AuthOS Reviewer Desk")
def get_reviewer_desk() -> HTMLResponse:
    """Serve the single-page reviewer desk application."""
    if _UI_HTML_PATH.exists():
        html_content = _UI_HTML_PATH.read_text(encoding="utf-8")
    else:
        html_content = "<h1>AuthOS Reviewer Desk</h1><p>UI template not found.</p>"
    return HTMLResponse(content=html_content)


@ui_router.get("/app", response_class=HTMLResponse, summary="AuthOS React Reviewer Workstation")
@ui_router.get("/app/{full_path:path}", response_class=HTMLResponse, summary="AuthOS React Reviewer Workstation")
def get_react_workstation(full_path: str = "") -> HTMLResponse:
    """Serve the modern React + TypeScript reviewer workstation."""
    react_index = _REACT_DIST_PATH / "index.html"
    if react_index.exists():
        return HTMLResponse(content=react_index.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h1>AuthOS React Workstation</h1><p>Production build not found. Run 'npm run build' inside frontend/.</p>",
        status_code=404,
    )
