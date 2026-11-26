"""Пользовательские формулировки контроля 30.3, точная первая карточка."""
import json
from pathlib import Path

import pytest
from kuznitsa.evaluation import cards_from
from kuznitsa.schema import Request
from test_m3b import store

GROUPS=json.loads((Path(__file__).parent/"fixtures/m3e_phrasings.json").read_text())
CASES=[]
for group in GROUPS:
    for query in group["queries"]:
        edition=group.get("editions",{}).get(query)
        CASES.append(pytest.param(query,[edition] if edition else group["ids"],id=query))


@pytest.mark.parametrize("mode",["fast","smart"])
@pytest.mark.parametrize("query,expected",CASES)
def test_first_card_after_rephrasing(store,mode,query,expected):
    result=store[0].search(Request(q=query,mode=mode,source="eval"))
    assert result["understood"]["intent"]=="product",query
    cards=cards_from(result["blocks"])
    assert cards and cards[0]["card_id"] in expected, (query,[c["title"] for c in cards[:2]])


@pytest.fixture(scope="module")
def departments(cfg,tmp_path_factory):
    from dataclasses import replace
    from kuznitsa.engine import Engine
    from kuznitsa.llm.jev import Disabled
    directory=tmp_path_factory.mktemp("departments")
    rows=[]
    def offer(cid,title,section,label,vendor,metric="device",pop=.5,upper=None,suffix=""):
        rows.append(dict(group_id=cid,offer_id=cid+suffix,family_id=cid,name=title+suffix,family_name=title,
                         domain="software",class_id=section,category_id=section,vendor=vendor,price=100,
                         popularity=pop,category_path=["Программы",label],lic=dict(metric=metric,qty_max=upper)))
    offer("agent","TickTime NTP Client","srv","Серверное ПО","Terra",pop=.99)
    offer("infra","Manager Suite","srv","Серверное ПО","Platform",pop=.9,upper=8)
    offer("infra","Manager Suite","srv","Серверное ПО","Platform",pop=.9,upper=90,suffix="-large")
    offer("mail","MailStation","srv","Серверное ПО","Nord")
    offer("cad","GearLab","cad","Программы для машиностроения","Gear",metric="user")
    offer("factory","FlowLine","auto","Системы автоматизации","Platform",metric="user")
    offer("copy","CopyForge","back","Программы резервного копирования","Forge")
    offer("storage","Storage Pro","back","Программы резервного копирования","Stor")
    offer("storage","Storage Pro","back","Программы резервного копирования","Stor","server",suffix="-srv")
    offer("studio","Edit Kit","video","Видеоредакторы","Blue Hill Corporation")
    offer("cam","CamWatch","cctv","ПО для видеонаблюдения","Lens")
    offer("cam","CamWatch","cctv","ПО для видеонаблюдения","Lens",suffix=" Server")
    offer("campc","DesktopCam","cctv","ПО для видеонаблюдения","Lab")
    offer("edu","DeskSuite 2024 для учебы","desk","Офисные пакеты","Desk")
    offer("biz","DeskSuite 2024 для бизнеса","desk","Офисные пакеты","Desk")
    offer("other","FrameKit","video","Видеоредакторы","Gear")
    (directory/"catalog.jsonl").write_text("\n".join(json.dumps(o) for o in rows))
    engine=Engine.open(replace(cfg,data=directory),llm=Disabled())
    try:
        yield lambda q: engine.search(Request(q=q,mode="fast"))
    finally:
        engine.close()


def test_broad_class_selects_quantity_inside_cards(departments):
    for q,category,first in [("серверное ПО на 37 узлов","srv","infra-large"),
                             ("система автоматизации на 11 пользователей","auto","factory"),
                             ("ПО для машиностроения на 12 мест","cad","cad")]:
        result=departments(q)
        block=result["blocks"][0]
        assert block["category_id"]==category and result["understood"]["intent"]=="category"
        item=block["items"][0]
        assert item["offer"]["offer_id"]==first
        assert item["calc"]["qty"]==result["understood"]["qty"]["value"]
        if category=="srv":
            assert block["total"]==3 and {c["card_id"] for c in block["items"]}>={"agent","mail","infra"}


def test_vendor_with_and_without_class_intersection(departments):
    present=departments("видеоредакторы Blue Hill")
    assert present["blocks"][0]["items"][0]["card_id"]=="studio"
    absent=departments("видеоредакторы Platform")
    assert absent["blocks"][0]["items"][0]["vendor"]["name"]=="Platform"
    assert "нет" in absent["understood"]["agent_note"] and absent["understood"]["intent"]=="category"


@pytest.mark.parametrize("q",["софт для резервного копирования на сервере","ПО для резервного копирования на сервер"])
def test_server_as_deployment_target(departments,q):
    r=departments(q)
    assert r["blocks"][0]["category_id"]=="back"
    first=r["blocks"][0]["items"][0]
    assert first["domain"]=="software" and first["offer"]["offer_id"]=="storage-srv"

def test_server_variant_from_offer_name(departments):
    result=departments("ПО для видеонаблюдения на сервер")
    first=result["blocks"][0]["items"][0]
    assert result["blocks"][0]["category_id"]=="cctv" and first["offer"]["offer_id"]=="cam Server"


def test_year_without_edition_prefers_business(departments):
    assert departments("DeskSuite 2024 года")["blocks"][0]["items"][0]["card_id"]=="biz"
    assert departments("DeskSuite 2024 для учебы")["blocks"][0]["items"][0]["card_id"]=="edu"
