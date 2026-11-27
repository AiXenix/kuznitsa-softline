"""Тесты раунда 3 потока N1: ослабление пустых ответов, раскладка и опечатки с точкой, поколения в наличии и заполнители брендов."""
from dataclasses import replace
import json
from shutil import copytree

import pytest

from kuznitsa.config import Config
from kuznitsa.engine import Engine, Trace
from kuznitsa.evaluation import cards_from
from kuznitsa.llm.jev import Disabled
from kuznitsa.plans import feed as feed_plan, feed_guard
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def n1_r3_engine(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n1_r3_feed")
    kb = copytree(Config().kb, data / "kb")

    rows = []

    def add(cid, title, section, vendor, *, domain="software", price=25000, offers=1, lic=None):
        root = "Оборудование" if domain == "hardware" else "Программы"
        for i in range(offers):
            rows.append(
                dict(
                    group_id=cid,
                    offer_id=f"{cid}-{i + 1}",
                    family_id=cid,
                    family_name=title,
                    name=f"{title} (вариант {i + 1})" if i else title,
                    domain=domain,
                    category_id=section,
                    class_id=section,
                    category_path=[root, section],
                    vendor=vendor,
                    price=price + i * 100,
                    available=True,
                    lic=lic or dict(metric="device", qty_min=1, qty_max=100),
                )
            )

    # ПО с точками, поколениями, разработкой, ЭДО, мессенджерами и САПР
    add("kontur_tolk", "Контур.Толк", "Программное обеспечение для онлайн общения", "СКБ Контур", price=12000, offers=4)
    add("express", "eXpress", "Программное обеспечение для онлайн общения", "Анлимитед Продакшен", price=14000, offers=3)
    add("vkurse", "ВКУРСЕ CLASSIC", "Программное обеспечение для онлайн общения", "ВКУРСЕ", price=15000, offers=3)
    add("aspro_fin", "Аспро.Финансы", "Финансовое программное обеспечение", "Аспро", price=18000, offers=3)
    add("aspro_cloud", "Аспро.Cloud", "Программное обеспечение для управления проектами", "Аспро", price=19000, offers=3)
    add("b24_market", "1С-Битрикс24.Маркет", "Программное обеспечение для управления бизнесом", "1С-Битрикс", price=22000, offers=3)
    add("spire_doc", "Spire.Doc", "Программы для разработки ПО", "E-iceblue", price=45000, offers=3)
    add("aspose_cells", "Aspose.Cells", "Программы для разработки ПО", "Aspose", price=65000, offers=3)
    add("openoffice", "OpenOffice.org", "Офисные пакеты", "Apache", price=1000, offers=2)
    add("gitflic", "GitFlic", "Программы для разработки ПО", "Ресолют", price=35000, offers=4)
    add("altova", "Altova UModel 2026", "Программы для разработки ПО", "Altova", price=42000, offers=3)
    add("drweb_ss", "Dr.Web Security Space", "Антивирусы для дома", "Доктор Веб", price=2500, offers=5)
    add("drweb_ent", "Dr.Web Enterprise Security Suite", "Антивирусы для организаций", "Доктор Веб", price=9500, offers=5)
    add("ti_ng", "Traffic Inspector Next Generation", "Межсетевые экраны", "Смарт-Софт", price=55000, offers=4)
    add("win11_pro", "Microsoft Windows 11 Pro (Профессиональная)", "Операционные системы", "Microsoft", price=28000, offers=5)
    add("win10_pro", "Microsoft Windows 10 Pro (GGWA)", "Операционные системы", "Microsoft", price=24000, offers=4)
    add("win10_ent", "Microsoft Windows 10 Enterprise", "Операционные системы", "Microsoft", price=32000, offers=3)
    add("office_2019", "Microsoft Office Standard 2019", "Офисные пакеты программ Microsoft Office", "Microsoft", price=38000, offers=4)
    add("ws_2019", "Microsoft Windows Server Essentials 2019", "Серверные ОС", "Microsoft", price=64000, offers=3)
    add("acad_2024", "Autodesk AutoCAD Revit LT Suite 2024", "Базовые программы", "Autodesk", price=125000, offers=3)
    add("pilot_ecm", "Pilot-ECM", "Программы для документооборота", "АСКОН", price=72000, offers=4)
    add("pilot_ice", "Pilot-ICE", "Программы для документооборота", "АСКОН", price=68000, offers=4)
    add("etax", "e-BS ETAXREPORT", "Программное обеспечение для бухгалтерии", "e-BS", price=19000, offers=3)
    add("kompas_home", "КОМПАС-3D HOME", "Программы для машиностроения", "АСКОН", price=5000, offers=3)
    add("kompas_v25", "КОМПАС-3D V25", "Программы для машиностроения", "АСКОН", price=110000, offers=6)
    add("kompas_gr", "КОМПАС-График V25", "Программы для машиностроения", "АСКОН", price=75000, offers=4)
    add("nanocad_26", "Платформа nanoCAD 26", "Базовые программы", "Нанософт", price=65000, offers=5)

    # Оборудование: кабели, роутеры, флешки, ноутбуки
    add("hdmi_2", "Buro BHP HDMI 2", "Кабели, переходники, разъемы", "Buro", domain="hardware", price=550, offers=2)
    add("hdmi_3", "Buro BHP HDMI 3", "Кабели, переходники, разъемы", "Buro", domain="hardware", price=690, offers=2)
    add("utp_5e", "Buro Витая пара cat5E", "Кабели, переходники, разъемы", "Buro", domain="hardware", price=490, offers=3)
    add("router_bd4", "Wi-Fi роутер ASUS BD4", "Wi-Fi роутеры", "ASUS", domain="hardware", price=9900, offers=4)
    add("router_xp4", "Wi-Fi роутер ASUS XP4", "Wi-Fi роутеры", "ASUS", domain="hardware", price=12900, offers=3)
    add("flash_64", "Флешка Netac UM2 64GB", "Флешки USB", "Netac", domain="hardware", price=890, offers=3)
    add("flash_32", "Флешка Netac UM2 32GB", "Флешки USB", "Netac", domain="hardware", price=590, offers=2)
    add("nb_i7", "Ноутбук MSI Modern Intel Core i7-14650HX 16GB", "Ноутбуки", "MSI", domain="hardware", price=89000, offers=3)
    add("nb_ryzen", "Ноутбук ASUS VivoBook AMD Ryzen 7", "Ноутбуки", "ASUS", domain="hardware", price=74000, offers=2)

    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return Engine.open(replace(cfg, kb=kb, data=data), llm=Disabled())


def _direct(eng, q):
    req = Request(q=q, mode="fast", source="eval")
    res = feed_plan.search(eng, req, eng.clients["guest"], Trace(eng.timer), (), False)
    assert res is not None, f"Query fell back to legacy engine: {q!r}"
    return res


# --- Пункт 1: Пустой ответ + ослабление запроса ---
@pytest.mark.parametrize("q,expected_sub", [
    ("кабель hdmi 2 м", "hdmi"),
    ("wifi маршрутизатор гигабитный", "роутер"),
    ("роутер wi-fi 6", "роутер"),
    ("флешка 64 гб", "64gb"),
    ("средства программирования на 12 рабочих мест", "gitflic"),
    ("ноутбук 16 гб i7", "ноутбук"),
])
def test_unmatched_query_relaxes_instead_of_empty(n1_r3_engine, q, expected_sub):
    res = _direct(n1_r3_engine, q)
    cards = cards_from(res["blocks"])
    assert cards, f"Empty cards for {q!r}"
    assert res["understood"]["zero_reason"] is None
    assert "Показаны товары по части запроса" in (res["understood"].get("agent_note") or "")
    assert any(t["step"] == "relax" for t in res["trace"])
    assert any(expected_sub in c["title"].lower() for c in cards[:3]), [c["title"] for c in cards[:3]]


def test_telegram_returns_out_of_catalog_with_messengers(n1_r3_engine):
    res = _direct(n1_r3_engine, "телеграм")
    assert res["understood"]["intent"] == "out_of_catalog"
    assert any(b["type"] == "not_in_catalog" for b in res["blocks"])
    titles = [c["title"].lower() for c in cards_from(res["blocks"])[:4]]
    assert any("контур.толк" in t or "express" in t or "вкурсе" in t for t in titles), titles


@pytest.mark.parametrize("garbage", ["", "   ", "!!!", "???", "😀", ".", "*", "а", "z", "asdfghjkl", "пицца", "рецепт борща"])
def test_relaxation_never_triggers_on_garbage_or_empty(n1_r3_engine, garbage):
    res = n1_r3_engine.search(Request(q=garbage, mode="fast", source="eval"))
    assert cards_from(res["blocks"]) == [], garbage
    assert res["understood"]["zero_reason"] == "unknown_term", garbage


# --- Пункт 2: Раскладка с точкой и запятой внутри ---
@pytest.mark.parametrize("bad_q,expected", [
    ("rjyneh.njkr", "контур.толк"),
    ("lh.dt,", "dr.web"),
    ("fcghj.abyfycs", "аспро.финансы"),
    ("fcghj.cloud", "аспро.cloud"),
    ("1c-,bnhbrc24.vfhrtn", "1с-битрикс24.маркет"),
    ("вк.цуи", "dr.web"),
    ("ызшку.вщс", "spire.doc"),
    ("фызщыу.судды", "aspose.cells"),
    ("щзутщаашсу.щкп", "openoffice.org"),
])
def test_layout_recovery_with_dot_and_comma(n1_r3_engine, bad_q, expected):
    res = _direct(n1_r3_engine, bad_q)
    cards = cards_from(res["blocks"])
    assert cards, bad_q
    assert res["understood"]["intent"] == "product"
    assert expected in cards[0]["title"].lower(), (bad_q, [c["title"] for c in cards[:3]])


# --- Пункт 3: Название с точкой и опечаткой не объявляется отсутствующим ---
@pytest.mark.parametrize("typo_q,expected", [
    ("контур.тлок", "контур.толк"),
    ("контур.толг", "контур.толк"),
    ("dr.web secruity space", "dr.web security space"),
    ("traffic inspector next generaiton", "traffic inspector next generation"),
    ("spire.dco", "spire.doc"),
    ("aspose.celss", "aspose.cells"),
])
def test_dotted_and_multiword_typos_recover_before_absent(n1_r3_engine, typo_q, expected):
    res = _direct(n1_r3_engine, typo_q)
    cards = cards_from(res["blocks"])
    assert cards, typo_q
    assert res["understood"]["intent"] == "product", typo_q
    assert res["understood"]["zero_reason"] is None, typo_q
    assert expected in cards[0]["title"].lower(), (typo_q, [c["title"] for c in cards[:3]])


# --- Пункт 4: Поколение есть в каталоге — не «Нет в каталоге» ---
@pytest.mark.parametrize("q,expected", [
    ("можно ли купить windows 10", "windows 10"),
    ("windows 10", "windows 10"),
    ("office 2019", "2019"),
    ("windows server 2019", "2019"),
    ("autocad 2024", "2024"),
])
def test_present_generation_is_never_marked_absent(n1_r3_engine, q, expected):
    res = n1_r3_engine.search(Request(q=q, mode="fast", source="eval"))
    assert res["understood"]["intent"] == "product", q
    assert res["understood"]["zero_reason"] is None, q
    assert not any(b["type"] == "not_in_catalog" for b in res["blocks"]), q
    cards = cards_from(res["blocks"])
    assert cards and any(expected in c["title"].lower() for c in cards[:3]), (q, [c["title"] for c in cards[:3]])


def test_missing_generation_windows_7_remains_honestly_absent(n1_r3_engine):
    res = n1_r3_engine.search(Request(q="windows 7", mode="fast", source="eval"))
    assert res["understood"]["intent"] == "out_of_catalog"
    assert any(b["type"] == "not_in_catalog" for b in res["blocks"])
    titles = [c["title"].lower() for c in cards_from(res["blocks"])[:3]]
    assert any("windows 11" in t or "windows 10" in t for t in titles), titles


# --- Пункт 5: Заполнитель отсутствующего бренда по его классу ---
@pytest.mark.parametrize("q,expected_sub", [
    ("сбис", "pilot"),
    ("контур диадок", "pilot"),
    ("rjyneh.lbfljr", "pilot"),
    ("компас 3д лт", "компас-3d"),
    ("компас 3d lt", "компас-3d"),
])
def test_absent_brand_fills_with_same_class_replacements(n1_r3_engine, q, expected_sub):
    res = _direct(n1_r3_engine, q)
    assert res["understood"]["intent"] == "out_of_catalog", q
    assert any(b["type"] == "not_in_catalog" for b in res["blocks"]), q
    titles = [c["title"].lower() for c in cards_from(res["blocks"])[:4]]
    assert any(expected_sub in t for t in titles), (q, titles)
    assert not any("справочник" in t or "гис" in t for t in titles), (q, titles)


def test_unknown_absent_brand_from_legacy_has_no_random_filler(n1_r3_engine):
    req = Request(q="неизвестныйбренд99", mode="fast", source="eval")
    fake_legacy = dict(
        search_id="s_test",
        engine="kuznitsa",
        engine_version="1.0",
        mode="fast",
        query=dict(raw=req.q, normalized="неизвестныйбренд99", corrected="неизвестныйбренд99", corrections=[], did_you_mean=None),
        understood=dict(intent="out_of_catalog", zero_reason="not_in_catalog", filters={}, entities=[]),
        blocks=[
            dict(type="not_in_catalog", title="Нет в каталоге", reason="not_in_catalog", text="Нет"),
            dict(type="clarify", title="Уточните раздел", question="Выберите раздел", options=[dict(label="САПР", apply=dict(q="САПР"))]),
            dict(type="products", title="Примеры", items=[dict(card_id="utp_5e", title="Учебные справочники", vendor={"name": "X"}, category={"title": "Y"})]),
        ],
    )
    cleaned = feed_guard.verify_response(n1_r3_engine, req, n1_r3_engine.clients["guest"], fake_legacy, from_legacy=True)
    assert cards_from(cleaned["blocks"]) == []
    assert [b["type"] for b in cleaned["blocks"]] == ["not_in_catalog", "clarify"]
