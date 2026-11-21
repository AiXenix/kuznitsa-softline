"""Procurement files. Both endpoints share the application's search engine."""
from math import ceil
import json
import zlib
from typing import Literal

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic_core import to_json

from kuznitsa.analytics.store import result_cards
from kuznitsa.config import WEIGHTS
from kuznitsa.rank.business import ranked
from kuznitsa.quote.parse import FileError, LIMIT, parse
from kuznitsa.quote.export import SpecificationRequest, make_export

router=APIRouter()


def search_file(engine,data,name,profile_id,mode,session_id):
    positions,info=parse(data,name)
    req=SpecificationRequest(q="\n".join(p["query"] for p in positions),profile_id=profile_id,
                             mode=mode,session_id=session_id,source="ui",context="off")
    response=engine.search(req)
    block=next((b for b in response["blocks"] if b["type"]=="spec"),None)
    indexed={line["raw"]:line for line in (block or {}).get("lines",[])}
    lines=[]
    supplier_codes=None
    for i,p in enumerate(positions,1):
        line=indexed.get(p["query"])
        if line is None:
            found=response if len(positions)==1 else engine.search(req.model_copy(update=dict(q=p["query"],session_id="",mode="fast",source="eval")))
            cards=result_cards(found)
            card=next(iter(cards),None)
            calc=(card or {}).get("calc") or {}
            line=dict(raw=p["query"],understood=found["understood"],card=card,status="matched" if card else "not_found",
                      alternatives=cards[1:3],total=calc.get("total"),unit_price=calc.get("unit_price"))
        if p["sku"]:
            # A structured article is an explicit choice, even when its spelling
            # inside the product name was normalized as ordinary search text.
            if supplier_codes is None:
                from kuznitsa.ingest.source_index import codes
                from collections import defaultdict
                supplier_codes=defaultdict(list)
                for offer in engine.catalog.offers_by_id.values():
                    for key in {str(v).casefold() for v in (offer.sku,*codes(offer)) if v}:
                        supplier_codes[key].append(offer)
            candidates=supplier_codes.get(p["sku"].casefold(),[])
            exact=None
            if len({o.family_id or o.offer_id for o in candidates})==1:
                def preference(o):
                    fits=(o.lic.qty_min or 1)<=p["qty"]<=(o.lic.qty_max or p["qty"])
                    return (not fits,not o.available,o.price is None,o.price or 0,o.offer_id)
                exact=min(candidates,key=preference)
            if exact:
                group=engine.catalog.cards[exact.card_id]
                outside=(exact.lic.qty_min or 1)>p["qty"] or (exact.lic.qty_max or p["qty"])<p["qty"]
                count=None if outside else ceil(p["qty"]/(exact.lic.pack or 1))
                card=ranked(group,(exact,count,None),1,True,engine.clients[profile_id],WEIGHTS,engine.kb)
                card["position"]=1
                card["qty_out_of_range"]=outside
                calc=card.get("calc") or {}
                line={**line,"card":card,"status":"matched","total":calc.get("total"),
                      "unit_price":calc.get("unit_price"),"alternatives":[]}
            elif line.get("card"):
                line={**line,"card":None,"status":"not_found","total":None,"unit_price":None,
                      "alternatives":[line["card"],*line["alternatives"]][:3],
                      "note":"Указанный артикул не найден. Требуется согласовать замену."}
        card=line.get("card")
        if card and card.get("offer"):
            snapshot=engine.catalog.offers_by_id.get(card["offer"]["offer_id"])
            if snapshot is not None:
                card["offer"]["registry"]=snapshot.registry
                card["offer"]["source_id"]=getattr(snapshot,"source_id",None) or snapshot.attrs.get("source_id")
        lines.append({**line,"n":i,"qty":p["qty"],"unit":p["unit"]})
    response["blocks"]=[dict(type="spec",title="Подбор по спецификации",lines=lines,
                             unresolved=[l["n"] for l in lines if not l["card"]],
                             total=sum(l["total"] for l in lines) if all(l["total"] is not None for l in lines) else None)]
    response["upload"]=info
    ids=[c["card_id"] for c in result_cards(response)]
    reason=None if ids else "not_in_catalog"
    response["understood"].update(intent="spec_list",intent_title="Список позиций",zero_reason=reason)
    with engine.journal.transaction() as db:
        db.execute("""UPDATE searches SET response_z=?,blocks_json=?,top_cards_json=?,n_cards=?,zero=?,intent='spec_list',fail_reason=?
                      WHERE search_id=?""",(zlib.compress(to_json(response),1),'["spec"]',json.dumps(ids),len(ids),
                                            int(not ids),reason,response["search_id"]))
    return response


@router.post("/api/spec/upload")
async def upload(request:Request,name:str,profile_id:str="guest",mode:Literal["fast","smart"]="fast",session_id:str=""):
    try:
        data=bytearray()
        async for chunk in request.stream():
            if len(data)+len(chunk)>LIMIT:
                raise FileError(413,"file_too_large","Максимальный размер файла — 2 МБ.")
            data.extend(chunk)
        return await run_in_threadpool(search_file,request.app.state.engine,bytes(data),name,profile_id,mode,session_id)
    except FileError as exc:
        return JSONResponse({"error":{"code":exc.code,"message":str(exc)}},status_code=exc.status)


@router.get("/api/export/{search_id}")
def export(request:Request,search_id:str,format:Literal["xlsx","csv"]="xlsx"):
    content,name=make_export(request.app.state.engine,search_id,format)
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format=="xlsx" else "text/csv"
    return Response(content,media_type=mime,headers={"Content-Disposition":f'attachment; filename="{name}"'})
