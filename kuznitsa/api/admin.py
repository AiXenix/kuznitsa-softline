"""Служебная консоль магазина."""
from collections import Counter
import json
import os
from pathlib import Path
from secrets import compare_digest
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, ConfigDict
from kuznitsa.config import WEIGHTS,ROOT
from kuznitsa.analytics import kpi, gaps, insights, replay, cost, digest
from kuznitsa.analytics.failures import REASONS,LABELS
from kuznitsa.understand.intent import TITLES


def authorize(request:Request,x_admin_token:str=Header(default="")):
    if request.method=="GET" and os.getenv("KZ_ADMIN_OPEN")=="1":
        return
    token=os.getenv("KZ_ADMIN_TOKEN")
    if not token or not compare_digest(x_admin_token.encode(),token.encode()):
        raise HTTPException(403,"Требуется токен администратора")


router=APIRouter(prefix="/api/admin",dependencies=[Depends(authorize)])


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
    limit:int=Field(100,ge=1,le=3000)


def checked(fn,*args,**kwargs):
    try:
        return fn(*args,**kwargs)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@router.get("/kpi")
def indicators(request:Request,segment:str|None=None,category:str|None=None,intent:str|None=None,engine:str|None=None,day:str|None=None):
    result=kpi.report(request.app.state.engine.journal,segment=segment,category=category,intent=intent,engine=engine,day=day)
    labels=dict(category=request.app.state.engine.names["category"],intent=TITLES,
                segment=dict(smb="Малый бизнес",mid="Средний бизнес",enterprise="Крупный бизнес",guest="Гости",gov="Госзаказчики",edu="Образование",individual="Физические лица"),
                engine=dict(legacy="Прежний поиск",kuznitsa="Кузница",naive="Поиск по названию"))
    for key,group in result["slices"].items():
        for item in group:
            item["label"]=labels.get(key,{}).get(item["key"],"Не определено" if item["key"]=="unknown" else item["key"])
    return result


@router.get("/queries")
def queries(request:Request,kind:Literal["top","zero","low_ctr","rising","reformulated"]="top",limit:int=Query(50,ge=1,le=500)):
    rows=[r for r in kpi.facts(request.app.state.engine.journal) if r["source"]!="replay"]
    return dict(kind=kind,items=kpi.queries(rows,kind,limit))


@router.get("/failures")
def failures(request:Request):
    rows=[r for r in kpi.facts(request.app.state.engine.journal) if r["source"]!="replay" and (kpi.failed(r) or r["reason"])]
    counts=Counter()
    examples={}
    for r in rows:
        reason=r["reason"] or ("ranking_issue" if (r["best_position"] or 0)>5 else "ambiguous")
        counts[reason]+=1
        examples.setdefault(reason,r["q"])
    return dict(items=[dict(reason=k,label=LABELS.get(k,k),count=v,example=examples[k]) for k,v in counts.most_common()],reasons=sorted(REASONS))


@router.get("/gaps")
def assortment(request:Request):
    return gaps.report(request.app.state.engine)


@router.get("/insights")
def proposals(request:Request,role:str|None=None,status:str|None=None):
    return dict(items=[r for r in insights.listing(request.app.state.engine.journal) if (not role or r["role"]==role) and (not status or r["status"]==status)])


@router.post("/insights/refresh")
def refresh(request:Request):
    return insights.discover(request.app.state.engine)


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
    phrases=[body.q] if body.q else [r["q_raw"] for r in e.journal.rows("""SELECT q_raw FROM searches
        WHERE source='history' GROUP BY q_raw ORDER BY count(*) DESC,q_raw LIMIT ?""",(body.limit,))]
    return insights.preview(e,body.weights,phrases)


@router.post("/replay",status_code=202)
def start_replay(request:Request,body:Replay,background:BackgroundTasks):
    e=request.app.state.engine
    plan=replay.prepare(e,body.mode,body.limit)
    ident,selected,*_=plan
    done=e.journal.rows("SELECT count(*) n FROM replay_results WHERE run_id=?",(ident,))[0]["n"]
    if done<len(selected):
        background.add_task(replay.execute,e,body.mode,plan)
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
    for fixture in sorted((ROOT/"eval").glob("*.jsonl")):
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


@router.get("/ingest")
def ingestion(request:Request):
    e=request.app.state.engine
    return dict(cards=len(e.catalog.cards),offers=len(e.catalog.offers_by_id),
                sources=e.journal.rows("SELECT source,count(*) searches FROM searches GROUP BY source"))


@router.get("/digest")
def summary(request:Request,role:str|None=None):
    return checked(digest.digest,request.app.state.engine.journal,role)
