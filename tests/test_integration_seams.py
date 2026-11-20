import sys
from types import ModuleType

from fastapi import APIRouter, Request as HttpRequest
from fastapi.testclient import TestClient
import pytest

from kuznitsa import cli
from kuznitsa.app import create_app
from kuznitsa.controls import Controls
from kuznitsa.engine import Engine
from kuznitsa.plans.naive import match
from kuznitsa.schema import Request


class Rules(Controls):
    def __init__(self):
        self.revision = 0
        self.target = None
        self.calls = []

    def version(self):
        return self.revision

    def synonyms(self):
        if self.revision > 0:
            return []
        return [
            dict(phrase="полярник", to="north", kind="vendor", rule_id="r1"),
            dict(phrase="зелёное поле", to="страж", kind="text", rule_id="r2"),
        ]

    def weights(self):
        return {"rel": .1, "margin": .8}

    def redirect(self, ctx):
        self.calls.append(ctx.copy())
        return self.target

    def merch(self, ctx, cards):
        if len(cards) < 2:
            return super().merch(ctx,cards)
        self.before = [c["card_id"] for c in cards]
        return dict(cards=cards[::-1], banners=[dict(kind="banner",text="Акция",rule_id="b")],
                    fired=[dict(kind="pin",rule_id="p",card_id=cards[-1]["card_id"],summary="Закреплено")])


def step(r, key):
    return next(s for s in r["trace"] if s["step"]==key)


def products(r):
    return next(b for b in r["blocks"] if b["type"]=="products")["items"]


def test_controls(cfg):
    rules=Rules()
    engine=Engine.open(cfg,controls=rules)
    for q,field,value,rid in [("полярник","vendor","north","r1"),("зелёное поле","family","guard","r2")]:
        r=engine.search(Request(q=q))
        assert r["understood"]["filters"][field]==[value]
        assert step(r,"entities")["detail"]["synonyms"][0]["rule_id"]==rid
    r=engine.search(Request(q="антивирус",mode="fast",weights={"rel":.9}))
    weights=step(r,"business")["detail"]["weights"]
    assert weights["margin"]==.8 and weights["rel"]==.9
    assert rules.calls[-1]==dict(q_raw="антивирус",q_norm="антивирус",intent="category",category_id="endpoint_security",
                                 segment="smb",profile_id="guest",mode="fast")
    cards=products(r)
    assert [c["card_id"] for c in cards]==rules.before[::-1]
    assert [c["position"] for c in cards]==list(range(1,len(cards)+1))
    assert step(r,"merch")["detail"]["fired"][0]["rule_id"]=="p"
    assert "Закреплено правилом магазина" in cards[0]["score"]["why"]
    assert r["banners"][0]["rule_id"]=="b"
    rules.revision+=1
    for q in ("полярник","зелёное поле"):
        assert not step(engine.search(Request(q=q)),"entities")["detail"]["synonyms"]


@pytest.mark.parametrize("target,intent", [({"q":"страж"},"product"),({"category":"office_suite"},"category"),({"intent":"broad"},"broad")])
def test_redirect(cfg,target,intent):
    rules=Rules()
    rules.target={**target,"rule_id":"direct"}
    engine=Engine.open(cfg,controls=rules)
    r=engine.search(Request(q="полярник"))
    assert len(rules.calls)==1 and r["query"]["raw"]=="полярник"
    assert r["understood"]["intent"]==intent
    assert step(r,"intent")["detail"]["redirect"]==rules.target
    if "q" in target:
        assert products(r)[0]["card_id"]=="guard"
    if "category" in target:
        assert all(c["category"]["id"]=="office_suite" for c in products(r))


def test_ignore_and_verbatim(engine):
    keys=["vendor","qty","action","term","price","exclude","profile","category"]
    r=engine.search(Request(q="север продление на 30 пк на 2 года до 6000 кроме страж",category="security",
                            profile_id="smb_trade",ignore=keys))
    u=r["understood"]
    assert not u["filters"] and not u["exclude"] and not u["qty"] and not u["chips"]
    assert r["profile"]["id"]=="guest" and step(r,"entities")["detail"]["ignored"]==keys
    for kwargs in [dict(ignore=["context"]),dict(context="off")]:
        r=engine.search(Request(q="страж",category="office_suite",**kwargs))
        assert "category" not in r["understood"]["filters"]
    assert engine.search(Request(q="ctdth"))["query"]["corrections"]
    assert not engine.search(Request(q="ctdth",verbatim=True))["query"]["corrections"]


def test_naive(engine,monkeypatch):
    class Recorder:
        def search(self,ts,req,r,count,reason,relaxed):
            self.row=(req.mode,r["engine"],count)
    journal=Recorder()
    monkeypatch.setattr(engine,"journal",journal)
    matches=match(engine.catalog,"SHI NOR",limit=None)
    assert len(matches)>3 and matches==sorted(matches,key=lambda o:-o.popularity)
    assert match(engine.catalog,"щит")==[] and match(engine.catalog,"")==[]
    r=engine.search(Request(q="SHI NOR",mode="naive",page_size=2,page=2))
    cards=products(r)
    assert journal.row==("naive","naive",len(matches)) and len(r["trace"])==2
    assert [c["offer"]["offer_id"] for c in cards]==[o.offer_id for o in matches[2:4]]
    assert cards[0]["card_id"]!=cards[1]["card_id"]
    assert engine.card(cards[0]["card_id"])["offer"]==cards[0]["offer"]


def add_module(monkeypatch,name,**attrs):
    module=ModuleType(name)
    module.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules,name,module)


def test_plugins_present(cfg,monkeypatch):
    pages=APIRouter()
    admin=APIRouter(prefix="/api/admin")
    @pages.get("/")
    def home():
        return "витрина"
    @admin.get("/inspect")
    def inspect(req:HttpRequest):
        return req.app.state.engine.controls.journal is req.app.state.engine.journal
    class RuleControls(Controls):
        def __init__(self,journal):
            self.journal=journal
    add_module(monkeypatch,"kuznitsa.api.admin",router=admin)
    add_module(monkeypatch,"kuznitsa.pages",router=pages)
    add_module(monkeypatch,"kuznitsa.analytics.controls",RuleControls=RuleControls)
    with TestClient(create_app(cfg=cfg)) as api:
        assert api.get("/").json()=="витрина" and api.get("/api/admin/inspect").json() is True
    called=[]
    def run(args,cfg):
        called.append(args.cmd)
        return args.cmd=="report"
    add_module(monkeypatch,"kuznitsa.analytics.cli",register=lambda sub:sub.add_parser("report"),run=run)
    assert cli.main(["report"])==0 and called==["report"]


def test_plugins_absent_and_robots(cfg,monkeypatch,capsys):
    for name in ("kuznitsa.api.admin","kuznitsa.pages","kuznitsa.analytics.controls","kuznitsa.analytics.cli"):
        monkeypatch.setitem(sys.modules,name,None)
    with TestClient(create_app(cfg=cfg)) as api:
        assert api.get("/").status_code==200
        assert "naive" in api.get("/api/meta").json()["modes"]
        for path in ["/robots.txt","/missing","/api/search?q=shield&mode=naive"]:
            r=api.get(path)
            assert r.headers["X-Robots-Tag"]=="noindex, nofollow"
        assert "Disallow: /" in api.get("/robots.txt").text
        assert r.json()["engine"]=="naive"
    monkeypatch.setattr(cli,"Config",lambda:cfg)
    assert cli.main(["search","shield","--mode","naive"])==0
    assert '"engine": "naive"' in capsys.readouterr().out
