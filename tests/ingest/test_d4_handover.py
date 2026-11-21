import json
from datetime import date

from openpyxl import Workbook

from kuznitsa.config import Config
from kuznitsa.engine import Engine
from kuznitsa.ingest import history
from kuznitsa.ingest.adapters import tables
from kuznitsa.ingest.catalog import import_catalog
from kuznitsa.ingest.day import identify
from kuznitsa.ingest.source_index import install
from kuznitsa.kb.loader import load
from kuznitsa.mock.catalog_gen import demo_record
from kuznitsa.schema import Offer, Request


def test_grouped_headers_and_sections(tmp_path):
    book=Workbook()
    sheet=book.active
    sheet.append(["Отчёт за квартал"])
    sheet.merge_cells("A1:D1")
    sheet.append(["Товарные позиции",None,"Цена","Остаток"])
    sheet.merge_cells("A2:B2")
    sheet.append(["Артикул","Наименование","USD","шт."])
    sheet.append(["Приложения"])
    sheet.merge_cells("A4:D4")
    sheet.append([None,"Чертёжные"])
    sheet.merge_cells("B5:D5")
    sheet.append(["R-01","Ink Draw",120,2])
    sheet.append(["Итого",None,120])
    sheet=book.create_sheet("Ещё")
    sheet.append(["Раздел","Товар","Розница"])
    sheet.append(["Офис","Writer",440])
    path=tmp_path/"book.xlsx"
    book.save(path)
    sheets=[list(rows) for _,rows in tables(path,{})]
    assert len(sheets)==2
    assert sheets[0]==[(6,{"Артикул":"R-01","Наименование":"Ink Draw","Цена USD":120,
                          "Остаток":2,"category_path":"Приложения/Чертёжные"})]
    assert sheets[1][0][1]["Товар"]=="Writer"


def test_merge_nonstandard_key_and_load_search(tmp_path,cfg):
    primary=tmp_path/"a.csv"
    primary.write_bytes(('Внутренний ключ;Артикул;Товар;Цена;Страна разработки;Альтернатива;ФСТЭК;Серия;Упаковщик\n'
                         'CODE001;M-01;"Red; Box";"1 230,50";Россия;Legacy;Да;Box;А\n'
                         'CODE002;M-02;Green Pack;200;Китай;;;Pack;Б\n').encode("cp1251"))
    stock=tmp_path/"b.csv"
    stock.write_text("item id,stock quantity,price,lead time,promo,added_at\nCODE001,0,1500,3-7,yes,2026-11-10\nCODE002,4,200,today,no,2026-11-09\n")
    out=tmp_path/"out"
    r=import_catalog([stock,primary],out,cfg.kb,ai="off")
    assert r["offers"]==2 and r["merge"]["matched"][str(stock)]==2
    assert r["merge"]["conflicts"]["price"]>=1
    rows=list(map(json.loads,(out/"catalog.jsonl").read_text().splitlines()))
    o=rows[0]
    assert o["source_id"]=="CODE001" and "M-01" in o["source_ids"]
    assert o["name"]=="Red; Box" and o["price"]==1230.5
    assert [o[k] for k in ("in_stock","delivery_days","promo","added_at","domestic")]==[False,7,True,"2026-11-10",True]
    assert o["attrs"]["analog_of"]=="Legacy" and o["certs"]==["fstec"]
    extra=o["attrs"]["extra"]
    assert (json.loads(extra) if isinstance(extra,str) else extra)["Упаковщик"]=="А"
    assert rows[1]["domestic"] is False
    kb=load(cfg.kb,out)
    assert kb.auto["families"]==2
    eng=Engine.open(Config(data=out,cache=tmp_path/"cache",kb=cfg.kb,embed="off"))
    try:
        install(eng.catalog)
        response=eng.search(Request(q="CODE001",mode="fast"))
        products=next(b for b in response["blocks"] if b["type"]=="products")
        assert products["items"][0]["offer"]["offer_id"]==o["offer_id"]
    finally:
        eng.close()


def test_sniff_precedes_product_heuristics(tmp_path,monkeypatch):
    p=tmp_path/"part.tsv"
    p.write_text("x\ty\n7\texample\n")
    monkeypatch.setattr(history,"sniff",lambda path:dict(kind="metrika_hits",reason="Хиты",columns={"x":"hit_id"},confidence=.92),raising=False)
    result={}
    assert identify(p,diagnostics=result)==("metrika_hits",{"x":"hit_id"})
    assert result["confidence"]==.92


def test_mock_direction_fields():
    o=Offer(offer_id="k1",name="Клиент",available=True,delivery="esd",registry=True,attrs={"promo":"true"})
    today=date(2026,11,21)
    row=json.loads(demo_record(o,today,{}))
    assert row["domestic"] and row["in_stock"] and row["promo"]
    assert row["delivery_days"]==0 and 0<=(today-date.fromisoformat(row["added_at"])).days<540
    assert row==json.loads(demo_record(o,today,{}))


def test_b4_replay_contract(tmp_path,cfg,monkeypatch):
    from kuznitsa.analytics import replay
    from kuznitsa.ingest.day import day
    original=replay.run
    seen=[]
    def run(engine,mode,limit,*,cfg):
        seen.append((mode,limit,cfg.data))
        return original(engine,mode=mode,limit=limit)
    monkeypatch.setattr(replay,"run",run)
    folder=tmp_path/"uploads"
    folder.mkdir()
    (folder/"catalog.csv").write_text("sku,name,price\nX-01,Example Suite,900\n")
    out=tmp_path/"new"
    result=day(folder,cfg,out,ai="off",n=1,replay_limit=2)
    assert seen==[("fast",2,out)] and result["replay"]["status"]=="completed"


def test_commerce_variants_tiered_workbook_and_public_lookup(tmp_path,cfg):
    from pathlib import Path
    from kuznitsa.analytics.store import result_cards
    sources=Path(__file__).resolve().parents[2]/"docs/ingest_examples"
    expected={"commerceml":([1200.5,2800],["UT-12-S","product-12#v2"]),
              "variants":([1490,2990],["variant-guid-1","SUP-111"]),
              "bands":([1000,850],[])}
    for name,(prices,codes) in expected.items():
        files=sorted((sources/("day_"+name)).iterdir(),reverse=True)
        out=tmp_path/name
        r=import_catalog(files,out,cfg.kb,ai="off")
        assert r["offers"]==2 and all(identify(path)[0]=="catalog" for path in files)
        rows=list(map(json.loads,(out/"catalog.jsonl").read_text().splitlines()))
        assert [o["price"] for o in rows]==prices
        assert len({o["offer_id"] for o in rows})==2
        if name=="commerceml":
            assert rows[0]["category_path"]==["Инженерные решения","Проектирование"]
            assert rows[0]["domestic"] and rows[0]["in_stock"] and not rows[1]["in_stock"]
            assert rows[0]["attrs"]["Тип цены"]=="Розничная"
            assert rows[0]["edition"]=="Стандарт"
        elif name=="variants":
            aliases=rows[0]["attrs"]["aliases"]
            assert (json.loads(aliases) if isinstance(aliases,str) else aliases)==["плановик","учёт запасов"]
            assert rows[1]["attrs"]["task"]=="Планировать пополнение запасов"
        else:
            assert [(r["lic"]["qty_min"],r["lic"]["qty_max"]) for r in rows]==[(1,9),(10,50)]
        config=Config(data=out,cache=out/"cache",kb=cfg.kb,embed="off")
        eng=Engine.open(config)
        try:
            install(eng.catalog)
            if name=="bands":
                from io import BytesIO
                from openpyxl import load_workbook
                from kuznitsa.api.files import search_file
                from kuznitsa.quote.export import make_export
                response=search_file(eng,b"Product name;Part number;Qty\nArchive;V-123;12","order.csv","guest","fast","")
                line=response["blocks"][0]["lines"][0]
                assert line["card"]["offer"]["offer_id"]==rows[1]["offer_id"]
                content,_=make_export(eng,response["search_id"],"xlsx")
                book=load_workbook(BytesIO(content),read_only=True)
                assert book.active["K5"].value=="V-123"
                book.close()
            for o,code in zip(rows,codes):
                response=eng.search(Request(q=code,mode="fast"))
                assert result_cards(response)[0]["offer"]["offer_id"]==o["offer_id"]
            for o in rows:
                for key in o["source_ids"]:
                    card=result_cards(eng.search(Request(q=key,mode="fast")))[0]
                    assert card["offer"]["offer_id"] in {v["offer_id"] for v in rows if key in v["source_ids"]}
        finally:
            eng.close()


def test_guid_distinguishes_variants_sharing_article(tmp_path,cfg):
    source=tmp_path/"prices.csv"
    source.write_text("name,sku,guid,price,Синонимы,Жаргон\n"
                      "Studio Edition,M-1,g-11,11,редактор,студия\n"
                      "Studio Upgrade,M-1,g-12,12,переход,апгрейд\n")
    import_catalog([source],tmp_path/"out",cfg.kb,ai="off")
    rows=list(map(json.loads,(tmp_path/"out/catalog.jsonl").read_text().splitlines()))
    assert [o["source_id"] for o in rows]==["g-11","g-12"]
    assert len({o["offer_id"] for o in rows})==2
    aliases=rows[0]["attrs"]["aliases"]
    assert (json.loads(aliases) if isinstance(aliases,str) else aliases)==["редактор","студия"]
