import json
import sqlite3
from threading import Barrier
import httpx
import pytest

from kuznitsa.engine import Engine
from kuznitsa.llm.decisions import Decisions,choice
from kuznitsa.llm.jev import Jev
from kuznitsa.schema import Request


def response(request,probability=.88):
    body=json.loads(request.content)
    result={}
    for key,q in body["questions"].items():
        target="broad" if key=="intent" else "none" if "none" in q["criteria"] else next(iter(q["criteria"]))
        result[key]={"choice":target,"probabilities":{target:probability}}
    return httpx.Response(200,json=dict(answers=result,usage=dict(input_tokens=27,output_tokens=5,cost=.0123)))


def test_batches_parallel_cache_and_cost(tmp_path):
    barrier=Barrier(2,timeout=3)
    sizes=[]
    def reply(request):
        sizes.append(len(json.loads(request.content)["questions"]))
        barrier.wait()
        return response(request)
    client=Jev(transport=httpx.MockTransport(reply))
    db=tmp_path/"store.sqlite"
    service=Decisions(client,db,lambda:1712345678,3)
    cards=[dict(card_id=str(i),title="Программа "+str(i)) for i in range(30)]
    rows=service.rerank("search1","ui",{"запрос":"лицензия"},cards)
    assert sorted(sizes)==[10,20] and all(r["ok"] and r["usd"]==.0123 for r in rows)
    assert all(r["cached"] and r["usd"]==0 for r in service.rerank("search2","ui",{"запрос":"лицензия"},cards))
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*),SUM(tokens_in),SUM(cost_usd) FROM llm_calls").fetchone()==(4,54,.0246)
    service.pool.shutdown()
    client.close()


def test_circuit_and_budget(tmp_path):
    clock=[1700000000.]
    replies=[503]*5+[200,200]
    def transport(r):
        return response(r) if replies.pop(0)==200 else httpx.Response(503)
    client=Jev(transport=httpx.MockTransport(transport))
    service=Decisions(client,tmp_path/"db",lambda:clock[0],.01)
    questions={"intent":choice("Сценарий",{"broad":"Уточнить"})}
    def call(key,source="ui"):
        return service.request(key,source,"intent",{"q":key},questions)[1]
    assert all(call("first")["sent"] for _ in range(5))
    assert not call("blocked")["sent"] and len(replies)==2
    clock[0]+=61
    assert call("first")["ok"] and not call("second")["sent"]
    assert call("first")["cached"]
    service.run_budget=.01
    assert call("evaluation","eval")["ok"] and not call("next","eval")["sent"]
    client.close()


def test_modes_and_failed_decision(cfg):
    calls=[]
    def transport(r):
        calls.append(r)
        return httpx.Response(503)
    client=Jev(transport=httpx.MockTransport(transport))
    engine=Engine.open(cfg,llm=client)
    for q in ["North Shield",engine.catalog.cards["shield:pro"].offers[0].sku]:
        r=engine.search(Request(q=q,mode="smart"))
        assert r["cost"]["llm_calls"]==0
    fast=engine.search(Request(q="антивирус",mode="fast"))
    assert not calls
    fallback=engine.search(Request(q="антивирус",mode="smart"))
    assert fallback["mode"]=="fast" and fallback["notes"] and fallback["cost"]["llm_calls"]==1
    assert fallback["blocks"]==fast["blocks"]
    assert next(t for t in fallback["trace"] if t["step"]=="rerank")["status"]=="fallback"
    client.close()


def test_cost_estimate_only_when_missing(tmp_path):
    def missing_cost(req):
        data=response(req).json()
        del data["usage"]["cost"]
        return httpx.Response(200,json=data)
    client=Jev(transport=httpx.MockTransport(missing_cost))
    service=Decisions(client,tmp_path/"llm",lambda:1,3,price_in=.05)
    q={"intent":choice("Сценарий",{"broad":"Уточнить"})}
    answers,meta=service.request("id","ui","intent",{"q":"по"},q)
    assert answers and meta["estimated"] and meta["usd"]==pytest.approx(27*.05/1_000_000)
    client.close()
