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
    (root/"roles.yaml").write_text(yaml.safe_dump([dict(id="bookkeeper",title="Бухгалтер",
        aliases=["бухгалтер","бухгалтерия"],slots=[dict(category="endpoint_security",families=[],
        products=["Kaspersky Small Office Security"],note="Защита рабочего места")])],allow_unicode=True))
    (root/"hardware_hints_extra.yaml").write_text(yaml.safe_dump([dict(id="mobile_pc",hardware_class="laptop",
        hardware_feed_classes=[70824],trigger_words=["ноутбук"],prompt="Искали ПО для ноутбука?",
        software_classes=[650])],allow_unicode=True))
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
        return {i.get("rule_id") for b in feed.search(Request(q="astra linux",mode="fast"))["blocks"] for i in b.get("items",[])}
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

def test_variants_of_one_server(feed):
    items=feed.search(Request(q="сервер",mode="fast"))["blocks"][0]["items"]
    servers=[c for c in items if not c.get("fill") and c.get("kind")!="upsell"]
    assert len({c["title"] for c in servers})==len(servers)==2
    card=next(c for c in servers if "3470S2A" in c["title"])
    assert card["variants_count"]==3
    from kuznitsa.index.hardware import model_title
    first=feed.catalog.cards[card["card_id"]].offers[0]
    for tail in (" — комплектация Enterprise"," (цвет: серый)",", артикул X-001",", RAM 32 GB"," (64 ГБ ОЗУ)"):
        assert model_title(first.model_copy(update={"family_name":card["title"]+tail}))==card["title"]
    for old,canonical in feed.catalog.card_aliases.items():
        if canonical==card["card_id"]:
            assert feed.card(old)["card_id"]==canonical
    original_ids={o.offer_id for o in feed.catalog.cards[card["card_id"]].offers}
    assert original_ids=={v["offer_id"] for v in feed.card(card["card_id"])["variants"]}


def test_device_precedes_profession(feed):
    for mode in ("fast","smart"):
        result=feed.search(Request(q="ноутбук в бухгалтерию",mode=mode))
        products=result["blocks"][0]["items"]
        assert products[0]["domain"]=="hardware" and "Ноутбук" in products[0]["title"]
        assert any("Бухгалтер" in c["reason"] for c in products if c.get("kind")=="upsell")
        assert any("Бухгалтер" in chip["label"] for chip in result["understood"]["chips"])


def test_competitor_dependency(cfg,tmp_path):
    data=copytree(DATA,tmp_path/"store")
    root=copytree(cfg.kb,tmp_path/"kb")
    template=json.loads((data/"catalog.jsonl").read_text().splitlines()[0])
    def row(ident,title,vendor,category):
        return dict(template,offer_id=ident,family_name=title,name=title,vendor=vendor,vendor_id=vendor,
                    group_id=ident,family_id=ident,class_id=category,category_id=category)
    additions=[row("alpha","Alpha Suite","Alpha","suite"),row("beta","Beta Suite","Beta","suite"),
               row("specific","Shield for Alpha Suite","Shield","protection"),
               row("embedded","Shield Alpha Suite Connector","Shield","protection"),
               row("generic","Universal Shield","Shield","other_protection")]
    with (data/"catalog.jsonl").open("a") as out:
        for r in additions:print(json.dumps(r),file=out)
    rules=[dict(id=k,when=dict(classes=["suite"]),offer=dict(families=[k]),
                reason="Защита",weight=.9) for k in ("specific","embedded","generic")]
    (root/"upsell_r9.yaml").write_text(yaml.safe_dump(rules))
    with pytest.MonkeyPatch.context() as env:
        env.setenv("KZ_KB_DIR",str(root))
        e=Engine.open(replace(cfg,data=data,kb=root))
        try:
            picks=e.catalog.feed.recommend.picks
            assert {c for c,r in picks(e.journal,"beta suite",["beta"],3)}=={"generic"}
            assert {c for c,r in picks(e.journal,"alpha suite",["alpha"],3)}=={"generic","specific","embedded"}
        finally:e.close()
