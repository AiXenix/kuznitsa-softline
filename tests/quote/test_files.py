import csv
from io import BytesIO,StringIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from kuznitsa.app import create_app
from kuznitsa.quote.parse import LIMIT,parse
from kuznitsa.quote.export import quote_rows
from kuznitsa.schema import Request

EXAMPLES=Path(__file__).resolve().parents[2]/"docs/quote_examples"


@pytest.mark.parametrize("file,count",[("request.txt",3),("request.csv",2),("request-1c.xlsx",2),("order-200.csv",200)])
def test_read_examples(file,count):
    rows,info=parse((EXAMPLES/file).read_bytes(),file)
    assert len(rows)==info["positions"]==count
    if file.endswith("xlsx"):
        assert info["columns"]["qty"]=="Кол-во"
        assert rows[1]["sku"]=="4601546092816"
        assert info["skipped"][0]["row"]==7


def test_limits_and_cp1251():
    data="Название\tКол-во\n"+"Щит\t20\n"*203
    rows,info=parse(data.encode("cp1251"),"r.tsv")
    assert len(rows)==200 and info["skipped"][-1]["row"]==204
    assert rows[0]["query"]=="Щит — 20 шт"


@pytest.mark.parametrize("name,data,code,status",[("a.pdf",b"abc","file_unsupported",415),
    ("a.csv",b"","file_empty",400),("a.xlsx",b"bad","no_positions",400),
    ("a.txt",b"a"*(LIMIT+1),"file_too_large",413),("a.csv",b"Product name;Qty\n;2","no_positions",400)])
def test_errors(engine,name,data,code,status):
    with TestClient(create_app(engine)) as client:
        r=client.post("/api/spec/upload",params={"name":name},content=data)
        assert (r.status_code,r.json()["error"]["code"])==(status,code)


def test_upload_export_snapshot(engine):
    offer=next(o for o in engine.catalog.offers_by_id.values() if o.sku and o.price and o.available)
    quantity=offer.lic.qty_min or offer.lic.pack or 1
    body=f"Product name;Part number;Qty\n=TEST;{offer.sku};{quantity}\nUnknown;X-0123456;2"
    with TestClient(create_app(engine)) as client:
        r=client.post("/api/spec/upload?name=test.csv&profile_id=smb_trade",content=body.encode())
        assert r.status_code==200
        response=r.json()
        lines=response["blocks"][0]["lines"]
        assert len(lines)==2 and lines[0]["card"]["offer"]["sku"]==offer.sku
        assert lines[1]["card"] is None
        ident=response["search_id"]
        assert engine.journal.detail(ident)["upload"]["positions"]==2
        file=client.get("/api/export/"+ident)
        assert file.status_code==200 and ident[:6] in file.headers["Content-Disposition"]
        book=load_workbook(BytesIO(file.content))
        ws=book["Коммерческое предложение"]
        assert ws["B1"].value==engine.clients["smb_trade"].title
        assert ws["B5"].data_type=="s" and ws["D5"].value==offer.sku and ws["I5"].value==lines[0]["total"]
        assert ws["I7"].data_type=="f" and ws.freeze_panes=="B5"
        assert book["Не найдено"].max_row==2
        csv_file=client.get("/api/export/"+ident+"?format=csv")
        rows=list(csv.reader(StringIO(csv_file.content.decode("utf-8-sig")),delimiter=";"))
        assert rows[4][1].startswith("'=")
        assert client.get("/api/export/missing").status_code==404


def test_export_kit_slots_and_archived(engine):
    rows,missing=quote_rows({"query":{"raw":"комплект"},"understood":{},"blocks":[
        {"type":"kit","seats":25,"slots":[{"title":"Защита","card":None,"alternatives":[]}]}]})
    assert rows[0][6]==25 and missing[0][1]=="Защита"
    r=engine.search(Request(q="щит",mode="fast",profile_id="smb_trade",source="eval"))
    with engine.journal.transaction() as db:
        db.execute("UPDATE searches SET response_z=NULL WHERE search_id=?",(r["search_id"],))
    with TestClient(create_app(engine)) as client:
        book=load_workbook(BytesIO(client.get("/api/export/"+r["search_id"]).content))
        assert book.active["B1"].value==engine.clients["smb_trade"].title


def test_export_other_card_blocks():
    card=dict(card_id="a:b",title="Инструмент",offer={"name":"Поставка","sku":"A-1","price":None,"price_on_request":True})
    response=dict(query={"raw":"сравнить"},understood={"qty":{"value":3}},blocks=[
        {"type":"compare","columns":[card]},{"type":"services","items":[card]}])
    rows,missing=quote_rows(response)
    assert len(rows)==1 and not missing and rows[0][6:9]==[3,None,None]
    assert "Цена по запросу" in rows[0][-1]
