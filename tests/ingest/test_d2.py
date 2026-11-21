import json
from collections import Counter
from threading import Barrier, Lock
from time import sleep

import httpx
import pytest
import yaml

from kuznitsa.config import ROOT
from kuznitsa.ingest.catalog import import_catalog
from kuznitsa.ingest.selfcheck import probes,sample
from kuznitsa.schema import Offer

FIXTURES=ROOT/"docs/ingest_examples"
KB=ROOT/"kb"


def test_embed_longtail(tmp_path):
    report=import_catalog([FIXTURES/"longtail.csv"],tmp_path,KB)
    expected=json.loads((FIXTURES/"longtail.gold.json").read_text())
    rows=yaml.safe_load((tmp_path/"kb_auto.yaml").read_text())["families"]
    assert len(rows)==len(expected)==64
    correct=sum(f["category"]==expected[f["name"]]["category"] for f in rows)
    assert correct>=.70*len(rows)
    assert report["ai"]["questions"]==43+3*64 and report["ai"]["usd"]==0
    offers=[Offer.model_validate_json(l) for l in (tmp_path/"catalog.jsonl").read_text().splitlines()]
    assert len(offers)==256 and all(o.registry is None and not o.certs for o in offers)
    known={f["id"]:f for f in rows}
    assert all(o.category_id==known[o.family_id]["category"] for o in offers)


@pytest.mark.parametrize("status",[200,429])
def test_transport_cache_and_degradation(status,tmp_path,monkeypatch):
    monkeypatch.setenv("KZ_EMBED_MODEL","off")
    inflight=peak=calls=0
    lock=Lock()
    first_pair=Barrier(2)
    def respond(request):
        nonlocal inflight,peak,calls
        assert request.url.host=="127.0.0.1"
        with lock:
            calls+=1
            inflight+=1
            peak=max(peak,inflight)
            call=calls
        if call<=2 and status==200:
            first_pair.wait(timeout=5)
        sleep(.025)
        with lock:
            inflight-=1
        qs=json.loads(request.content)["questions"]
        answers={k:dict(choice="none",probabilities={"none":1}) for k in qs}
        if "category" in qs:
            first=next(iter(qs["category"]["criteria"]))
            answers["category"]=dict(choice=first,probabilities={first:.54,"none":.46})
        return httpx.Response(status,json=dict(answers=answers,usage=dict(cost=.00001)))
    path=tmp_path/"data"
    args=([FIXTURES/"unknown.csv"],path,KB)
    opts=dict(ai="jev",transport=httpx.MockTransport(respond))
    dry=import_catalog(*args,**opts,dry_run=True)["ai"]
    assert dry["forecast_sent"]==4 and dry["forecast_usd"]>0 and calls==0 and not path.exists()
    result=import_catalog(*args,**opts)["ai"]
    if status==200:
        assert calls==result["sent"]==4 and peak==2 and result["usd"]==pytest.approx(.00004)
        cached=import_catalog(*args,**opts,ai_budget_usd=0)["ai"]
        assert cached["cached"]==4 and not cached["sent"] and not cached["usd"]
        assert not import_catalog(*args,**opts,dry_run=True)["ai"]["forecast_sent"]
        assert all(not d["accepted"] for d in map(json.loads,(path/"import_ai.jsonl").read_text().splitlines()) if d["source"]=="jev")
    else:
        assert 1<=calls<=2 and result["fallback"]["http_429"]==4
        saved=calls
        assert import_catalog(*args,**opts,ai_budget_usd=0)["ai"]["fallback"]["budget"]==4 and calls==saved


def test_rule_fields_and_explicit_regulatory_data(tmp_path,monkeypatch):
    monkeypatch.setenv("KZ_EMBED_MODEL","off")
    source=tmp_path/"rows.json"
    row=dict(name="Oriole ФСТЭК",family="Oriole",brand="Xyzania",description="Облачная служба для Windows и Linux",category_id="endpoint_security")
    source.write_text(json.dumps([{**row,"sku":"A"},{**row,"sku":"B","registry":True,"certs":["fsb"]}]))
    import_catalog([source],tmp_path,KB)
    a,b=[Offer.model_validate_json(l) for l in (tmp_path/"catalog.jsonl").read_text().splitlines()]
    assert not a.certs and a.registry is None and b.certs==["fsb"] and b.registry
    assert a.category_id=="endpoint_security" and set(a.platforms)=={"windows","linux"}
    f=yaml.safe_load((tmp_path/"kb_auto.yaml").read_text())["families"][0]
    assert f["deployment"]==["cloud"] and not f.get("certs") and f.get("registry") is None


def test_probes_and_balanced_sampling():
    import random
    rows=[Offer(offer_id=str(i),name="Arvo",family_id="arvo",family_name="Arvo",edition="pro",sku=f"A-{i}",
                vendor="Supplier",vendor_id=str(i%2),category_id=str(i%3),lic={"qty_min":25,"qty_max":49,"metric":"device"})
          for i in range(60)]
    selected=list(sample(rows,12,random.Random(7)))
    assert selected==list(sample(rows,12,random.Random(7)))
    assert sorted(Counter(o.vendor_id for o in selected).values())==[6,6]
    assert sorted(Counter(o.category_id for o in selected).values())==[4,4,4]
    qs={k:(q,e) for k,q,e in probes(rows[0],{"families":{},"categories":{"0":{"title":"Антивирус"}}},random.Random(7))}
    assert len(qs)==9 and qs["exact"]==("Arvo",None) and qs["sku"]==("A-0","pro")
    assert "30 пк" in qs["quantity"][0] and qs["phonetic"][0]=="арво про"
