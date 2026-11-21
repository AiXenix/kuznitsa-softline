import json
from pathlib import Path
from shutil import copyfile, copytree

import pytest

from kuznitsa.ingest import history
from kuznitsa.ingest.day import day

EXAMPLES=Path(__file__).resolve().parents[2]/"docs/ingest_examples"


@pytest.mark.parametrize("mode",["parent","indent","outline"])
def test_ut_day(mode,cfg,tmp_path):
    out=tmp_path/"out"
    report=day(EXAMPLES/("day_ut_"+mode),cfg,out,ai="off",n=2)
    assert {f["role"]:f["accepted"] for f in report["files"]}=={"catalog":3,"prices":3}
    rows={r["sku"]:r for r in map(json.loads,(out/"catalog.jsonl").read_text().splitlines())}
    assert len(rows)==report["catalog"]["offers"]==3
    assert rows["VX-001"]["category_path"]==["Программы","Проектирование"]
    assert rows["VX-002"]["category_path"]==["Программы","Графика"]
    assert not rows["VX-003"]["category_path"]
    first=rows["VX-001"]
    assert (first["price"],first["attrs"]["prices"])==(1250.50,{"Для госзаказчиков":1100.50,"Оптовая":1050.50})
    assert (first["vendor"],first["family_name"],first["edition"])==("Вектор","Север","Проф")
    assert first["registry"] and first["attrs"]["country"]=="Россия"
    attrs=first["attrs"]
    assert (attrs["vendor"],attrs["series"],attrs["edition"])==("Вектор","Север","Проф")
    assert (attrs["term_months"],attrs["metric"],attrs["unit"])==("24","user","пользователь")
    assert (attrs["qty_min"],attrs["qty_max"],attrs["registry_no"])==("10","49","№ 75001")
    assert first["lic"]["term_months"]==24 and first["lic"]["metric"]=="user"
    assert (first["lic"]["qty_min"],first["lic"]["qty_max"])==(10,49)
    assert rows["VX-002"]["lic"]["pack"]==5


def test_batch_routes_api_pages_and_support_chat(cfg,tmp_path,monkeypatch):
    src=tmp_path/"incoming"
    copytree(EXAMPLES/"ut_history",src)
    copyfile(EXAMPLES/"day_usd/01.csv",src/"products.csv")
    original=history.sniff
    def sniff(path):
        if path.suffix==".json":
            return dict(kind="metrika_api",columns={"dimensions":"dimension"},confidence=1.,reason="Страница отчёта")
        if path.name=="tickets.csv":
            return dict(kind="support_chat",columns={},confidence=1.,reason="Обращения покупателей")
        return original(path)
    def ingest(engine,files,mapping):
        assert {p.name for p in files}=={"page1.json","page2.json","tickets.csv"}
        return [dict(file=p.name, rows_accepted=2, skipped=0) for p in files]
    monkeypatch.setattr(history,"sniff",sniff)
    monkeypatch.setattr(history,"ingest_files",ingest)
    report=day(src,cfg,tmp_path/"out",ai="off",n=1)
    markdown=(tmp_path/"out/day_report.md").read_text()
    assert markdown.count("Метрика · API отчётов")==2 and "Обращения в чат поддержки" in markdown
    assert [(f["role"],f["accepted"]) for f in report["files"] if f["role"]!="catalog"]==[
        ("metrika_api",2),("metrika_api",2),("support_chat",2)]


def test_missing_retail_and_arbitrary_price_label(cfg,tmp_path):
    from openpyxl import Workbook
    from kuznitsa.ingest.catalog import import_catalog

    wb=Workbook()
    products=wb.active
    products.append(["Код","Наименование","Характеристики"])
    products.append(["N1","Вектор CAD","Срок: бессрочный; Количество: 5 шт."])
    prices=wb.create_sheet("Лист 2")
    prices.append(["Код","Виды цен"])
    prices.merge_cells("A1:A2")
    prices.merge_cells("B1:D1")
    for col,label in enumerate(["Розничная (руб.)","Постоянный покупатель","Оптовая"],2):
        prices.cell(2,col,label)
    prices.append(["N1",None,"1 100,55","по запросу"])
    source=tmp_path/"book.xlsx"
    wb.save(source)
    out=tmp_path/"snapshot"
    r=import_catalog([source],out,cfg.kb,ai="off")
    assert r["offers"]==1 and not r["rejected"]
    row=json.loads((out/"catalog.jsonl").read_text())
    assert row.get("price") is None and row["price_on_request"]
    assert row["attrs"]["prices"]=={"Постоянный покупатель":1100.55}
    assert (row["lic"]["model"],row["lic"]["pack"])==("perpetual",5)



def test_moysklad_pages_and_offer_identity(cfg,tmp_path):
    from dataclasses import replace
    from uuid import UUID
    from kuznitsa.analytics.store import result_cards
    from kuznitsa.engine import Engine
    from kuznitsa.schema import Request

    out=tmp_path/"snapshot"
    report=day(EXAMPLES/"day_moysklad",cfg,out,ai="off",n=4)
    assert [f["role"] for f in report["files"]]==["catalog","catalog","catalog","categories","stock"]
    assert [(f["accepted"],f["skipped"]) for f in report["files"]]==[(2,0),(1,0),(2,0),(2,0),(3,1)]
    assert [f["page"]["offset"] for f in report["files"][:2]]==[0,2]
    offers={o["sku"]:o for o in map(json.loads,(out/"catalog.jsonl").read_text().splitlines())}
    assert len(offers)==report["catalog"]["offers"]==4
    engine=Engine.open(replace(cfg,data=out,cache=out/"cache"))
    try:
        for n in (4,5,6,7):
            code=f"MS-{n:02d}"
            o=offers["AR-"+code]
            keys=[str(UUID(int=n)),code,"EXT-"+code,"AR-"+code]
            assert set(keys)<=set(o["source_ids"])
            for key in keys:
                assert result_cards(engine.search(Request(q=key,mode="fast")))[0]["offer"]["offer_id"]==o["offer_id"]
            assert o["category_path"]==["Программы","Проектирование"]
            assert o["attrs"]["country"]=="Россия" and o["lic"]["metric"]=="user"
        pro,std=(offers["AR-MS-04"],offers["AR-MS-05"])
        assert pro["family_id"]==std["family_id"]
        assert (pro["edition"],pro["lic"]["term_months"],std["lic"]["term_months"],std["lic"]["pack"])==("Проф",24,12,5)
        assert pro["attrs"]["in_stock"]=="false" and std["in_stock"]
        assert pro["price"]==400.55 and std["attrs"]["prices"]["Для госзаказчиков"]==500
        assert offers["AR-MS-06"]["price"]==700.01
        assert "EXT-MS-03" in pro["source_ids"] and "EXT-MS-03" in std["source_ids"]
    finally:
        engine.close()


def test_moysklad_short_stock_and_product_page(cfg,tmp_path):
    from kuznitsa.ingest.catalog import import_catalog
    src=EXAMPLES/"day_moysklad"
    page=json.loads((src/"02.json").read_text())
    page["meta"]["href"]=page["meta"]["href"].replace("/assortment","/product")
    product=page["rows"][0]
    products=tmp_path/"catalog.json"
    products.write_text(json.dumps(page))
    stock=tmp_path/"availability.json"
    stock.write_text(json.dumps({"stock":[{"code":product["code"],"externalCode":"WAREHOUSE-7","quantity":0}]}))
    out=tmp_path/"short"
    report=import_catalog([stock,products],out,cfg.kb,ai="off")
    row=json.loads((out/"catalog.jsonl").read_text())
    assert report["offers"]==1 and row["attrs"]["in_stock"]=="false"
    assert "WAREHOUSE-7" in row["source_ids"]
