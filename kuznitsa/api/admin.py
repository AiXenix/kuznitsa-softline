"""Служебная консоль магазина."""
from datetime import datetime
from zoneinfo import ZoneInfo
from kuznitsa.analytics import dashboard, priorities
import json
import gzip
import os
from functools import lru_cache
from heapq import nsmallest
from pathlib import Path
from secrets import compare_digest
from typing import Literal, Any

from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, ConfigDict
from kuznitsa.config import WEIGHTS,ROOT
from kuznitsa.analytics import kpi, gaps, insights, replay, cost, digest
from kuznitsa.understand.intent import TITLES


def authorize(request:Request,x_admin_token:str=Header(default="")):
    read_only = request.method=="GET" or (request.method=="POST" and request.url.path=="/api/admin/priorities/preview")
    if read_only and os.getenv("KZ_ADMIN_OPEN")=="1":
        return
    token=os.getenv("KZ_ADMIN_TOKEN")
    if not token or not compare_digest(x_admin_token.encode(),token.encode()):
        raise HTTPException(403,"Требуется токен администратора")


from contextlib import asynccontextmanager
from kuznitsa.plans import naive


@asynccontextmanager
async def warm_search(app):
    engine=app.state.engine
    engine.catalog.legacy_category_names=engine.names["category"]
    naive.prepare(engine.catalog)
    engine._rules()
    yield


router=APIRouter(prefix="/api/admin",dependencies=[Depends(authorize)],lifespan=warm_search)


class Rule(BaseModel):
    model_config=ConfigDict(extra="forbid")
    kind:str
    conditions:dict={}
    action:dict
    enabled:bool=True


class Preview(BaseModel):
    q:str|None=Field(None,max_length=1500)
    weights:dict[str,float]
    limit:int=Field(10,ge=1,le=50)


class Replay(BaseModel):
    mode:Literal["fast","smart"]="fast"
    limit:int|None=Field(None,ge=1)


def checked(fn,*args,**kwargs):
    try:
        return fn(*args,**kwargs)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


def json_report(request,data):
    response=JSONResponse(data,headers={"Vary":"Accept-Encoding"})
    accepted={item.strip() for item in request.headers.get("accept-encoding","").lower().split(",")}
    if "gzip" in accepted and len(response.body)>16384:
        response.body=gzip.compress(response.body,compresslevel=1,mtime=0)
        response.headers.update({"Content-Encoding":"gzip","Content-Length":str(len(response.body))})
    return response


@router.get("/kpi")
def indicators(request:Request,segment:str|None=None,category:str|None=None,intent:str|None=None,engine:str|None=None,day:str|None=None,view:Literal["full","overview","slices"]="full"):
    result=kpi.report(request.app.state.engine.journal,segment=segment,category=category,intent=intent,engine=engine,day=day)
    labels=dict(category=request.app.state.engine.names["category"],intent=TITLES,
                segment=dict(smb="Малый бизнес",mid="Средний бизнес",enterprise="Крупный бизнес",guest="Гости",gov="Госзаказчики",edu="Образование",individual="Физические лица"),
                engine=dict(legacy="Обычный поиск по словам",kuznitsa="Кузница",naive="Поиск по названию"))
    if view=="overview":
        result.pop("slices",None)
    elif view=="slices":
        result={k:result[k] for k in ("scope","scope_text","note","slices")}
    for key,group in result.get("slices",{}).items():
        for item in group:
            item["label"]=labels.get(key,{}).get(item["key"],"Не определено" if item["key"]=="unknown" else item["key"])
    tz=ZoneInfo("Europe/Moscow")
    midnight=datetime.fromtimestamp(request.app.state.engine.clock(),tz).replace(hour=0,minute=0,second=0,microsecond=0)
    result["today"]=dict(label="Сегодня на стенде · Москва",start=midnight.timestamp(),items=request.app.state.engine.journal.rows(
        f"SELECT engine,count(*) searches,sum(zero) empty FROM searches WHERE source IN ({dashboard.LIVE}) AND ts>=? AND ts<? GROUP BY engine",
        (midnight.timestamp(),midnight.timestamp()+86400)))
    return json_report(request,result)


@router.get("/queries")
def queries(request:Request,kind:Literal["top","zero","low_ctr","rising","reformulated","recent"]="top",limit:int=Query(50,ge=1,le=500)):
    e=request.app.state.engine
    items=dashboard.recent(e.journal,limit,e.usd_rub) if kind=="recent" else dashboard.query_rows(e.journal,kind)[:limit]
    return dict(kind=kind,items=items)


@router.get("/failures")
def failures(request:Request):
    return dashboard.failure_rows(request.app.state.engine.journal)


@router.get("/gaps")
def assortment(request:Request):
    return json_report(request,gaps.report(request.app.state.engine))


@router.get("/insights")
def proposals(request:Request,role:str|None=None,status:str|None=None,view:Literal["full","list"]="full"):
    items=[r for r in insights.listing(request.app.state.engine.journal) if (not role or r["role"]==role) and (not status or r["status"]==status)]
    if view=="list":
        items=[{k:r[k] for k in ("id","type","title","role","status","confidence","impact","evidence_text","impact_text") if k in r} for r in items]
    return json_report(request,dict(items=items))


@router.get("/insights/{ident}")
def proposal_detail(request:Request,ident:str):
    result=insights.listing(request.app.state.engine.journal,ident)
    if not result:
        raise KeyError(ident)
    return JSONResponse(result[0])


@router.post("/insights/refresh")
def refresh(request:Request):
    e=request.app.state.engine
    result=insights.discover(e)
    dashboard.warm(e)
    return result


@router.post("/insights/{ident}/{operation}")
def decision(request:Request,ident:str,operation:Literal["apply","reject","verify"]):
    return checked(insights.transition,request.app.state.engine,ident,operation)


@router.get("/rules")
def rules(request:Request):
    c=request.app.state.engine.controls
    return dict(items=c.rules(),version=c.version())


@router.post("/rules",status_code=201)
def create(request:Request,body:Rule):
    c=request.app.state.engine.controls
    return dict(id=checked(c.save,**body.model_dump()),version=c.version())


@router.put("/rules/{ident}")
def update(request:Request,ident:str,body:Rule):
    c=request.app.state.engine.controls
    return dict(id=checked(c.save,ident=ident,**body.model_dump()),version=c.version())


@router.delete("/rules/{ident}")
def remove(request:Request,ident:str):
    c=request.app.state.engine.controls
    c.remove(ident)
    return dict(id=ident,version=c.version())


@router.get("/weights")
def weights(request:Request):
    c=request.app.state.engine.controls
    return dict(weights=c.weights() or WEIGHTS,version=c.version())


@router.post("/weights")
def set_weights(request:Request,body:dict[str,float]):
    checked(request.app.state.engine.controls.set_weights,body)
    return weights(request)


@router.post("/preview")
def preview(request:Request,body:Preview):
    e=request.app.state.engine
    if set(body.weights)!=set(WEIGHTS) or abs(sum(body.weights.values())-1)>.0001 or any(not 0<=v<=1 for v in body.weights.values()):
        raise HTTPException(422,"Проверьте веса")
    phrases=[body.q] if body.q else [r["q_raw"] for r in e.journal.rows("""SELECT q_raw FROM active_history
        GROUP BY q_raw ORDER BY count(*) DESC,q_raw LIMIT ?""",(body.limit,))]
    return insights.preview(e,body.weights,phrases)


@router.post("/replay",status_code=202)
def start_replay(request:Request,body:Replay,background:BackgroundTasks):
    e=request.app.state.engine
    plan=checked(replay.prepare,e,body.mode,body.limit)
    ident,selected,*_=plan
    done=e.journal.rows("SELECT count(*) n FROM replay_results WHERE run_id=?",(ident,))[0]["n"]
    active=e.journal.rows("SELECT id FROM active_replay")
    if done<len(selected) or not active or active[0]["id"]!=ident:
        def publish():
            replay.execute(e,body.mode,plan)
            dashboard.warm(e)
        background.add_task(publish)
    return dict(id=ident,status="accepted" if done<len(selected) else "completed",processed=done,total=len(selected))


@router.get("/replay/{ident}")
def replay_status(request:Request,ident:str):
    return replay.summary(request.app.state.engine.journal,ident)


@router.get("/cost")
def expenses(request:Request,daily:int=Query(1000,ge=0)):
    return cost.report(request.app.state.engine.journal,daily)


@router.get("/search/{search_id}")
def search(request:Request,search_id:str):
    return request.app.state.engine.journal.detail(search_id)


@router.get("/eval")
def evaluation(request:Request):
    data=Path(request.app.state.engine.journal.path).parent
    path=max((data/"eval").glob("*.jsonl"),key=lambda p:p.stat().st_mtime,default=None)
    items=[json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path else []
    scenarios={}
    for fixture in (ROOT/"eval").glob("queries.dev.jsonl"):
        with fixture.open() as stream:
            for line in stream:
                if line.strip():
                    row=json.loads(line)
                    if row.get("id") and row.get("scenario"):
                        scenarios[row["id"]]=row["scenario"]
    groups={}
    for item in items:
        key=scenarios.get(item.get("id"),"unknown")
        counts=groups.setdefault(key,dict(total=0,passed=0))
        counts["total"]+=1
        counts["passed"]+=int(bool(item.get("checks")) and all(item["checks"].values()))
    return dict(file=path.name if path else None,items=items,scenarios=groups)


@lru_cache(8)
def review_rows(path,mtime,size):
    def decisions():
        with path.open() as stream:
            for line in stream:
                if line.strip():
                    row=json.loads(line)
                    if row.get("fallback") or not row.get("accepted") or row.get("confidence")=="low":
                        yield row
    return nsmallest(50,decisions(),key=lambda r:(not bool(r.get("fallback")),bool(r.get("accepted")),r.get("probability") or 0))


@router.get("/ingest")
def ingestion(request:Request):
    e=request.app.state.engine
    path=Path(e.journal.path).parent/"import_report.json"
    sources=e.journal.rows("SELECT source,count(*) searches FROM searches GROUP BY source")
    for r in sources:
        r["service"]=r["source"] in ("eval","replay")
    reports=e.journal.rows("SELECT value FROM kv WHERE key LIKE 'settings:import-report:%' ORDER BY updated DESC")
    catalog=json.loads(path.read_text()) if path.is_file() else None
    ai_file=path.with_name("import_ai.jsonl")
    stat=ai_file.stat() if ai_file.is_file() else None
    ai=(catalog or {}).get("ai") or {}
    history=[json.loads(r["value"]) for r in reports]
    external=[dict(file=r["file"],items=r.get("external_phrases",[]),metrics=r.get("report_metrics",{})) for r in history if r.get("kind")=="metrika_external_phrases"]
    crm=[dict(file=r["file"],**r["crm"]) for r in history if r.get("crm")]
    return dict(catalog=catalog,external_phrases=external,crm_leads=crm,classification_usd=ai.get("usd"),forecast_usd=ai.get("forecast_usd",(catalog or {}).get("forecast_usd")),review=review_rows(ai_file,stat.st_mtime_ns,stat.st_size) if stat else [],history=history,cards=len(e.catalog.cards),offers=len(e.catalog.offers_by_id),
                sources=sources)


@router.get("/digest")
def summary(request:Request,role:Literal["head_ecom","ecom_manager","product_manager","content_manager","customer"]|None=None,
            format:Literal["json","md","xlsx"]="json"):
    if format!="json":
        from kuznitsa.analytics.exports import export
        return export(request.app.state.engine,role or "head_ecom",format)
    return checked(digest.digest,request.app.state.engine.journal,role)



def priority_result(operation, *args):
    try:
        return operation(*args)
    except ValueError as exc:
        return JSONResponse({"error":{"code":"invalid_rule","message":str(exc)}},status_code=400)
    except NotImplementedError as exc:
        return JSONResponse({"error":{"code":"preview_unavailable","message":str(exc)}},status_code=503)


@router.get("/priorities")
def priority_list(request: Request):
    return priorities.listing(request.app.state.engine)


@router.get("/priorities/audit")
def priority_history(request: Request):
    return priorities.audit(request.app.state.engine.journal)


@router.get("/priorities/export")
def priority_export(request: Request):
    return priorities.export_rules(request.app.state.engine.journal)


@router.post("/priorities/import")
def priority_import(request: Request, body: Any = Body(None)):
    return priority_result(priorities.import_rules,request.app.state.engine.journal,body)


@router.post("/priorities/preview")
def priority_preview(request: Request, body: Any = Body(None)):
    return priority_result(priorities.preview,request.app.state.engine,body)


@router.post("/priorities")
def priority_create(request: Request, body: Any = Body(None)):
    return priority_result(priorities.change,request.app.state.engine.journal,"create",body)


@router.put("/priorities/{ident}")
def priority_update(request: Request, ident: str, body: Any = Body(None)):
    return priority_result(priorities.change,request.app.state.engine.journal,"update",body,ident)


@router.delete("/priorities/{ident}")
def priority_delete(request: Request, ident: str):
    return priority_result(priorities.change,request.app.state.engine.journal,"delete",None,ident)


@router.post("/priorities/{ident}/toggle")
def priority_toggle(request: Request, ident: str):
    return priority_result(priorities.change,request.app.state.engine.journal,"toggle",None,ident)
