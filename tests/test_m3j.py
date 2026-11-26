import json
from dataclasses import replace
from shutil import copytree

import pytest
import yaml

from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request
from kuznitsa.suggest.index import suggest


@pytest.fixture(scope="module")
def shop(cfg,tmp_path_factory,monkeypatch_module):
    data=tmp_path_factory.mktemp("editions")
    kb=copytree(cfg.kb,data/"kb")
    rows=[]
    def add(name,section,vendor="North",aud=None):
        rows.append(dict(offer_id=name,group_id=name,name=name,family_name=name,vendor=vendor,domain="software",
                         class_id=section,category_id=section,category_path=["ПО",section],price=800,lic={"audience":aud}))
    for name in ("Windows 11 Home","Windows 11 Pro","Windows 10 Pro","Windows 11 Enterprise"):
        add(name,"Windows 11: лицензии Home и Pro","Microsoft")
    for name in ("Office для дома и бизнеса 2024","Office Профессиональный 2021","Office Standard 2024"):
        add(name,"Офисные пакеты","Microsoft")
    for level in ("Plus","Standard","Premium"):
        add("Kaspersky "+level,"Домашние антивирусы","Kaspersky","home")
    for level in ("Professional","Education","Ultimate","Business","Server"):
        add("DraftLab "+level,"Проектирование")
    add("Remote Про","Услуги")
    add("Kaspersky Endpoint Security для бизнеса","Защита","Kaspersky","business")
    rules=[dict(id="home",when={"classes":["Windows 11: лицензии Home и Pro"],"families":["Windows 11"],
                                "query_words":["windows 11"],"audience":"home"},
                offer={"classes":["Домашние антивирусы"],"audience":"home"},reason="Защита для дома"),
           dict(id="corp",when={"classes":["Windows 11: лицензии Home и Pro"]},
                offer={"classes":["Защита"]},reason="Защита рабочих станций")]
    (kb/"upsell_r9.yaml").write_text(yaml.safe_dump(rules,allow_unicode=True))
    monkeypatch_module.setenv("KZ_KB_DIR",str(kb))
    (data/"catalog.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    e=Engine.open(replace(cfg,data=data,kb=kb),llm=Disabled())
    yield e
    e.close()


@pytest.fixture(scope="module")
def monkeypatch_module():
    with pytest.MonkeyPatch.context() as patch:
        yield patch


@pytest.mark.parametrize("q,title",[
    ("винда хоум","Windows 11 Home"),("виндовс хом 11","Windows 11 Home"),("винда 10 про","Windows 10 Pro"),
    ("винда проф","Windows 11 Pro"),("винда корпоративная","Windows 11 Enterprise"),
    ("винда энтерпрайз","Windows 11 Enterprise"),("офис хоум энд бизнес","Office для дома и бизнеса 2024"),
    ("офис про 2021","Office Профессиональный 2021"),("офис стандард","Office Standard 2024"),
    ("касперский плюс","Kaspersky Plus"),("касперский стандарт","Kaspersky Standard"),
    ("касперский премиум","Kaspersky Premium"),("DraftLab профессионал","DraftLab Professional"),
    ("DraftLab профешнл","DraftLab Professional"),("DraftLab эдьюкейшн","DraftLab Education"),
    ("DraftLab ультимейт","DraftLab Ultimate"),("DraftLab бизнес","DraftLab Business"),("DraftLab сервер","DraftLab Server")])
def test_same_edition_in_search_and_suggest(shop,q,title):
    for mode in ("fast","smart"):
        r=shop.search(Request(q=q,mode=mode))
        assert r["understood"]["intent"]=="product"
        assert r["blocks"][0]["items"][0]["title"]==title
    groups={g["type"]:g["items"] for g in suggest(shop,q)["groups"]}
    assert groups["products"][0]["text"]==title
    assert groups["categories"][0]["text"]==shop.catalog.feed.classes[shop.catalog.feed.card_sections[title]]


def test_release_fallback_stays_in_class(shop):
    r=shop.search(Request(q="виндовс хоум 12",mode="fast"))
    assert r["understood"]["intent"]=="product" and "Версия 12" in r["understood"]["agent_note"]
    items=[c for c in r["blocks"][0]["items"] if c.get("kind")!="upsell"]
    assert items[0]["title"]=="Windows 11 Home" and all(c["title"].startswith("Windows") for c in items)


@pytest.mark.parametrize("q,audience",[("виндовс хоум","home"),("винда домашняя","home"),("винда про","business")])
def test_recommended_edition_audience(shop,q,audience):
    r=shop.search(Request(q=q,mode="fast"))
    assert r["understood"]["filters"]["audience"]==audience
    cards=[x["card"] for b in r["blocks"] if b["type"]=="crosssell" for x in b["items"]]
    cards.extend(c for c in r["blocks"][0]["items"] if c.get("kind")=="upsell")
    assert cards and all(c["offer"]["audience"]==audience for c in cards)
    upsell=next(g for g in suggest(shop,q)["groups"] if g["type"]=="upsell")
    assert all(shop.catalog.cards[i["card_id"]].offers[0].lic.audience==audience for i in upsell["items"])


def test_standalone_level_and_hardware(shop):
    assert shop.catalog.feed.edition("сервер") is None
    assert shop.catalog.feed.edition("про") is None
    assert shop.catalog.feed.edition("неизвестная про") is None
    assert shop.search(Request(q="про",mode="fast"))["blocks"][0]["type"]=="clarify"

def test_home_suggestions_match_canonical_spelling(shop):
    def picks(query):
        return {g["type"]: [item["meta"] for item in g["items"]]
                for g in suggest(shop,query)["groups"] if g["type"] in {"products","categories","upsell"}}

    canonical = picks("windows home")
    assert set(canonical) == {"products", "categories", "upsell"}
    for query in ("винда хоум", "виндовс хоум", "винда хоум 11"):
        assert picks(query) == canonical
