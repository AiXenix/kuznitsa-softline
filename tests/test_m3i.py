import json
from dataclasses import replace
from shutil import copytree

import pytest

from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request
from kuznitsa.evaluation import cards_from


@pytest.fixture(scope="module")
def store(cfg,tmp_path_factory):
    root=tmp_path_factory.mktemp("m3i")
    kb=copytree(cfg.kb,root/"kb")
    rows=[]
    def add(name,department,section,vendor="Alba",registry=False,audience="business"):
        rows.append(dict(name=name,offer_id=name,group_id=name,family_name=name,class_id=section,category_id=section,
                     domain="software",category_path=[department,section],vendor=vendor,price=900,
                     registry=registry,lic={"audience":audience}))
    add("OrbitDesk","Рабочие системы","Коробочные лицензии")
    for n in range(3):
        add(f"Север {n}","Рабочие системы","Платформы (Импортозамещение)")
    add("Студент","Рабочие системы","Платформы (Импортозамещение)",audience="edu")
    add("Берег","Рабочие системы","Линейки ОС",registry=True)
    rows.append({**rows[-1],"offer_id":"Берег учебная","registry":False,"lic":{"audience":"edu"}})
    add("Иностранная ОС","Рабочие системы","Линейки ОС")
    add("FrostCut","Монтаж видео","Видеоредакторы",vendor="Frost")
    add("Доступ","Связь","Доступ (Импортозамещение)",registry=True)
    (root/"catalog.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    engine=Engine.open(replace(cfg,data=root,kb=kb),llm=Disabled())
    yield engine
    engine.close()


@pytest.mark.parametrize("mode",["fast","smart"])
def test_department_ladder_without_kb_row(store,mode):
    r=store.search(Request(q="российский аналог OrbitDesk",mode=mode,filters={"audience":"business"}))
    block=next(b for b in r["blocks"] if b["type"]=="analogs")
    assert {
        x["card"]["title"] for x in block["items"][:3]}=={"Север 0","Север 1","Север 2"}
    assert block["items"][3]["card"]["title"]=="Берег"
    assert all(x["card"]["offer"]["audience"]=="business" for x in block["items"])
    assert block["title"]=="Российские аналоги OrbitDesk"
    assert all(x["reason"]==x["card"]["label"] and x["reason"].startswith("Российский аналог OrbitDesk: ") for x in block["items"])
    assert block["category_id"]=="Платформы (Импортозамещение)"


@pytest.mark.parametrize("q",["видеоредакторы Frost","CoralNest Premium","отечественная замена FrostCut"])
def test_sparse_results_have_cards_or_section_choice(store,q):
    r=store.search(Request(q=q,mode="fast"))
    blocks=r["blocks"]
    assert all(b["items"] for b in blocks if b["type"] in {"products","analogs","services","promo","crosssell"})
    assert len(cards_from(blocks))>=4 or any(b["type"]=="clarify" and b["options"] for b in blocks)
    if q.startswith("отечественная"):
        assert not cards_from(blocks)
        assert next(b for b in blocks if b["type"]=="clarify")["options"]


@pytest.mark.parametrize("kind,field",[("products","items"),("promo","items"),("services","items"),
    ("analogs","items"),("compare","columns"),("crosssell","items"),("kit","slots"),("spec","lines")])
def test_empty_product_blocks_are_removed(store,kind,field):
    from kuznitsa.plans.response_guard import guard
    result=dict(blocks=[{"type":kind,field:[]}],understood=dict(intent="analog",filters={}))
    guard(store,Request(q="OrbitDesk"),result)
    assert [b["type"] for b in result["blocks"]]==["clarify"] and result["blocks"][0]["options"]


def test_registry_and_audience_hold_during_expansion(store):
    r=store.search(Request(q="отечественный аналог OrbitDesk",mode="fast",
                           filters={"registry":True,"audience":"business"}))
    assert [c["title"] for c in cards_from(r["blocks"])]==["Берег"]
    edu=store.search(Request(q="российский аналог OrbitDesk",mode="fast",filters={"audience":"edu"}))
    assert [c["title"] for c in cards_from(edu["blocks"])]==["Студент"]
    assert any(b["type"]=="clarify" and b["options"] for b in r["blocks"])
