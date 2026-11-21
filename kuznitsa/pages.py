"""Public storefront pages, registered before the fallback in app.py."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles
from starlette.routing import Route

WEB = Path(__file__).resolve().parents[1] / "web"
FLOW_DOCS = WEB.parent / "docs" / "flows"
DOCS = WEB.parent / "docs"


@asynccontextmanager
async def document_routes(app):
    # FastAPI registers its built-in /docs before application routers.
    for index, route in enumerate(app.router.routes):
        if getattr(route, "name", None) == "swagger_ui_html" and route.path == "/docs":
            app.router.routes[index] = Route("/api/docs", route.endpoint, name=route.name)
            break
    yield


router = APIRouter(include_in_schema=False, lifespan=document_routes)
assets = StaticFiles(directory=WEB)


@router.get("/")
@router.get("/flows")
@router.get("/docs")
@router.get("/docs/")
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


def document_path(name: str):
    relative = Path(name)
    if relative.suffix != ".md" or relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(404)
    root = DOCS.resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or path.suffix != ".md" or not path.is_file():
        raise HTTPException(404)
    return path


@router.get("/docs/{name:path}")
def document_page(name: str):
    document_path(name)
    return page()


@router.get("/web-data/documents")
def document_list():
    return sorted(p.name for p in DOCS.glob("*.md")
                  if p.resolve().parent == DOCS.resolve() and p.resolve().suffix == ".md" and p.is_file())


@router.get("/web-data/documents/{name:path}")
def document_source(name: str):
    return FileResponse(document_path(name), media_type="text/plain",
                        headers={"Cache-Control": "no-cache"})
