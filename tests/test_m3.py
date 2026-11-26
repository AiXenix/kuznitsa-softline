import json
from dataclasses import replace
from pathlib import Path
from shutil import copytree
import httpx
import pytest
import yaml

from kuznitsa.engine import Engine
from kuznitsa.schema import Request
from kuznitsa.llm.jev import Jev
from kuznitsa.suggest.index import suggest

DATA=Path(__file__).parent/"fixtures/softline_feed"


@pytest.fixture(scope="module")
def feed(cfg,tmp_path_factory):
    data=copytree(DATA,tmp_path_factory.mktemp("feed")/"snapshot")
    root=copytree(cfg.kb,data/"kb")
    (root/"families/backup.yaml").write_text(yaml.safe_dump([dict(id="backup",name="Кибер Бэкап",vendor="east",category="office_suite")],allow_unicode=True))
    (root/"analogs.yaml").write_text(yaml.safe_dump([dict(product="Retired Backup",family="old",russian_analogs=[dict(family="backup")])]))
    rule=dict(id="os_protection",when=dict(families=["Astra Linux Special Edition"]),offer=dict(classes=["650"]),
              weight=.9,reason="Защита рабочих станций")
    companions=[rule, dict(rule,id="os_domain",offer=dict(families=["ALD Pro"]),weight=.85),
                dict(rule,id="os_copy",offer=dict(classes=["1033"]),weight=.8)]
    (root/"upsell_r9.yaml").write_text(yaml.safe_dump(companions))
    (root/"hardware_hints.yaml").write_text(yaml.safe_dump([dict(id="rack",hardware_class="server",
        hardware_feed_classes=[86563],trigger_words=["сервер"],prompt="Искали ПО для сервера?",
        software_classes=[650])],allow_unicode=True))
    (root/"slang_device.yaml").write_text(yaml.safe_dump([dict(term="стоечник",type="slang",
        maps_to=dict(attr="hardware_class",value="server"))],allow_unicode=True))
    def classify(request):
        criteria=json.loads(request.content)["questions"]["section"]["criteria"]
        key=next(k for k,title in criteria.items() if "Антивирусы для организаций" in title)
        return httpx.Response(200,json={"answers":{"section":{"choice":key,"probabilities":{key:.91}}},"usage":{"cost":.0001}})
    with pytest.MonkeyPatch.context() as env:
        env.setenv("KZ_KB_DIR",str(root))
        engine=Engine.open(replace(cfg,data=data,kb=root),llm=Jev(transport=httpx.MockTransport(classify)))
        yield engine
        engine.close()


@pytest.mark.parametrize("q,expected",[
    ("сервер","сервер"),("антивирь",""),("винда","windows"),("мдаемон","mdaemon"),("astra linux","astra linux"),
    ("Microsoft Office для дома и бизнеса","2024"),("kaspersky small office security","small office"),
    ("крипто про csp 5.0","csp"),("anydesk","anydesk"),("кибер бэкап","кибер бэкап"),
    ("сканер-вс","сканер-вс"),("мтс","мтс линк"),("max patrol","maxpatrol"),("365","для семьи")])
def test_real_groups(feed,q,expected):
    for mode in ("fast","smart"):
        result=feed.search(Request(q=q,mode=mode))
        block=result["blocks"][0]
        items=block["items"]
        assert block["type"]=="products" and expected in items[0]["title"].lower()
        assert len({c["card_id"] for c in items})>=4
        if q=="сервер":
            assert items[0]["domain"]=="hardware" and "ПО для" in result["understood"]["chips"][0]["label"]
        if q=="кибер бэкап":assert "резервного копирования" in block["title"].lower()
        if q=="anydesk":assert items[1]["fill"]
        if q=="astra linux":
            cross=next(b for b in result["blocks"] if b["type"]=="crosssell")
            all_rules={i["rule_id"] for i in cross["items"]} | {i["rule_id"] for i in items if i.get("kind")=="upsell"}
            assert {"os_protection","os_copy","os_domain"}<=all_rules
        if q=="антивирь":assert items[0]["domain"]=="software" and "Антивирусы" in feed.catalog.cards[items[0]["card_id"]].offers[0].category_path[0]


def test_question_and_suggestions(feed):
    for mode in ("fast","smart"):
        r=feed.search(Request(q="Что использовать против вирусов?",mode=mode))
        assert "антивирус" in r["blocks"][0]["title"].lower()
        assert r["cost"]["llm_calls"]==int(mode=="smart")
    groups={g["type"]:g["items"] for g in suggest(feed,"astra linux")["groups"]}
    assert 0<len(groups["products"])<=4 and "picture" in groups["products"][0]
    assert groups["upsell"][0]["rule_id"]=="os_protection"


def test_merch_slots_and_feed_prices(feed):
    from kuznitsa.rank.upsell import interleave
    for n in range(1,10):
        items=list(range(n))
        interleave("example",items,["extra"]*10)
        assert items[0]==0 and items.count("extra")==n//2
        assert all((a,b)!=("extra","extra") for a,b in zip(items,items[1:]))
    from kuznitsa.plans.feed import decorate
    for price,old,available,expected in [(100,125,True,["Акция −20 %"]),(None,100,False,["Цена по запросу","Под заказ"]),(50,50,True,[])]:
        record=next(iter(feed.catalog.offers_by_id.values())).model_copy(update=dict(price=price,oldprice=old,available=available))
        card=dict(offer={},badges=[])
        decorate(card,record)
        assert [b["label"] for b in card["badges"]]==expected


def test_missing_line_and_outside_catalog(feed):
    missing=feed.search(Request(q="Retired Backup",mode="fast"))
    assert missing["blocks"][0]["type"]=="not_in_catalog"
    assert "Кибер Бэкап" in missing["blocks"][1]["items"][0]["card"]["title"]
    noise=feed.search(Request(q="зимняя резина r16",mode="fast"))
    popular=next(b for b in noise["blocks"] if b.get("title")=="Популярное")
    assert len(popular["items"])==4 and all(c["fill"] for c in popular["items"])


def test_feed_http_card_and_suggest(feed):
    from fastapi.testclient import TestClient
    from kuznitsa.app import create_app
    with TestClient(create_app(engine=feed)) as client:
        data=client.get("/api/suggest",params={"q":"astra linux"}).json()
        product=next(g["items"][0] for g in data["groups"] if g["type"]=="products")
        card=client.get("/api/card/"+product["card_id"]).json()
        assert card["domain"]=="software" and card["picture"]==product["picture"]
        assert card["variants_count"]>=1

def test_hardware_slang_and_software_link(feed):
    result=feed.search(Request(q="стоечник",mode="fast"))
    assert result["blocks"][0]["items"][0]["domain"]=="hardware"
    groups={g["type"]:g["items"] for g in suggest(feed,"стоечник")["groups"]}
    assert groups["products"][0]["card_id"]==result["blocks"][0]["items"][0]["card_id"]
    assert groups["categories"][0]["meta"]=="86563"
    chip=result["understood"]["chips"][0]
    software=feed.search(Request(**chip["apply"],mode="fast"))
    assert software["blocks"][0]["category_id"]=="650"
    assert software["blocks"][0]["items"][0]["domain"]=="software"


def test_live_upsell_rule_changes(feed,monkeypatch):
    from types import SimpleNamespace
    rules=feed.catalog.feed.recommend
    rule=dict(rules.base[0],id="store_rule",reason="Защита по правилу магазина")
    state=[1,[rule]]
    monkeypatch.setattr(rules,"provider",SimpleNamespace(active_rules=lambda journal:state))
    monkeypatch.setattr(rules,"compiled",rules.compiled)
    monkeypatch.setattr(rules,"version",None)
    def items():
        return {i.get("rule_id") for b in feed.search(Request(q="astra linux",mode="fast"))["blocks"] for i in b["items"]}
    assert "store_rule" in items()
    state[:]=[2,[]]
    assert "store_rule" not in items()


@pytest.mark.parametrize("q,prefix",[("Windows server","microsoft windows server"),("сервер 1с","postgres pro")])
def test_server_software(feed,q,prefix):
    for mode in ("fast","smart"):
        response=feed.search(Request(q=q,mode=mode))
        first=response["blocks"][0]["items"][0]
        assert first["domain"]=="software" and prefix in first["title"].casefold()
        assert not any(c["key"]=="domain" for c in response["understood"]["chips"])
