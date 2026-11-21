import json
from dataclasses import replace
from pathlib import Path

from kuznitsa.analytics.store import result_cards
from kuznitsa.engine import Engine
from kuznitsa.ingest.catalog import import_catalog
from kuznitsa.schema import Request


def test_supplier_series_and_offer_specific_units(tmp_path,cfg):
    products=tmp_path/"products.csv"
    products.write_text("source_id;name;vendor;vendor_id;series;family_id;metric\n"
                        "Q-1;Коммерческая лицензия;ГК Современные технологии управления;ERP-V12;Business Studio;ERP-F28;user\n")
    prices=tmp_path/"prices.csv"
    prices.write_text("source_id;guid;unit;qty_min;qty_max;price\n"
                      "Q-1;D-10;устройство;1;10;1000\n"
                      "Q-1;U-10;пользователь;1;10;1500\n"
                      "Q-1;S-20;сервер;11;20;2000\n")
    out=tmp_path/"snapshot"
    config=replace(cfg,kb=Path("kb"),data=out)
    report=import_catalog([products,prices],out,config.kb,ai="off")
    assert report["offers"]==3
    rows=[json.loads(line) for line in (out/"catalog.jsonl").read_text().splitlines()]
    assert {(o["vendor_id"],o["family_id"]) for o in rows}=={("business_studio","business_studio")}
    engine=Engine.open(config)
    try:
        for code,metric,lo,hi in (("D-10","device",1,10),("U-10","user",1,10),("S-20","server",11,20)):
            card=result_cards(engine.search(Request(q=code,mode="fast")))[0]
            offer=card["offer"]
            assert code in offer["source_ids"]
            assert (offer["metric"],offer["qty_min"],offer["qty_max"])==(metric,lo,hi)
        from kuznitsa.api.files import search_file
        request="Артикул;Количество;Единица;Номенклатура\nQ-1;5;пользователь;Лицензия"
        line=search_file(engine,request.encode(),"order.csv","guest","fast","")["blocks"][0]["lines"][0]
        assert line["card"]["offer"]["metric"]=="user"
    finally:
        engine.close()


def test_flat_bands_with_shared_article(tmp_path,cfg):
    source=tmp_path/"tiers.csv"
    source.write_text("sku;name;unit;qty_min;qty_max;price\n"
                      "A-7;Suite;ПК;1;20;100\n"
                      "A-7;Suite;сервер;1;20;200\n"
                      "A-7;Suite;сервер;1;20;200\n")
    report=import_catalog([source],tmp_path/"out",cfg.kb,ai="off")
    assert report["offers"]==2 and report["duplicates"]==1


def test_legal_name_respects_curated_brand():
    from types import SimpleNamespace
    from kuznitsa.ingest.nameparse import Parser
    vendors={"former":{"name":"First","name_ru":"Бюро Программ (прежнее название)"},
             "current":{"name":"Second","aliases":["Бюро Программ"]}}
    parser=Parser(SimpleNamespace(rows={"families":{},"vendors":vendors,"categories":{}}))
    assert parser.lookup("vendors","Бюро Программ").value=="current"


def test_admin_export_sales_flags_and_feed(tmp_path,cfg):
    from kuznitsa.ingest.day import day
    incoming=tmp_path/"incoming"
    incoming.mkdir()
    supplier=incoming/"items.csv"
    supplier.write_text(
        "ID;NAME;PROPERTY_ARTNUMBER;PROPERTY_SERIES;PROPERTY_VENDOR;PROPERTY_MANUFACTURER;"
        "SECTION_PATH;PROPERTY_SEARCH_TAG;TAGS;DETAIL_TEXT;Активность;Снят с продажи;Статус;price\n"
        "11;Gamma Suite;AA11;Gamma;North;;ПО / Сети > Мониторинг;сеть;наблюдение;"
        '"<p>Учёт&nbsp;узлов</p><script>debug()</script>";Y;N;;540\n'
        "12;Zeta Box;AA12;Zeta;;Maker;;;;;N;N;;100\n"
        "13;Theta Box;AA13;Theta;;Maker;;;;;Y;Да;;100\n"
        "14;Delta Box;AA14;Delta;;Maker;;;;;Y;N;архив;100\n")
    (incoming/"feed.yml").write_text('<yml_catalog><shop><offers><offer id="12" available="true">'
                                    '<name>Zeta Box</name><price>100</price></offer></offers></shop></yml_catalog>')
    out=tmp_path/"data"
    result=day(incoming,cfg,out,ai="off",n=1)
    assert result["catalog"]["offers"]==1 and result["catalog"]["inactive"]==3
    assert "Снято с продажи — 3" in (out/"day_report.md").read_text()
    offer=json.loads((out/"catalog.jsonl").read_text())
    assert offer["sku"]=="AA11" and offer["description"]=="Учёт узлов"
    assert offer["vendor"]=="North" and offer["family_name"]=="Gamma"
    assert offer["category_path"]==["ПО","Сети","Мониторинг"]
    assert offer["attrs"]["aliases"]==["сеть","наблюдение"]
    archived=list(map(json.loads,(out/"inactive_offers.jsonl").read_text().splitlines()))
    assert {r["sku"] for r in archived}=={"AA12","AA13","AA14"}
    assert all(r["attrs"]["active"] is False and r["attrs"]["sold"] is False for r in archived)
    assert all(r["vendor"]=="Maker" for r in archived)


def test_metrika_goals_from_sniff(tmp_path,cfg,monkeypatch):
    from kuznitsa.ingest import history
    from kuznitsa.ingest.day import day
    incoming=tmp_path/"files"
    incoming.mkdir()
    (incoming/"items.csv").write_text("sku,name,price\nV1,Suite,100\n")
    goals=incoming/"totals.csv"
    goals.write_text("Достижение целей;;;\nДата;Корзина;Заказ;Заявка\n2026-11-01;5;2;1\n")
    original=history.sniff
    def sniff(path):
        if path==goals:
            return dict(kind="metrika_goals",columns={},confidence=1.,reason="Цели по датам")
        return original(path)
    def ingest(engine,files,mapping):
        assert list(files)==[goals]
        return [dict(rows_accepted=1,skipped=0)]
    monkeypatch.setattr(history,"sniff",sniff)
    monkeypatch.setattr(history,"ingest_files",ingest)
    out=tmp_path/"new"
    result=day(incoming,cfg,out,ai="off",n=1)
    assert any(f["role"]=="metrika_goals" and f["accepted"]==1 for f in result["files"])
    assert "Метрика · достижение целей" in (out/"day_report.md").read_text()


def test_reimport_withdraws_last_sellable_product(tmp_path,cfg):
    path=tmp_path/"items.csv"
    out=tmp_path/"data"
    path.write_text("sku;name;price;ACTIVE\nA-7;Gamma;120;Y\n")
    assert import_catalog([path],out,cfg.kb,ai="off")["offers"]==1
    path.write_text("sku;name;price;ACTIVE\nA-7;Gamma;120;N\n")
    report=import_catalog([path],out,cfg.kb,ai="off")
    assert report["inactive"]==1 and report["offers"]==0
    assert (out/"catalog.jsonl").read_text()==""
    assert json.loads((out/"inactive_offers.jsonl").read_text())["attrs"]["sold"] is False
