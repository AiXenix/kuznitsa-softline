"""Public storefront pages, registered before the fallback in app.py."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

WEB = Path(__file__).resolve().parents[1] / "web"
router = APIRouter(include_in_schema=False)
assets = StaticFiles(directory=WEB)


@router.get("/")
@router.get("/about")
@router.get("/scenarios")
@router.get("/styleguide")
@router.get("/admin")
@router.get("/inspect/{search_id}")
def page():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/web/{path:path}")
async def asset(path: str, request: Request):
    response = await assets.get_response(path, request.scope)
    response.headers["Cache-Control"] = "no-store" if path.endswith(".html") else "no-cache"
    return response
