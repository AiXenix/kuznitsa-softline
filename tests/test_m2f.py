from dataclasses import replace
from shutil import copytree

import pytest
from kuznitsa.engine import Engine
from kuznitsa.evaluation import cards_from
from kuznitsa.schema import Offer, Request
from tests.conftest import MINI
from tests.test_m2b import shop


@pytest.fixture(scope="module")
def retail(cfg,tmp_path_factory):
    root=tmp_path_factory.mktemp("retail")
    kb=root/"kb"
    copytree(MINI,kb)
    (kb/"families/home.yaml").write_text("""- id: personal
  name: North Personal
  aliases: [север персональный]
  category: endpoint_security
  vendor: north
  analogs: [shield]
  license: {audiences: [home]}
""")
    (kb/"for_whom.yaml").write_text("families: [{id: personal, audiences: [home], for_whom: Для семьи}]")
    offer=Offer(offer_id="home-three",family_id="personal",vendor_id="north",vendor="North",
                name="North Personal на три устройства",family_name="North Personal",category_id="endpoint_security",
                price=900,lic=dict(audience="home",action="new",metric="device",pack=3))
    (root/"catalog.jsonl").write_bytes((cfg.data/"catalog.jsonl").read_bytes()+offer.model_dump_json().encode()+b"\n")
    (root/"clients.jsonl").write_bytes((cfg.data/"clients.jsonl").read_bytes())
    engine=Engine.open(replace(cfg,data=root,kb=kb))
    yield engine
    engine.close()


@pytest.mark.parametrize("q",["север персональный","антивирус для семьи на 3 устройства"])
def test_home_checkout(retail,q):
    def search(**kwargs):
        return retail.search(Request(q=q,mode="fast",**kwargs))
    guest=search()
    assert cards_from(guest["blocks"])[0]["offer"]["offer_id"]=="home-three"
    assert guest["understood"]["refined"]["audience"]=="home"
    for args in (dict(profile_id="smb_trade"),dict(filters={"audience":"business"})):
        result=search(**args)
        assert "EULA" in result["understood"]["agent_note"]
        assert any(b["type"]=="analogs" for b in result["blocks"])
        assert all(c["offer"]["audience"]!="home" for c in cards_from(result["blocks"]))


def test_company_use_in_free_text(retail):
    result=retail.search(Request(q="север персональный для бизнеса",mode="fast"))
    assert "EULA" in result["understood"]["agent_note"]
    assert any(b["type"]=="analogs" and b["items"] for b in result["blocks"])


@pytest.mark.parametrize("q,scenario,block",[
    ("перейти с AutoCAD на nanoCAD на 12 мест","license_ops","products"),
    ("сетевые лицензии для nanoCAD","license_ops","products"),
    ("продлить Autodesk AutoCAD","analog","analogs"),
    ("внедрение платформы 1с","service","services"),
    ("можно ли нашей компании применять шифрование","question","answer"),
    ("купленные лицензии нашей компании","account","my_licenses"),
    ("сбой базы, нужна лицензия Postgres Pro","product","products"),
    ("кп на 2 аналога Autodesk AutoCAD","analog","analogs"),
])
def test_operations(shop,q,scenario,block):
    r=shop.search(Request(q=q,profile_id="smb_trade",mode="fast"))
    assert r["understood"]["intent"]==scenario
    assert any(b["type"]==block for b in r["blocks"])


def test_supplier_format(shop,monkeypatch):
    card=shop.catalog.cards["nanocad:base"]
    monkeypatch.setitem(card.kb,"formats",["h3d"])
    r=shop.search(Request(q="в чем открывать файлы h3d",mode="fast"))
    assert r["understood"]["intent"]=="analog"
    assert cards_from(r["blocks"])[0]["card_id"]=="nanocad:base"


def test_colloquialisms(shop):
    for q in ("средство от вирусов","защита смартфонов для маленькой конторы"):
        r=shop.search(Request(q=q,mode="fast"))
        assert cards_from(r["blocks"])
        if "конторы" in q:assert r["understood"]["refined"]["audience"] in ("micro_office","mobile")
    r=shop.search(Request(q="антивирус для файлопомойки",mode="fast"))
    assert r["understood"]["refined"]["audience"]=="server"
    r=shop.search(Request(q="антивирус на макбук",mode="fast"))
    assert cards_from(r["blocks"]) and any("macOS" in n for n in r["notes"])


def test_compound_and_physical_quantity(shop):
    r=shop.search(Request(q="касперантивируспродление17пк",mode="fast"))
    assert r["understood"]["intent"]=="renewal" and r["understood"]["qty"]["value"]==17
    r=shop.search(Request(q="postgres pro на 8 физических процессоров",mode="fast"))
    assert r["understood"]["qty"]==dict(value=8,metric="cpu")


@pytest.fixture(scope="module")
def price_list(cfg,tmp_path_factory):
    import json
    root=tmp_path_factory.mktemp("external")
    def row(code,title,series,category,path,**changes):
        lic={"action":"new","metric":"user","audience":"business"}
        lic.update(changes.pop("lic",{}))
        attrs=dict(series=series,edition="Плюс",operation="Покупка")
        attrs.update(changes.pop("attrs",{}))
        return dict(offer_id=code,source_id=code,name=title,family_name=series,family_id=series,vendor_id="north",
                    vendor="Север",category_id=category,category_path=[path],price=710,attrs=attrs,lic=lic,**changes)
    rows=[
        row("compress","Ладога Плюс на пользователя","Ладога","compress","Сжатие файлов",lic=dict(qty_min=32,qty_max=62)),
        row("service","Техническая поддержка Ладога","Сопровождение Ладога","setup","Установка и настройка программ",kind="service"),
        row("papers","Tabula Document","Tabula","docs","Офисные пакеты"),
        row("words","Vocabula Editor","Vocabula","translation","Письменный перевод"),
        row("survey","Спектр Wi-Fi","Спектр","radio","Замеры Wi-Fi",attrs=dict(task="анализ покрытия беспроводной сети")),
        row("pro","AmberPrint MF 8 ESD","AmberPrint MF","print","Учёт печати",delivery="esd",version="8"),
        row("packs","Сфера, пакет","Сфера","compress","Сжатие файлов",lic=dict(qty_min=8,qty_max=8,pack=8)),
        row("rmail","Почтовая линия","Почтовая линия","mail","Почта",attrs=dict(analog_of="AureaMail",country="Россия")),
        row("fmail","Почтовый офис","Почтовый офис","mail","Почта",attrs=dict(analog_of="AureaMail",country="Китай")),
        row("bright","Яркий Офис Базовый","Яркий Офис Базовый","docs","Офисные пакеты"),
        row("pg","Наблюдатель","Наблюдатель","mon","Мониторинг СУБД",attrs=dict(task="оценка нагрузки СУБД PostgreSQL")),
        row("vault","Хранилище ключей","Хранилище ключей","passwords","Управление паролями"),
        row("recover","Возврат данных Server","Возврат данных","recover","Восстановление данных",lic=dict(metric="server")),
        row("home","Личный барьер","Барьер","protect","Антивирусная защита",lic=dict(audience="home")),
    ]
    (root/"catalog.jsonl").write_text("\n".join(map(json.dumps,rows)))
    e=Engine.open(replace(cfg,data=root))
    yield e
    e.close()


@pytest.mark.parametrize("delimiter",[";",","," — "])
def test_spec_license_before_support(price_list,delimiter):
    q="Ладога"+delimiter+"38"+(" шт" if delimiter==" — " else "")
    lines=price_list.search(Request(q=q,mode="fast"))["blocks"][0]["lines"]
    assert [(l["qty"],l["card"]["offer"]["offer_id"],l["total"]) for l in lines]==[(38,"compress",38*710)]


@pytest.mark.parametrize("delimiter",[";","|","\t"])
def test_supplier_lot(price_list,delimiter):
    q=delimiter.join(["Ладога","Плюс","Покупка","партия 39 мест"])
    r=price_list.search(Request(q=q+"\nЛадога;40",mode="fast"))
    assert [(l["qty"],l["card"]["offer"]["offer_id"]) for l in r["blocks"][0]["lines"]]==[(39,"compress"),(40,"compress")]


@pytest.mark.parametrize("q,expected",[
    ("data compression software","compress"),("translation tools","words"),("office productivity suite","papers"),
    ("software setup service","service"),("архиватор в малый офис","compress"),
    ("менеджер паролей для небольшой конторы","vault"),("восстановление носителей для сервера","recover"),
    ("антивирус родителям","home"),("измерить покрытие wi-fi","survey")])
def test_language_on_supplier_tree(price_list,q,expected):
    r=price_list.search(Request(q=q,mode="fast"))
    ids=[i.get("card",i)["offer"]["offer_id"] for b in r["blocks"] if b["type"] in ("products","services") for i in b["items"]]
    assert expected in ids, (r["understood"],ids)


@pytest.mark.parametrize("q,expected", [("Ладога на 29 мест",32),("Сфера на 19 мест",3)])
def test_cover_purchase(price_list,q,expected):
    r=price_list.search(Request(q=q,mode="fast"))
    first=cards_from(r["blocks"])[0]
    assert not first.get("qty_out_of_range") and first["calc"]["qty"]==expected


@pytest.mark.parametrize("q",["AmberPrint NG","AmberPrint 5.1 Professional","AmberPrint server","AmberPrint BOX"])
def test_missing_edition_has_related_family(price_list,q):
    r=price_list.search(Request(q=q,mode="fast"))
    b=next(b for b in r["blocks"] if b["type"]=="analogs")
    assert b["source"]["status"]=="unavailable" and b["items"][0]["card"]["offer"]["offer_id"]=="pro"
    assert not any(b["type"]=="products" for b in r["blocks"])


def test_exclusion_in_class(price_list):
    r=price_list.search(Request(q="архиваторы кроме Ладоги",mode="fast"))
    assert r["understood"]["intent"]=="category"
    assert [c["offer"]["offer_id"] for c in cards_from(r["blocks"])]==["packs"]


def test_replacement_in_russia(price_list):
    r=price_list.search(Request(q="чем заменить AureaMail в России",mode="fast"))
    b=next(b for b in r["blocks"] if b["type"]=="analogs")
    assert [i["card"]["offer"]["offer_id"] for i in b["items"]]==["rmail"]


def test_transliterated_edition(price_list):
    r=price_list.search(Request(q="yarkiy ofis bazovyy",mode="fast"))
    assert cards_from(r["blocks"])[0]["offer"]["offer_id"]=="bright"


def test_monitor_database_as_target(price_list):
    r=price_list.search(Request(q="метрики pgsql",mode="fast"))
    assert cards_from(r["blocks"])[0]["offer"]["offer_id"]=="pg"
    assert not r["understood"]["filters"].get("vendor")


def test_quote_upload_uses_main_license(price_list):
    from fastapi.testclient import TestClient
    from kuznitsa.app import create_app
    with TestClient(create_app(price_list)) as api:
        r=api.post("/api/spec/upload",params={"name":"закупка.csv","mode":"fast"},
                   content="Название;Количество\nЛадога;42".encode())
        assert r.status_code==200
        line=r.json()["blocks"][0]["lines"][0]
        assert (line["card"]["offer"]["offer_id"],line["qty"],line["total"])==("compress",42,42*710)
