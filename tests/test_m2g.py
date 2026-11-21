import json
from dataclasses import replace

import pytest

from kuznitsa.engine import Engine
from kuznitsa.evaluation import cards_from
from kuznitsa.schema import Request


def snapshot(path):
    rows=[]
    for i,(family,section,desc) in enumerate([
        ("Atlas Cutter","Раскрой материалов","Оптимизация расхода древесины при нарезке заготовок"),
        ("Точная Съёмка","Обработка фотографий","Сшивание фотографий в круговые панорамы"),
        ("Личный Архив","Электронные записи","Заметки, списки и личный дневник"),
        ("Orbis Queue","Регистрация посетителей","Управление электронной очередью и талонами")]):
        for action in ("new","renewal"):
            rows.append(dict(offer_id=f"{i}-{action}",source_id=f"ext-{i}-{action}",vendor="Норд",vendor_id="n",
                family_name=family,family_id=f"f{i}",name=f"{family} Базовая {action}",edition="base",category_id=f"c{i}",
                category_path=["ПО",section],description=desc,price=1200,domestic=i!=2,
                attrs=dict(series=family,edition="base",operation=action,prices={"retail":1200,"partner":700,"project":800}),
                lic=dict(action=action,audience="business",metric="user")))
    (path/"catalog.jsonl").write_text("\n".join(json.dumps(x,ensure_ascii=False) for x in rows))


@pytest.fixture
def shop(cfg,tmp_path):
    snapshot(tmp_path)
    e=Engine.open(replace(cfg,data=tmp_path))
    yield e
    e.close()


def response(e,q,mode="fast"):
    return e.search(Request(q=q,mode=mode,source="eval"))


CASES=["оптимизировать расход древесины","photo stitching software","российская альтернатива для ArborMaster",
       "njxyfz c]tvrf","Какая информация нужна для продления Atlas Cutter?","Orbis Queue ещё на год по действующей подписке",
       "Atlas Cutter для партнёра до 900 рублей","Точная Съёмка 9","Atlas Cutter; Базовая; Новая лицензия; партия 2 места",
       "электронные записи маме"]


@pytest.mark.parametrize("q,amount",[
    ("Atlas Cutter по проектной цене до 950 рублей",800),
    ("Atlas Cutter для партнёра до 900 рублей",700),
    ("Atlas Cutter в розницу до 1300 рублей",1200),
    ("Atlas Cutter для госзаказчика до 1400 рублей",1200)])
def test_price(shop,q,amount):
    r=response(shop,q)
    c=cards_from(r["blocks"])[0]
    assert c["offer"]["price"]==c["calc"]["unit_price"]==amount
    if "госзаказчика" in q:assert any("Использована розничная" in n for n in r["notes"])


def test_imported_section_budget_by_price_type(cfg, tmp_path):
    from shutil import copytree

    kb = copytree(cfg.kb, tmp_path / "kb")
    (kb / "slang_budget.yaml").write_text(
        "- {term: госзаказчика, type: slang, maps_to: {attr: audience, value: gov}}\n"
    )
    section = "Раскрой материалов"
    tariffs = {
        "Atlas": {"retail": 800, "project": 440, "gov": 780, "partner": 600,
                  "wholesale": 390, "Цена проектная региональная": 620},
        "Prism": {"retail": 850, "project": 710, "gov": 450},
        "Forma": {"retail": 490, "project": 720},
    }
    offers = [
        {"offer_id": name, "source_id": name, "sku": "PX-" + name, "name": name, "family_id": name,
         "family_name": name, "category_id": "cutting", "category_path": ["ПО", section],
         "price": prices["retail"], "attrs": {"prices": prices},
         "lic": {"metric": "user", "action": "new", "audience": "business"}}
        for name, prices in tariffs.items()
    ]
    path = tmp_path / "catalog.jsonl"
    path.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in offers))
    engine = Engine.open(replace(cfg, data=tmp_path, kb=kb))
    try:
        for name, prices in tariffs.items():
            assert engine.catalog.offers_by_id[name].attrs["prices"] == prices
        for tariff, expected in [
            ("по проектной цене", {"Atlas": 440}),
            ("для госзаказчика", {"Prism": 450, "Forma": 490}),
        ]:
            result = response(engine, f"{section}, 4 места, {tariff} до 2 000 руб.")
            assert "audience" not in result["understood"]["filters"]
            cards = {card["offer"]["offer_id"]: card for card in cards_from(result["blocks"])}
            assert cards.keys() == expected.keys()
            for name, unit_price in expected.items():
                calc = cards[name]["calc"]
                assert (calc["qty"], calc["unit_price"], calc["total"]) == (4, unit_price, 4 * unit_price)
                fallback = any("Использована розничная" in why for why in cards[name]["score"]["why"])
                assert fallback == (name == "Forma")
            assert any("Использована розничная" in note for note in result["notes"]) == ("Forma" in cards)
        exact = response(engine, "PX-Atlas по проектной цене до 500 руб.")
        assert cards_from(exact["blocks"])[0]["offer"]["price"] == 440
    finally:
        engine.close()


@pytest.mark.parametrize("q,target",[("njxyfz съёмка","f1"),("Or bis Queue","f3"),("Точаня Съёмка","f1")])
def test_snapshot_repair(shop,q,target):
    r=response(shop,q)
    assert cards_from(r["blocks"])[0]["card_id"].startswith(target)
    assert r["query"]["corrections"]


def test_question_and_renewal(shop):
    answer=response(shop,"Какие сведения нужны для продления Orbis Queue?")
    assert answer["blocks"][0]["type"]=="answer" and cards_from(answer["blocks"])[0]["card_id"].startswith("f3")
    renewal=response(shop,"Atlas Cutter ещё один год по действующей подписке")
    assert renewal["understood"]["intent"]=="renewal" and cards_from(renewal["blocks"])[0]["offer"]["action"]=="renewal"


def test_generic_version(shop):
    r=response(shop,"Личный Архив 11")
    b=next(b for b in r["blocks"] if b["type"]=="analogs")
    assert any("11" in why for why in b["items"][0]["card"]["score"]["why"])


def test_supplier_fields(shop):
    for op in ("Новая лицензия","Продление"):
        r=response(shop,"Orbis Queue; Базовая; "+op+"; партия 3 места")
        line=r["blocks"][0]["lines"][0]
        assert line["qty"]==3 and line["card"]["offer"]["action"]==("new" if op.startswith("Новая") else "renewal")


def test_home_class(shop):
    r=response(shop,"электронные записи для дома")
    assert any(b["type"]=="products" and b["items"][0]["category"]["id"]=="c2" for b in r["blocks"])
    assert any("домашн" in n for n in r["notes"]) and not any(b["type"]=="not_in_catalog" for b in r["blocks"])


def test_section_resolution(shop,monkeypatch):
    from unittest.mock import Mock
    decisions=Mock()
    decisions.decide_before.return_value=({"section":{"choice":"c0","probabilities":{"c0":.83}}},
        dict(kind="intent",ok=True,cached=False,sent=1,usd=.0001,tokens_in=2,tokens_out=2,ms=1))
    shop.decisions=decisions
    monkeypatch.setattr(shop.catalog.sections,"candidates",lambda q:[("c0",.53),("c1",.52)])
    fast=response(shop,"российская альтернатива для ArborMaster")
    assert fast["blocks"][0]["type"]=="clarify" and len(fast["blocks"][0]["options"])==2
    decisions.decide_before.assert_not_called()
    smart=response(shop,"российская альтернатива для ArborMaster","smart")
    assert smart["understood"]["intent"]=="analog" and "умный режим" in smart["understood"]["agent_note"]
    assert cards_from(smart["blocks"])[0]["category"]["id"]=="c0"
    assert set(decisions.decide_before.call_args.args[-1]["section"]["criteria"])=={"c0","c1","none"}
    monkeypatch.setattr(shop.catalog.sections,"candidates",lambda q:[("c0",.73),("c1",.45)])
    r=response(shop,"оптимизировать раскрой фанеры")
    assert cards_from(r["blocks"])[0]["category"]["id"]=="c0" and "Похоже" in r["understood"]["agent_note"]
    without=shop.search(Request(q="оптимизировать раскрой фанеры",ignore=["category"]))
    assert all(s["step"]!="section" for s in without["trace"])


def test_reopen_day_rebuilds_spelling(cfg,tmp_path):
    from kuznitsa.ingest.day import day
    incoming=tmp_path/"incoming"
    incoming.mkdir()
    (incoming/"offers.csv").write_text("brand;sku;name;series;category;price\nСевер;IN-0008;Prism Binder;Prism Binder;ПО > Переплёт;500\n")
    out=tmp_path/"day"
    day(incoming,cfg,out,ai="off",n=1)
    e=Engine.open(replace(cfg,data=out))
    try:
        r=response(e,"Pr ism Binder")
        assert cards_from(r["blocks"])[0]["offer"]["sku"]=="IN-0008" and r["query"]["corrections"]
    finally:e.close()


def test_sections_cache_and_threshold(cfg,tmp_path):
    import httpx
    from kuznitsa.llm.jev import Jev
    snapshot(tmp_path)
    sent=[]
    def reply(request):
        payload=json.loads(request.content)
        sent.append(payload)
        assert set(payload["questions"])=={"section"}
        return httpx.Response(200,json={"answers":{"section":{"choice":"c0","probabilities":{"c0":.54}}},
                                        "usage":{"cost":.00001}})
    e=Engine.open(replace(cfg,data=tmp_path),llm=Jev(transport=httpx.MockTransport(reply)))
    try:
        for cached in (0,1):
            r=e.search(Request(q="чем заменить Norcrest",mode="smart"))
            assert r["blocks"][0]["type"]=="clarify"
            step=next(s for s in r["trace"] if s["step"]=="section")
            assert step["detail"]["calls"][0]["cached"]==cached
        assert len(sent)==1
    finally:e.close()


def test_section_candidates_use_product_description(shop):
    sections=shop.catalog.sections
    hits=sections.candidates("оптимизация расхода древесины")
    assert hits[0][0]=="c0" and hits[0][1]>hits[1][1]
    hits=sections.candidates("электронная очередь и талоны")
    assert hits[0][0]=="c3" and hits[0][1]>hits[1][1]
    unrelated=response(shop,"заказать болотные сапоги")
    assert not cards_from(unrelated["blocks"]) and all(step["step"]!="section" for step in unrelated["trace"])


def test_declared_replacement_beats_semantics(cfg,tmp_path):
    snapshot(tmp_path)
    path=tmp_path/"catalog.jsonl"
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["attrs"]["analog_of"]="Forma Cloud"
    path.write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in rows))
    e=Engine.open(replace(cfg,data=tmp_path))
    try:
        r=response(e,"российская альтернатива для Forma Cloud","smart")
        assert cards_from(r["blocks"])[0]["offer"]["offer_id"]=="0-new"
        assert all(s["step"]!="section" for s in r["trace"])
    finally:e.close()
