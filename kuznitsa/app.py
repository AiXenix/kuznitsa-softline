from contextlib import asynccontextmanager
import sqlite3
from time import monotonic
from collections import deque
from .api.models import Event
from fastapi import FastAPI, Request as HttpRequest, Response, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException
import yaml
from .config import Config,ROOT,WEIGHTS,MODE_TITLES
from .engine import Engine
from .optional import optional_module
from .plans.presentation import profile_info
from .schema import Request
from .suggest.index import suggest


def create_app(engine=None,cfg=None):
    cfg=cfg or Config()
    @asynccontextmanager
    async def lifespan(app):
        core = engine or Engine.open(cfg)
        rules = optional_module("kuznitsa.analytics.controls")
        if rules is not None:
            core.controls = rules.RuleControls(core.journal)
        app.state.engine = core
        try:
            yield
        finally:
            if engine is None:
                core.close()
    app=FastAPI(lifespan=lifespan)
    def core():
        return app.state.engine
    def error(status,code,message):
        return JSONResponse(dict(error=dict(code=code,message=message)),status_code=status, headers={"X-Robots-Tag":"noindex, nofollow"})

    traffic={}
    next_cleanup=0.
    @app.middleware("http")
    async def limits(req,call_next):
        nonlocal next_cleanup
        if cfg.rate_limit>0 and req.url.path in ("/api/search","/api/suggest"):
            now=monotonic()
            if now>=next_cleanup:
                for key in list(traffic):
                    if not traffic[key] or traffic[key][-1]<=now-60:
                        del traffic[key]
                next_cleanup=now+60
            key=req.client.host if req.client else ""
            recent=traffic.setdefault(key,deque())
            while recent and recent[0]<=now-60:
                recent.popleft()
            if len(recent)>=cfg.rate_limit:
                return error(429,"rate_limit","Слишком много запросов. Повторите через минуту.")
            recent.append(now)
        response=await call_next(req)
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["X-Robots-Tag"]="noindex, nofollow"
        response.headers["Referrer-Policy"]="same-origin"
        return response

    @app.exception_handler(KeyError)
    async def missing(req,exc):
        return error(404,"not_found","Профиль или карточка отсутствует.")
    @app.exception_handler(RequestValidationError)
    async def invalid(req,exc):
        return error(422,"invalid_request","Проверьте параметры запроса.")
    @app.exception_handler(HTTPException)
    async def http_error(req,exc):
        return error(exc.status_code,"http_error","Ресурс недоступен.")
    @app.get("/health")
    def health():
        c=core().catalog
        return dict(ok=True,version="0.1.0",catalog=dict(offers=sum(len(x.offers) for x in c.cards.values()),cards=len(c.cards)),kb={**core().kb.report()["counts"], "auto":core().kb.auto},llm=dict(enabled=core().llm.enabled))
    @app.get("/api/meta")
    def meta():
        preferred=ROOT/"docs/scenarios.yaml"
        paths=[preferred] if preferred.exists() else sorted((ROOT/"design/proposals").glob("*/scenarios.yaml"))
        scenarios={}
        for path in paths:
            data=yaml.load(path.read_text(),Loader=yaml.CSafeLoader)
            if isinstance(data,dict):
                data=data.get("scenarios",[])
            for row in data or []:
                if isinstance(row,dict) and row.get("id"):
                    scenarios.setdefault(row["id"],row)
        return dict(profiles=[profile_info(c) for c in core().clients.values() if c.demo],
                    categories=[dict(id=k,title=r.get("title",k)) for k,r in core().kb.rows["categories"].items() if not r.get("parent")],
                    modes=["fast","smart","naive"],mode_titles=MODE_TITLES,weights=WEIGHTS,catalog=health()["catalog"],scenarios=list(scenarios.values()) or [dict(id="product",title="Поиск продукта",examples=[next(iter(core().catalog.cards.values())).title] if core().catalog.cards else [])],
                    disclaimer="Каталог, цены и клиенты — демонстрационные.")
    @app.post("/api/search")
    def search(req:Request):
        if "mode" not in req.model_fields_set:
            req=req.model_copy(update={"mode":cfg.mode})
        return core().search(req)
    @app.get("/api/search")
    def search_get(req:HttpRequest):
        try:
            data=dict(req.query_params)
            if "ignore" in data:
                data["ignore"]=req.query_params.getlist("ignore")
            data.setdefault("mode",cfg.mode)
            return search(Request.model_validate(data))
        except ValidationError:
            return error(422,"invalid_request","Проверьте параметры запроса.")
    @app.get("/api/suggest")
    def suggestions(q:str=Query(max_length=1500),profile_id:str="guest",category:str|None=None,session_id:str=""):
        return suggest(core(),q,profile_id,category)
    @app.post("/api/event",status_code=204)
    def event(data:Event):
        try:
            core().journal.event(core().clock(),data.model_dump())
        except sqlite3.IntegrityError:
            return error(422,"unknown_search","Неизвестный поиск.")
        return Response(status_code=204)
    @app.get("/api/card/{card_id}")
    def card(card_id:str,profile_id:str="guest",qty:int|None=Query(None,ge=1),term:int|None=None,action:str|None=None):
        return core().card(card_id,profile_id,qty,term,action)
    @app.get("/api/profile/{id}")
    def profile(id:str):
        client=core().clients[id]
        return {**client.model_dump(),**profile_info(client)}
    @app.get("/robots.txt")
    def robots():
        return Response("User-agent: *\nDisallow: /\n",media_type="text/plain")
    for name in ("kuznitsa.api.admin", "kuznitsa.api.files", "kuznitsa.pages"):
        module = optional_module(name)
        if module is not None:
            router = module.router
            prefix = ""
            if name == "kuznitsa.api.admin" and not any(
                route.path == "/api/admin" or route.path.startswith("/api/admin/") for route in router.routes
            ):
                prefix = "/api/admin"
            app.include_router(router, prefix=prefix)
    @app.get("/")
    def home():
        return FileResponse(ROOT/"web/index.html")
    app.mount("/web",StaticFiles(directory=ROOT/"web"),name="web")
    return app


app=create_app()
