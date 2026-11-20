import json
from pathlib import Path

import pytest
import yaml
from kuznitsa.cli import main
from kuznitsa.config import ROOT
from kuznitsa.ingest.auto import merge_auto
from kuznitsa.ingest.catalog import import_catalog
from kuznitsa.ingest.enrich import Enricher
from kuznitsa.ingest.nameparse import Parser
from kuznitsa.kb.loader import load
from kuznitsa.schema import Offer

EXAMPLES=ROOT/"docs/ingest_examples"
KB=ROOT/"kb"


def read(out):
    return [Offer.model_validate_json(line) for line in (out/"catalog.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("ext","csv tsv json jsonl xlsx yml".split())
def test_known_suppliers(ext,tmp_path):
    report=import_catalog([EXAMPLES/f"price.{ext}"],tmp_path,KB)
    truth=yaml.safe_load((EXAMPLES/"expected.yaml").read_text())
    rows=read(tmp_path)
    assert {o.sku for o in rows}==truth.keys()
    assert report["duplicates"]==1 and report["rejected"]==(2 if ext=="jsonl" else 1)
    assert sum(o.vendor_id==truth[o.sku]["vendor"] for o in rows)/len(rows)>=.95
    assert sum(o.family_id==truth[o.sku]["family"] for o in rows)/len(rows)>=.95
    assert sum(o.edition==truth[o.sku]["edition"] for o in rows)/len(rows)>=.95
    fields=[(getattr(o.lic,k),v) for o in rows for k,v in truth[o.sku]["lic"].items()]
    assert sum(a==b for a,b in fields)/len(fields)>=.90
    if ext=="yml":
        assert rows[0].category_path==["ПО","Программы для организаций"]
        assert rows[0].language=="ru"


def test_new_products_and_reimport(tmp_path):
    f=EXAMPLES/"unknown.csv"
    report=import_catalog([f],tmp_path,KB)
    ids=[o.offer_id for o in read(tmp_path)]
    assert len(ids)==len(set(ids))==40
    assert report["auto"]==dict(vendors=1,categories=2,families=1)
    kb=load(KB)
    assert merge_auto(kb,tmp_path)==report["auto"]
    assert len({o.card_id for o in read(tmp_path)})==1
    assert kb.rows["categories"][read(tmp_path)[0].category_id]["parent"]
    import_catalog([f],tmp_path,KB)
    assert ids==[o.offer_id for o in read(tmp_path)]


def test_mapping_and_reference_join(tmp_path):
    table=tmp_path/"products.csv"
    table.write_text("X|tag|categoryId|price\nНовинка|A1|2|2 499,90\n")
    refs=tmp_path/"categories.json"
    refs.write_text(json.dumps([dict(id=1,title="Группа",parent=None),dict(id=2,title="Подгруппа",parent=1)]))
    m=tmp_path/"mapping.yaml"
    m.write_text("name: X\nsku: tag\n")
    out=tmp_path/"data"
    args=([table,refs],out,KB,m)
    import_catalog(*args,dry_run=True)
    assert not out.exists()
    report=import_catalog(*args)
    assert report["offers"]==1
    offer,=read(out)
    assert offer.category_path==["Группа","Подгруппа"] and offer.price==2499.90


def test_native_roundtrip_and_search(tmp_path,monkeypatch,capsys):
    from kuznitsa.mock.catalog_gen import offers_for
    kb=load(KB)
    f=kb.rows["families"]["kaspersky_kesb"]
    offers=list(offers_for(f,"Kaspersky",42,60))
    source=tmp_path/"export.jsonl"
    source.write_text("\n".join(o.model_dump_json(exclude_defaults=True,exclude_none=True) for o in offers))
    import_catalog([source],tmp_path,KB)
    assert read(tmp_path)==offers
    import_catalog([EXAMPLES/"price.csv"],tmp_path,KB)
    monkeypatch.setenv("KZ_EMBED_MODEL","off")
    monkeypatch.setenv("KZ_CACHE_DIR",str(tmp_path/"cache"))
    monkeypatch.setenv("KZ_DATA_DIR",str(tmp_path))
    assert main(["build-index"])==0
    capsys.readouterr()
    assert main(["search","антивирус на 30 пк","--mode","fast"])==0
    result=json.loads(capsys.readouterr().out)
    matches=[i for b in result["blocks"] for i in b.get("items",[]) if i.get("card_id")=="kaspersky_kesb:standard"]
    assert matches and matches[0]["offer"]["qty_min"]==25


def test_parser_evidence():
    p=Parser(load(KB))
    cases=[
        ("Kaspersky Endpoint Security для бизнеса – Расширенный Russian Edition. 25-49 Node 1 year Renewal License",
         dict(family_id="kaspersky_kesb",edition="advanced",qty_min=25,qty_max=49,metric="device",language="ru",term_months=12,action="renewal")),
        ("Dr.Web Desktop Security Suite Комплексная защита, 12 мес., 30 ПК, продление",
         dict(vendor_id="drweb",edition="complex",term_months=12,pack=30,metric="device",action="renewal")),
        ("Право на использование ПО МойОфис Стандартный 2, бессрочная, для образования, 100 шт.",
         dict(family_id="myoffice_standard",edition="standard_2",model="perpetual",audience="edu",pack=100)),
        ("WinSvrSTDCore 2022 SNGL OLV 2Lic NL Each AP CoreLic",
         dict(family_id="windows_server",edition="standard",pack=2,version="2022",metric="core")),
        ("Astra Linux Special Edition РУСБ.10015-01 «Воронеж», ФСТЭК, электронная поставка, ТП «Стандарт» 12 мес.",
         dict(family_id="astra_linux_se",edition="voronezh",delivery="esd",certs=["fstec"],action="support"))]
    for name,expected in cases:
        parsed=p.parse(name)
        for k,v in expected.items():
            assert parsed[k].value==v and parsed[k].fragment in name
    row=dict(name=cases[0][0],attrs={"Срок":"2 г.","Действие":"Rnwl"},action="Base")
    offer,trace,_=Enricher(p,{}).convert(row)
    assert offer.lic.term_months==24 and trace["term_months"].source=="attribute"
    assert trace["action"].value=="new" and trace["action"].source=="column"


def test_quality_report_and_signals(tmp_path):
    records=[dict(sku=f"P-{i}",name="Oriole Planner",**fields) for i,fields in enumerate([
        dict(price=100,rating=4,cost=70,stock=0),dict(price=105),dict(price=108),
        dict(price=12000),dict(price=0),dict(price="по запросу"),dict(price="опечатка"),{}])]
    source=tmp_path/"supplier.json"
    source.write_text(json.dumps(records))
    report=import_catalog([source],tmp_path/"out",KB)
    counts={i["code"]:i["count"] for i in report["issues"]}
    for key in ("price_outlier","no_price","request_price","zero_price","invalid_price"):
        assert counts[key]==1
    assert counts["no_description"]==counts["no_vendor"]==counts["no_category"]==8
    rows=read(tmp_path/"out")
    assert rows[0].popularity>.5 and rows[0].margin==pytest.approx(.3) and not rows[0].available
    assert rows[1].popularity==rows[1].margin==.5
    assert len(report["notes"])==2


def test_unicode_delimiter_and_damaged_quote(tmp_path):
    source=tmp_path/"feed.csv"
    source.write_text('sku§name§price\nA§Planner One§100\nB§"bad\nC§Planner Three§200\n')
    report=import_catalog([source],tmp_path/"out",KB)
    assert report["rejected"]==1
    assert [o.sku for o in read(tmp_path/"out")]==["A","C"]
