"""Тесты потока N1: правда о наличии, покупательский шум, разрушительные исправления и чистые ответы на мусор."""
from dataclasses import replace
import json
from shutil import copytree

import pytest
import yaml

from kuznitsa.config import Config
from kuznitsa.engine import Engine
from kuznitsa.evaluation import cards_from
from kuznitsa.llm.jev import Disabled
from kuznitsa.plans import feed_guard, feed_noise
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def n1_engine(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n1_feed")
    kb = copytree(Config().kb, data / "kb")

    rows = []

    def add(cid, title, section, vendor, *, domain="software", price=25000, family=None, qty_max=100):
        rows.append(
            dict(
                group_id=cid,
                offer_id=f"{cid}-1",
                family_id=family or cid,
                family_name=title,
                name=title,
                domain=domain,
                category_id=section,
                class_id=section,
                category_path=["Программы" if domain == "software" else "Оборудование", section],
                vendor=vendor,
                price=price,
                available=True,
                lic=dict(metric="device", qty_min=1, qty_max=qty_max),
            )
        )

    add("win11_pro", "Microsoft Windows 11 Pro", "Операционные системы", "Microsoft", price=28000)
    add("win11_home", "Microsoft Windows 11 Home", "Операционные системы", "Microsoft", price=20183)
    add("win10_pro", "Microsoft Windows 10 Pro", "Операционные системы", "Microsoft", price=24000)
    add("win_srv", "Microsoft Windows Server 2022 Standard", "Серверное ПО", "Microsoft", price=95000)
    add("dt_win7", "Vision Solutions Double-Take Availability для Windows 7.0", "Резервное копирование", "Vision Solutions", price=50000)
    add("office_std", "Microsoft Office Standard 2021", "Офисные пакеты", "Microsoft", price=42000)
    add("office_pro", "Microsoft Office Профессиональный 2021", "Офисные пакеты", "Microsoft", price=54000)
    add("access_2021", "Microsoft Access 2021", "Офисные пакеты", "Microsoft", price=18000)
    add("pub_2021", "Microsoft Publisher 2021", "Офисные пакеты", "Microsoft", price=18000)
    add("m365", "Microsoft 365 Бизнес Стандарт", "Офисные пакеты", "Microsoft", price=15000)
    add("acrobat", "Adobe Acrobat Professional", "Редакторы PDF", "Adobe", price=31000)
    add("photoshop", "Adobe Photoshop", "Графические редакторы", "Adobe", price=35000)
    add("cc", "Adobe Creative Cloud", "Графические редакторы", "Adobe", price=89000)
    add("illustrator", "Adobe Illustrator", "Графические редакторы", "Adobe", price=34000)
    add("premiere", "Adobe Premiere Pro", "Видеоредакторы", "Adobe", price=36000)
    add("autocad", "Autodesk AutoCAD", "САПР", "Autodesk", price=120000)
    add("corel", "CorelDRAW", "Графические редакторы", "Corel", price=45000)
    add("winrar", "WinRAR", "Архиваторы", "RARLAB", price=4500)
    add("kes", "Kaspersky Endpoint Security", "Антивирусы для организаций", "Лаборатория Касперского", price=12000)
    add("kes_course", "Kaspersky Endpoint Security Express Course", "Обучение", "Лаборатория Касперского", price=5000)
    add("drweb", "Dr.Web Security Space", "Антивирусы для организаций", "Доктор Веб", price=9000)
    add("kompas", "КОМПАС-3D", "САПР", "АСКОН", price=110000)
    add("lotsman", "ЛОЦМАН:PLM", "САПР", "АСКОН", price=150000)
    add("vertical", "ВЕРТИКАЛЬ", "САПР", "АСКОН", price=130000)
    add("polynom", "ПОЛИНОМ:MDM", "САПР", "АСКОН", price=140000)
    add("team_tool", "Team Foundation Server", "Разработка", "Microsoft", price=60000)
    add("pisa_cooler", "Кулер Процессорный JONSBO для CPU PISA A5 ARGB", "Охлаждение", "JONSBO", domain="hardware", price=2500)
    add("blender_hw", "Блендер стационарный Kitfort", "Техника", "Kitfort", domain="hardware", price=4500)

    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return Engine.open(replace(cfg, kb=kb, data=data), llm=Disabled())


@pytest.mark.parametrize("query", [
    "123456789",
    "<script>alert(1)</script>",
    "' OR 1=1 --",
    "???",
    "а",
    "asdfghjkl",
    "рецепт борща",
    "погода в москве",
    "пицца",
])
def test_garbage_returns_zero_cards_and_no_destructive_fix(n1_engine, query):
    res = n1_engine.search(Request(q=query, mode="fast"))
    assert cards_from(res["blocks"]) == [], query
    assert res["understood"]["zero_reason"] == "unknown_term", query
    assert res["query"]["corrections"] == [], query
    assert any(b["type"] == "clarify" and b.get("options") for b in res["blocks"]), query
    assert res["related_queries"], query


def test_steam_not_corrected_to_team_and_honest_absent(n1_engine):
    res = n1_engine.search(Request(q="steam", mode="fast"))
    assert res["understood"]["intent"] == "out_of_catalog"
    assert res["understood"]["zero_reason"] == "not_in_catalog"
    assert res["query"]["corrections"] == []
    assert any(b["type"] == "not_in_catalog" for b in res["blocks"])
    assert cards_from(res["blocks"]) == []


def test_windows_7_missing_generation_shows_windows_11_10(n1_engine):
    res = n1_engine.search(Request(q="windows 7", mode="fast"))
    assert res["understood"]["intent"] == "out_of_catalog"
    assert res["understood"]["zero_reason"] == "not_in_catalog"
    assert res["blocks"][0]["type"] == "not_in_catalog"
    titles = [c["title"].lower() for c in cards_from(res["blocks"])]
    assert titles and ("windows 11" in titles[0] or "windows 10" in titles[0])


def test_upgrade_query_not_treated_as_price_max(n1_engine):
    res = n1_engine.search(Request(q="апгрейд windows 10 до 11", mode="fast"))
    assert "price_max" not in res["understood"]["filters"]
    assert res["understood"]["zero_reason"] is None
    titles = [c["title"].lower() for c in cards_from(res["blocks"])]
    assert any("windows 11" in t for t in titles[:3])


def test_soft_budget_keeps_cheapest_product_cards(n1_engine):
    res = n1_engine.search(Request(q="windows дешевле 15000", mode="fast"))
    assert res["understood"]["zero_reason"] is None
    cards = cards_from(res["blocks"])
    assert cards and "windows" in cards[0]["title"].lower()
    assert cards[0]["card_id"] == "win11_home"


@pytest.mark.parametrize("query,expected", [
    ("Adobe Acrobat Pro", "acrobat"),
    ("adobe acrobat pro dc подписка на год для команд", "acrobat"),
    ("autocad 2025", "autocad"),
    ("автокад лт", "autocad"),
    ("coreldraw graphics suite 2024", "coreldraw"),
    ("office365 e3", "365"),
    ("MS Windows Server Standard 2022 16 core", "windows server"),
    ("windows 11 pro oem", "windows 11 pro"),
    ("windows 11 pro для юрлиц", "windows 11 pro"),
    ("x64 windows 11 home", "windows 11 home"),
    ("ключ активации windows 11", "windows 11"),
    ("скачать winrar", "winrar"),
    ("хочу купить фотошоп навсегда без подписки", "photoshop"),
    ("фш", "photoshop"),
    ("бессрочная лицензия office", "office"),
    ("электронная лицензия office", "office"),
    ("обновление компас-3d", "компас-3d"),
    ("dr.web 5 пк 3 года", "dr.web"),
    ("коробочная версия касперский", "kaspersky"),
])
def test_present_products_with_noise_and_relaxation(n1_engine, query, expected):
    res = n1_engine.search(Request(q=query, mode="fast"))
    assert res["understood"]["zero_reason"] is None, (query, res["understood"])
    assert not any(b["type"] == "not_in_catalog" for b in res["blocks"]), query
    titles = [c["title"].lower() for c in cards_from(res["blocks"])[:3]]
    assert any(expected in t for t in titles), (query, titles)
    if query == "коробочная версия касперский":
        assert "express course" not in titles[0]


def test_vendor_catalog_queries(n1_engine):
    for q, needle in [("всё от adobe", "adobe"), ("продукты Аскон", "компас")]:
        res = n1_engine.search(Request(q=q, mode="fast"))
        assert res["understood"]["zero_reason"] is None
        cards = cards_from(res["blocks"])
        assert len(cards) >= 4
        assert any(needle in c["title"].lower() for c in cards[:3])


def test_office_2021_prefers_suite_over_standalone(n1_engine):
    res = n1_engine.search(Request(q="microsoft office 2021", mode="fast"))
    cards = cards_from(res["blocks"])
    assert cards
    top = cards[0]["title"].lower()
    assert "office standard 2021" in top or "office профессиональный 2021" in top


def test_clean_analog_subject_strips_modifiers():
    assert feed_noise.clean_analog_subject("autocad дешевле") == "autocad"
    assert feed_noise.clean_analog_subject("бесплатный photoshop российский") == "photoshop"


def test_verify_response_strips_empty_blocks_and_overrides_false_absence(n1_engine):
    req = Request(q="Adobe Photoshop", mode="fast")
    profile = n1_engine.clients["guest"]
    fake = dict(
        search_id="s_test",
        engine="kuznitsa",
        engine_version="1.0",
        mode="fast",
        query=dict(raw=req.q, normalized="adobe photoshop", corrected="adobe photoshop", corrections=[], did_you_mean=None),
        understood=dict(intent="out_of_catalog", intent_title="Нет в каталоге", zero_reason="not_in_catalog", filters={}, exclude={}, entities=[], chips=[], agent_note="Ушёл"),
        blocks=[
            dict(type="not_in_catalog", title="Нет в каталоге", reason="vendor_left", text="Вендор ушёл"),
            dict(type="kit", title="Пустой комплект", slots=[]),
            dict(type="compare", title="Пустое сравнение", columns=[]),
        ],
        related_queries=[],
    )
    fixed = feed_guard.verify_response(n1_engine, req, profile, fake, from_legacy=True)
    assert fixed["understood"]["intent"] == "product"
    assert fixed["understood"]["zero_reason"] is None
    assert not any(b["type"] in ("not_in_catalog", "kit", "compare") for b in fixed["blocks"])
    assert any("photoshop" in c["title"].lower() for c in cards_from(fixed["blocks"]))
