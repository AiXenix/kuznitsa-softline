"""Приёмка M3b на строках real/v1. KZ_TEST_REAL_FEED включает полное дерево."""
import json
import os
from dataclasses import replace
from pathlib import Path
from shutil import copytree

import pytest
import yaml
from fastapi.testclient import TestClient
from kuznitsa.app import create_app
from kuznitsa.config import Config
from kuznitsa.engine import Engine
from kuznitsa.evaluation import cards_from
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request

FIXTURES=Path(__file__).parent/"fixtures"


@pytest.fixture(scope="module")
def store(cfg,tmp_path_factory):
    data=tmp_path_factory.mktemp("quality")
    snapshot=os.getenv("KZ_TEST_REAL_FEED")
    if snapshot:
        for name in ("catalog.jsonl","feed_categories.json","feed_classes.json","kb_auto.yaml"):
            (data/name).symlink_to(Path(snapshot).resolve()/name)
        conf=Config(data=data)
    else:
        excerpt=FIXTURES/"softline_feed"
        rows=[json.loads(s) for file in (excerpt/"catalog.jsonl",FIXTURES/"m3b_feed.jsonl")
              for s in file.read_text().splitlines()]
        tree=json.loads((excerpt/"feed_categories.json").read_text())
        for row in rows:
            if row.get("group_id"):
                tree.setdefault(row["group_id"],[row["family_name"],row["class_id"]])
        (data/"feed_categories.json").write_text(json.dumps(tree))
        (data/"catalog.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        kb=copytree(cfg.kb,data/"kb")
        (kb/"vendors_sample.yaml").write_text(yaml.safe_dump([dict(id="labs",name="Лаборатория Касперского",
            aliases=["касперский","kaspersky"])]))
        (kb/"families/crypto.yaml").write_text(yaml.safe_dump([dict(id="crypto_csp",name="КриптоПро CSP",
            category="office_suite",vendor="east",popularity=5)],allow_unicode=True))
        rules=[dict(id="os_"+k,when={"families":["Astra Linux Special Edition"]},offer={"classes":[k]},
                    reason="Совместимое ПО",weight=.8) for k in ("650","1033","1145","687")]
        (kb/"upsell_r9.yaml").write_text(yaml.safe_dump(rules))
        conf=replace(cfg,kb=kb,data=data)
    e=Engine.open(conf,llm=Disabled())
    with pytest.MonkeyPatch.context() as env:
        env.setenv("KZ_KB_DIR",str(conf.kb))
        with TestClient(create_app(engine=e)) as http:
            yield e,http
    e.close()


def search(store,q):
    return store[0].search(Request(q=q,mode="fast",source="eval"))


def suggest(store,q):
    result=store[1].get("/api/suggest",params={"q":q})
    assert result.status_code==200
    return {g["type"]:g["items"] for g in result.json()["groups"]}


@pytest.mark.parametrize("q,title",[
    ("майкрософт офис для дома и бизнеса","office"),("лицензия энидеск","anydesk"),
    ("касперски смол офис секьюрити","small office security"),("астра спешл","astra linux")])
def test_spoken_brand(store,q,title):
    result=search(store,q)
    assert title in cards_from(result["blocks"])[0]["title"].lower()
    assert result["blocks"][0]["type"]=="products"


@pytest.mark.parametrize("q,expected",[
    ("чем можно восстановить документы","5922"),("как перекодировать видеофайл","224"),
    ("перевести текст договора","4177"),("нарисовать диаграмму отдела","20725"),
    ("программы для очистки диска","5593")])
def test_task_section(store,q,expected):
    r=search(store,q)
    assert r["blocks"][0]["category_id"]==expected
    group=suggest(store,q)
    assert group["categories"][0]["meta"]==expected
    assert group["products"][0]["card_id"]==cards_from(r["blocks"])[0]["card_id"]


def test_home_vendor_quantity_and_renewal(store):
    assert search(store,"антивирусы для семьи")["blocks"][0]["category_id"]=="3775"
    r=search(store,"антивирусы касперского")
    core=[c for c in r["blocks"][0]["items"] if not c.get("kind") and not c.get("fill")]
    assert r["understood"]["filters"]["vendor"] and core
    assert all("касперск" in c["vendor"]["name"].lower() or "kaspersky" in c["vendor"]["name"].lower() for c in core)
    r=search(store,"антивирусы на 7 пользователей")
    assert r["understood"]["qty"]=={"value":7,"metric":"user"}
    offer=cards_from(r["blocks"])[0]["offer"]
    assert offer["metric"]=="user" and (offer["qty_min"] or 1)<=7<=(offer["qty_max"] or 7)
    r=search(store,"продлить kaspersky small office security")
    assert r["understood"]["intent"]=="renewal"
    assert cards_from(r["blocks"])[0]["offer"]["action"]=="renewal"


def test_no_generic_word_as_product(store):
    result=search(store,"CalderaNimble Neo")
    assert result["blocks"][0]["type"]=="not_in_catalog"
    assert len(cards_from(result["blocks"]))>=4
    result=search(store,"qxwzzzt")
    assert any(b["type"]=="clarify" and len(b["options"]) in (2,3) for b in result["blocks"])
    assert len(cards_from(result["blocks"]))>=4


def test_prefix_categories_and_fill(store):
    e,_=store
    for q in ("крипто","астра"):
        groups=suggest(store,q)
        products=groups["products"]
        if q=="крипто":
            titles=[p["text"].lower() for p in products]
            assert len(titles)==4 and any("криптоарм" in t for t in titles)
            assert any("криптопро csp" in t for t in titles)
        found={e.catalog.feed.card_sections[p["card_id"]] for p in products}
        assert all(c["meta"] in found for c in groups["categories"])
    for q in ("крипто про csp 5.0","макс патрол"):
        items=cards_from(search(store,q)["blocks"])
        assert len(items)>=4
        section=e.catalog.feed.card_sections[items[0]["card_id"]]
        assert all(e.catalog.feed.card_sections[c["card_id"]]==section for c in items if c.get("fill"))


def test_recognized_hardware_and_question(store):
    e,_=store
    for q,k in (("комп","70187"),("принтак","93995"),("свитч","85741"),("ноут","70824")):
        r=search(store,q)
        assert r["blocks"][0]["category_id"]==k
        groups=suggest(store,q)
        assert "corrections" not in groups and groups["categories"][0]["meta"]==k
    groups=suggest(store,"что от вирусов")
    assert groups["products"] and groups["categories"][0]["meta"]=="650"
    for item in groups["products"]:
        assert e.catalog.feed.card_sections[item["card_id"]]=="650"


def test_new_slang_and_audience_rules(cfg,tmp_path,monkeypatch):
    """Загрузка новых полей до появления файлов K и правки магазина поверх YAML."""
    from kuznitsa.analytics.upsell_rules import change,validate
    data=copytree(FIXTURES/"softline_feed",tmp_path/"feed")
    with (data/"catalog.jsonl").open("a") as out:
        out.write((FIXTURES/"m3b_feed.jsonl").read_text())
    kb=copytree(cfg.kb,tmp_path/"kb")
    slang=[dict(term="смол секьюр",type="slang",maps_to={"text":"small office security"}),
           dict(term="твердотельник",type="slang",maps_to={"attr":"hardware_class","value":"ssd"})]
    (kb/"slang_r10.yaml").write_text(yaml.safe_dump(slang,allow_unicode=True))
    def rule(name,when,offer):
        return dict(id=name,when=when,offer=offer,reason="Совместимо по аудитории",weight=.9)
    rules=[rule("for_home",{"classes":["3775"],"audience":"home"},{"classes":["3775"],"audience":"home"}),
           rule("for_business",{"classes":["3775"],"audience":"business"},{"classes":["650"]}),
           rule("wrong_target",{"classes":["3775"]},{"classes":["650"],"audience":"home"}),
           rule("unrelated",{"query_words":["антивирус"]},{"classes":["650"]}),
           rule("unavailable",{"classes":["3775"]},{"classes":["650"],"vendors":["Нет такого вендора"]}),
           rule("legacy",{"classes":["3775"]},{"classes":["1033"]})]
    (kb/"upsell_r9.yaml").write_text(yaml.safe_dump(rules))
    monkeypatch.setenv("KZ_KB_DIR",str(kb))
    e=Engine.open(replace(cfg,kb=kb,data=data),llm=Disabled())
    try:
        assert cards_from(search((e,None),"kaspersky смол секьюр")["blocks"])[0]["title"]=="Kaspersky Small Office Security"
        assert search((e,None),"твердотельник")["blocks"][0]["category_id"]=="79574"
        index=e.catalog.feed
        ids=[index.groups["3775"][0]]
        def picks(q):
            return {r["id"]:cid for cid,r in index.recommend.picks(e.journal,q,ids,8)}
        match=picks("антивирус")
        assert set(match)=={"for_home","legacy"}
        assert index.recommend.target_offer(match["for_home"],"home").lic.audience=="home"
        assert set(picks("для организации"))=={"for_business","legacy"}
        assert validate(rules[0])["when"]["audience"]=="home"
        with pytest.raises(ValueError):
            validate(dict(rules[0],when={"classes":["3775"],"audience":"unknown"}))
        change(e.journal,"update",{"enabled":False},"for_home","проверка")
        assert set(picks("антивирус"))=={"legacy"}
    finally:
        e.close()


@pytest.mark.parametrize("q,product",[
    ("SQL Server для учёта поставок","sql server"),("астра se для внутреннего документооборота","astra linux"),
    ("фотошоп под обработку снимков","photoshop"),("лайтрум для фотографа студии","lightroom"),
    ("премьер для монтажа видео","premiere"),("MS SQL под базу договоров","sql server")])
def test_product_precedes_purpose(store,q,product):
    for mode in ("smart","fast"):
        r=store[0].search(Request(q=q,mode=mode,source="eval"))
        assert r["understood"]["intent"]=="product"
        assert product in cards_from(r["blocks"])[0]["title"].lower()
        assert r["cost"]["llm_calls"]==0
        core=[c for c in cards_from(r["blocks"]) if not c.get("fill") and c.get("kind")!="upsell"]
        assert all(product in c["title"].lower() for c in core)


def test_tiles_after_fill(store):
    r=search(store,"astra linux")
    items=r["blocks"][0]["items"]
    cross=next(b for b in r["blocks"] if b["type"]=="crosssell")
    core=[c for c in items if c.get("kind")!="upsell"]
    tiles=[c for c in items if c.get("kind")=="upsell"]
    assert len(core)>=4 and any(c.get("fill") for c in core)
    assert 1<=len(tiles)<=len(core)//2 and items[0] is core[0]
    assert cross["items"] and all(c["rule_id"] for c in tiles)
    refs=[c["card_id"] for c in items]+[i["card"]["card_id"] for i in cross["items"]]
    assert len(refs)==len(set(refs))


def test_fixed_node_capacity(store):
    e=store[0]
    r=search(store,"MIS Utilities Network Asset Tracker на 23 узла")
    first=cards_from(r["blocks"])[0]
    assert first["card_id"]=="26966" and first["offer"]["pack"]>=23
    assert r["understood"]["qty"]=={"value":23,"metric":"device"}
    source=e.catalog.offers_by_id[first["offer"]["offer_id"]]
    assert source.lic.qty_min==1 and "К-во узлов" in source.description


def test_recommendation_scope(store):
    for q in ("1с","астра","офис"):
        r=search(store,q)
        blocks=r["blocks"]
        shown={i["title"] for i in cards_from(blocks) if i.get("kind")=="upsell"}
        shown.update(i["card"]["title"] for b in blocks if b["type"]=="crosssell" for i in b["items"])
        shown.update(i["text"] for i in suggest(store,q).get("upsell",[]))
        if q=="офис":assert all("датаплат.сервер" not in t.lower() for t in shown)
        if q=="1с":assert all("globalsign" not in t.lower() and "zvirt" not in t.lower() for t in shown)
        if q=="астра":assert all("инфраменеджер" not in t.lower() for t in shown)
