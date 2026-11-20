"""Public storefront pages, registered before the fallback in app.py."""
from pathlib import Path

from fastapi import APIRouter, Query, Request
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
@router.get("/card/{card_id}")
@router.get("/inspect/{search_id}")
def page():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/web/{path:path}")
async def asset(path: str, request: Request):
    response = await assets.get_response(path, request.scope)
    response.headers["Cache-Control"] = "no-store" if path.endswith(".html") else "no-cache"
    return response


@router.get("/api/admin/ui/search-reference")
def search_reference(request: Request, q: str = Query(min_length=1, max_length=1500)):
    """Resolve an aggregate's phrase to its latest real journal row."""
    from fastapi import HTTPException
    from kuznitsa.api.admin import authorize

    authorize(request, request.headers.get("X-Admin-Token", ""))
    journal = request.app.state.engine.journal
    found = journal.rows(
        "SELECT search_id FROM searches WHERE q_raw=? ORDER BY ts DESC, search_id DESC LIMIT 1",
        (q,),
    )
    if not found:
        raise HTTPException(404, "В журнале нет записи с этой фразой")
    return found[0]
