import json
from pathlib import Path

import pytest

from kuznitsa.ingest.day import day

EXAMPLES=Path(__file__).resolve().parents[2]/"docs/ingest_examples"
AMOUNTS={"retail":1800.75,"project":1600.25,"partner":1450,"gov":1350.5,"wholesale":1200}
LABELS=["Розничная","Цена проектная","Партнёрская цена","Для госзаказчиков","ОПТОВАЯ"]


@pytest.mark.parametrize("source",["day_d7_moysklad","day_d7_ut"])
def test_supplier_names_reach_snapshot_and_both_reports(source,cfg,tmp_path):
    out=tmp_path/"snapshot"
    report=day(EXAMPLES/source,cfg,out,ai="off",n=1)
    rows=list(map(json.loads,(out/"catalog.jsonl").read_text().splitlines()))
    assert len(rows)==5
    for i,row in enumerate(sorted(rows,key=lambda r:r["sku"])):
        attrs=row["attrs"]
        assert attrs["analog_of"]=="Калькулятор смет"
        assert attrs["aliases"]==["бюро","сметчик"]
        assert attrs["task"]=="Составление смет"
        assert attrs["edition"]==row["edition"]=="Проф"
        assert attrs["operation"]=="Продление" and row["lic"]["action"]=="renewal"
        assert attrs["country"]=="Россия" and attrs["registry_no"]==str(92000+i)
        assert attrs["prices"]=={**AMOUNTS,**dict(zip(LABELS,AMOUNTS.values()))}
        assert row["price"]==attrs["prices"]["retail"]
    counts=report["catalog"]["attributes"]
    assert counts==json.loads((out/"import_report.json").read_text())["attributes"]
    for k in ("analog_of","aliases","task","edition","operation","country","registry_no","prices"):
        assert counts["by_key"][k]==5
    assert counts["unmatched"]=={"Контур внедрения":3}
    markdown=(out/"day_report.md").read_text()
    assert "| analog_of | 5 |" in markdown and "Контур внедрения (3)" in markdown


def test_alias_collisions_and_counts(tmp_path,cfg):
    from kuznitsa.ingest.catalog import import_catalog

    file=tmp_path/"items.jsonl"
    file.write_text(json.dumps(dict(name="Аврора",sku="AU-1",edition="ПРОФ",version="2026",
        attrs={"Жаргон":"Полярник","ТаК.Же ищут!":"Полярник, атлас","Исполнение":"База",
               "Тип лицензии":"upgrade","Контрольный цвет":"янтарь"},
        prices={"Цена партнёрская":150,"Партнерская":170,"partner":145}),ensure_ascii=False)+"\n")
    out=tmp_path/"out"
    receipt=import_catalog([file],out,cfg.kb,ai="off")
    offer=json.loads((out/"catalog.jsonl").read_text())
    assert offer["attrs"]["prices"]=={"Цена партнёрская":150,"Партнерская":170,"partner":145}
    assert offer["attrs"]["aliases"]==["Полярник","атлас"]
    assert offer["attrs"]["operation"]==offer["lic"]["action"]=="upgrade"
    assert (offer["edition"],offer["attrs"]["edition"],offer["version"])==("ПРОФ","ПРОФ","2026")
    assert receipt["attributes"]["by_key"]["aliases"]==2
    assert receipt["attributes"]["unmatched"]=={"Контрольный цвет":1}


def test_only_special_prices_keep_retail_unknown(tmp_path,cfg):
    from kuznitsa.ingest.catalog import import_catalog
    product=tmp_path/"catalog.csv"
    product.write_text("Код;Наименование\nS01;Смета\n")
    prices=tmp_path/"rates.csv"
    prices.write_text("Код;Цена проектная;для ГОС. заказчиков\nS01;800;650\n")
    out=tmp_path/"out"
    report=import_catalog([prices,product],out,cfg.kb,ai="off")
    assert report["offers"]==1
    offer=json.loads((out/"catalog.jsonl").read_text())
    assert offer["price_on_request"] and offer.get("price") is None
    assert offer["attrs"]["prices"]=={"Цена проектная":800,"для ГОС. заказчиков":650,"project":800,"gov":650}
