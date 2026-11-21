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
    journal = request.app.state.engine.journal
    found = journal.rows(
        "SELECT search_id FROM searches WHERE q_raw=? ORDER BY ts DESC, search_id DESC LIMIT 1",
        (q,),
    )
    if not found:
        raise HTTPException(404, "В журнале нет записи с этой фразой")
    return found[0]


@router.get("/api/admin/ui/history-days")
def history_days(request: Request):
    """Project only historical traffic for the chart and its Moscow date range."""
    from kuznitsa.api.admin import authorize

    authorize(request, request.headers.get("X-Admin-Token", ""))
    journal = request.app.state.engine.journal
    days = journal.read_report(
        """SELECT date(ts, 'unixepoch', '+3 hours') AS key,
                  count(*) AS searches, avg(zero) AS zero_rate
           FROM searches WHERE source='history' AND ts IS NOT NULL GROUP BY key ORDER BY key"""
    )
    period = journal.read_report(
        """SELECT date(min(ts), 'unixepoch', '+3 hours') AS start,
                  date(max(ts), 'unixepoch', '+3 hours') AS end FROM searches"""
    )[0]
    return {"items": days, "period": period}
