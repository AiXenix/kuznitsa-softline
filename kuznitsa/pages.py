"""Public storefront pages, registered before the fallback in app.py."""
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

WEB = Path(__file__).resolve().parents[1] / "web"
FLOW_DOCS = WEB.parent / "docs" / "flows"
router = APIRouter(include_in_schema=False)
assets = StaticFiles(directory=WEB)


@router.get("/")
@router.get("/flows")
@router.get("/about")
@router.get("/scenarios")
@router.get("/styleguide")
@router.get("/admin")
@router.get("/card/{card_id}")
@router.get("/inspect/{search_id}")
def page():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/embed")
def embed_demo():
    return FileResponse(WEB / "embed/demo.html", headers={"Cache-Control": "no-store"})


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
    from kuznitsa.analytics.dashboard import search_reference as reference
    found = reference(request.app.state.engine, q)
    if not found:
        raise HTTPException(404, "В журнале нет записи с этой фразой")
    return found


@router.get("/api/admin/ui/history-days")
def history_days(request: Request):
    """Project only historical traffic for the chart and its Moscow date range."""
    from kuznitsa.api.admin import authorize

    authorize(request, request.headers.get("X-Admin-Token", ""))
    from kuznitsa.analytics.dashboard import history_days as day_projection
    return day_projection(request.app.state.engine.journal)


@router.get("/web-data/flows/{name}")
def flow_document(name: str):
    from fastapi import HTTPException
    if name not in {"flows", "examples", "timings"}:
        raise HTTPException(404)
    if (FLOW_DOCS / "flows.json").is_file():
        path = FLOW_DOCS / (name + ".json")
        if not path.is_file():
            raise HTTPException(404)
    else:
        path = WEB / "fixtures" / ("flows-" + name + ".json")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})
