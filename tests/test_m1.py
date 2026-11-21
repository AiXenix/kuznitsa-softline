import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from fastapi.testclient import TestClient
from kuznitsa.app import create_app
from kuznitsa.config import Config
from kuznitsa.kb.loader import load
from kuznitsa.mock.catalog_gen import build
from kuznitsa.llm.jev import Jev,Disabled
from kuznitsa.schema import Request,Offer
from kuznitsa.text import tokens,sku_key
from kuznitsa.understand.repair import repair


def ask(e,q,**kw):
    return e.search(Request(q=q,mode="fast",**kw))


def cards(r):
    return [i.get("card",i) for b in r["blocks"] if b["type"] in ("products","analogs") for i in b["items"]]


@pytest.mark.parametrize("q,w",[("C++ C# .NET",["c++","c#",".net"]),("1c:Бухгалтерия 8.3",["1с","бухгалтерия","8.3"]),
                               ("win11 office2021 50пк",["windows","11","office","2021","50","пк"]),("FQС‑10572",["fqc-10572"])])
def test_normalize(q,w):
    assert tokens(q)==w


def test_loader(tmp_path):
    (tmp_path/"families").mkdir()
    p=tmp_path/"families/f.yaml"
    p.write_text("- {id: good, name: Перо, catalog: no, platforms: linux, vendor: missing}\n- {id: extra, name: Перо, custom: true}\n- {oops: yes}")
    kb=load(tmp_path)
    f=kb.rows["families"]["good"]
    assert f["catalog"] is False and f["platforms"]==["linux"] and "extra" not in kb.rows["families"] and kb.warnings
    assert kb.errors and kb.dangling and not kb.syntax
    p.write_text("- [")
    assert load(tmp_path).syntax


def test_repeatable_generator(tmp_path):
    cfg=Config(kb=tmp_path/"empty",data=tmp_path/"data")
    count=build(cfg,load(cfg.kb))
    def digest():
        return [hashlib.sha256(p.read_bytes()).digest() for p in sorted(cfg.data.glob("*.jsonl"))]
    first=digest()
    assert count>1000 and build(cfg,load(cfg.kb))==count and first==digest()


@pytest.mark.parametrize("q,w",[("ctdth","север"),("севре","север"),("northshield","north shield"),("8.3","8.3")])
def test_repair(engine,q,w):
    assert " ".join(repair(q,engine.lex)[0])==w


def test_filters(engine):
    r=ask(engine,"север продление на 30 компов на 2 года до 180 тысяч")
    c=cards(r)[0]
    assert r["understood"]["qty"]==dict(value=30,metric="device")
    assert c["offer"]["term_months"]==24 and c["offer"]["action"]=="renewal"
    assert c["offer"]["qty_min"]==25 and c["calc"]["total"]==30*c["offer"]["price"]
    assert not r["notes"] and c["calc"]["total"]<=180000


def test_pack_and_exclude(engine):
    r=ask(engine,"антивирус не север на 17 пк")
    assert r["understood"]["exclude"]=={"vendor":["north"]}
    c=cards(r)[0]
    assert c["vendor"]["id"]=="east" and c["offer"]["pack"]*c["calc"]["qty"]>=17


def test_relax(engine):
    r=ask(engine,"страж на 7 лет")
    assert cards(r) and r["notes"] and r["understood"]["filters"]["term_months"]==84
    assert not cards(ask(engine,"страж",filters={"registry":True}))
    assert not cards(ask(engine,"страж",filters={"certs":["fstec"]}))


def test_exact(engine):
    o=next(iter(engine.catalog.skus.values()))
    assert cards(ask(engine,o.sku.translate(str.maketrans("AX","АХ"))))[0]["offer"]["offer_id"]==o.offer_id
    assert not cards(ask(engine,"ZZZ-123456"))


@pytest.mark.parametrize("q,intent,block",[("офис","broad","clarify"),("old guard","out_of_catalog","analogs"),
    ("купить ноутбук","off_topic","clarify"),("asdfgh","off_topic","clarify"),("север","vendor","products"),
    ("щит","product","products"),("антивирус","category","products")])
def test_plans(engine,q,intent,block):
    r=ask(engine,q)
    assert r["understood"]["intent"]==intent and any(b["type"]==block for b in r["blocks"])
    assert len(r["trace"])==15 and r["cost"]["usd"]==0


def test_profiles(engine):
    answers=[cards(ask(engine,"антивирус на 30 пк",profile_id=p))[0] for p in ("smb_trade","edu_university","gov_clinic")]
    assert [c["offer"]["audience"] for c in answers]==["business","edu","gov"]
    assert answers[0]["offer"]["action"]=="renewal"
    assert len({c["offer"]["offer_id"] for c in answers})==3


def test_tiers(engine):
    r=ask(engine,"old guard",weights={"rel":0,"pers":1,"margin":1,"pop":1})
    tiers=[c["score"]["tier"] for c in cards(r)]
    assert len(set(tiers))>1 and tiers==sorted(tiers)


def test_api(engine):
    with TestClient(create_app(engine)) as api:
        assert api.get("/").status_code==200
        assert api.get("/health").json()["catalog"]["offers"]>100
        assert api.get("/api/meta").json()["profiles"]
        assert api.get("/api/suggest",params={"q":"сев"}).json()["groups"]
        assert api.get("/api/profile/smb_trade").json()["owned"][0]["expires_at"]=="2023-12-05"
        assert api.get("/api/profile/missing").status_code==404
        assert api.post("/api/search",json={"q":"щит","filters":{"price_max":"bad"}}).status_code==422
        r=api.get("/api/search",params={"q":"щит"}).json()
        c=cards(r)[0]
        assert len(api.get("/api/card/"+c["card_id"]).json()["variants"])==c["variants_count"]
        assert api.post("/api/event",json=dict(type="order",search_id=r["search_id"])).status_code==204
        assert api.post("/api/event",json=dict(type="click",search_id="missing")).status_code==422
        with sqlite3.connect(engine.journal.path) as db:
            assert db.execute("select count(*) from events where search_id=?",(r["search_id"],)).fetchone()[0]==1
            assert db.execute("select n_cards from searches where search_id=?",(r["search_id"],)).fetchone()[0]>0


def test_parallel(engine):
    with ThreadPoolExecutor(4) as pool:
        ids=list(pool.map(lambda _:ask(engine,"щит")["search_id"],range(12)))
    assert len(set(ids))==12


def test_transport():
    def transport(req):
        assert json.loads(req.content)["state"]=={"запрос":"текст"}
        return httpx.Response(200,json={"answers":{"intent":{"choice":"sku"}}})
    client=Jev(transport=httpx.MockTransport(transport))
    assert client.decide("текст",{"intent":{"type":"choice"}})["intent"]["choice"]=="sku"
    client.close()
    assert Disabled().decide("текст",{})=={}


@pytest.mark.parametrize("q,quantity,term",[("щит на тридцать пять пк на год",35,12),("щит x10 на 2 года",10,24),
                                            ("антивирус от 25 до 49 пк",25,None)])
def test_quantity_phrases(engine,q,quantity,term):
    understood=ask(engine,q)["understood"]
    assert understood["qty"]["value"]==quantity
    assert understood["filters"].get("term_months")==term
    assert "price_max" not in understood["filters"]


def test_full_trace_when_smart(engine):
    r=engine.search(Request(q="сравнить щит или страж",mode="smart"))
    assert r["understood"]["intent"]=="compare"
    assert next(x for x in r["trace"] if x["step"]=="plan")["status"]=="ok"
    assert any(b["type"]=="compare" and len(b["columns"])==2 for b in r["blocks"])


def test_multiple_sku(engine):
    a=engine.catalog.cards["shield:pro"].offers[0]
    b=engine.catalog.cards["guard"].offers[0]
    assert {c["offer"]["offer_id"] for c in cards(ask(engine,a.sku+" "+b.sku))}=={a.offer_id,b.offer_id}


def test_catalog_columns_and_no_kb(cfg,tmp_path):
    from kuznitsa.engine import Engine
    from kuznitsa.mock.catalog_gen import write_lines
    from kuznitsa.schema import Client
    from kuznitsa.config import Config
    write_lines(tmp_path/"catalog.jsonl",[Offer(offer_id="unmapped",name="Mosaic",sku="ABC-4321-RU").model_dump_json()])
    write_lines(tmp_path/"clients.jsonl",[Client(client_id="guest",title="Гость",segment="smb").model_dump_json()])
    empty=Engine.open(Config(kb=tmp_path/"absent",data=tmp_path,cache=tmp_path/"cache",embed="off"))
    assert cards(ask(empty,"ABC-4321"))[0]["offer"]["offer_id"]=="unmapped"
    assert cards(ask(empty,"ABC-4321"))[0]["calc"] is None


def test_cache_warm(cfg,engine):
    from kuznitsa.engine import Engine
    other=Engine.open(cfg)
    assert engine.catalog.scores("север")==other.catalog.scores("север")
    assert list(cfg.cache.glob("lex-*.npz"))


def test_rate_limit(engine,cfg):
    from dataclasses import replace
    with TestClient(create_app(engine,replace(cfg,rate_limit=1,cors_origins=["https://shop.example"]))) as api:
        assert api.get("/api/search?q=щит").status_code==200
        assert api.get("/api/suggest?q=щ").status_code==200
        for path in ("search","suggest"):
            limited=api.get(f"/api/{path}?q=щит",headers={"Origin":"https://shop.example"})
            assert limited.headers["access-control-allow-origin"]=="https://shop.example"
            assert limited.status_code==429 and int(limited.headers["Retry-After"])>0


def test_concurrent_store_and_eval(engine,cfg):
    from kuznitsa.evaluation import evaluate
    path=cfg.data/"checks.jsonl"
    path.write_text(json.dumps(dict(q="страж",id="guard",scenario="product",
                                   **{"assert":dict(family_any=["guard"],top1_any=["Guard"])})))
    assert evaluate(engine,path,"fast",cfg.data)["scenarios"]["product"]==dict(total=1,passed=1,pass_rate=1.)


def test_bad_records_are_reported(tmp_path):
    (tmp_path/"families").mkdir()
    (tmp_path/"families/f.yaml").write_text("- {id: bad, name: One, license: {metrics: foo}}\n- {id: good, name: Two}")
    kb=load(tmp_path)
    assert set(kb.rows["families"])=={"good"} and kb.errors and not kb.syntax


def test_sku_filter_exclusion(engine):
    sku=engine.catalog.cards["shield:pro"].offers[0].sku
    assert not cards(ask(engine,sku,exclude={"vendor":"north"}))


def test_exact_category_context(engine):
    r=ask(engine,"офис",category="office_suite")
    assert r["understood"]["intent"]=="category" and cards(r)
    assert all(c["category"]["id"]=="office_suite" for c in cards(r))
