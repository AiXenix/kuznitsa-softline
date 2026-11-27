"""Тесты N3 (второй заход): единая нормализация ввода, опечатки/раскладка разделов и порядок главных продуктов."""
import json
from dataclasses import replace
from pathlib import Path
from shutil import copytree

import pytest

from kuznitsa.engine import Engine
from kuznitsa.index.feed_repair import strip_invisible_and_accents
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request
from kuznitsa.text import normalize


@pytest.fixture(scope="module")
def monkeypatch_r2():
    with pytest.MonkeyPatch.context() as patch:
        yield patch


@pytest.fixture(scope="module")
def n3_r2_shop(cfg, tmp_path_factory, monkeypatch_r2):
    data = tmp_path_factory.mktemp("n3_r2_catalog")
    kb = copytree(Path(__file__).resolve().parents[1] / "kb", data / "kb")
    rows = []

    def add(name, section, vendor, offers=1, price=1000, domain="software", aud=None, root="ПО"):
        lic = {"audience": aud}
        for idx in range(offers):
            rows.append(dict(
                offer_id=f"{name}__{idx}",
                group_id=name,
                name=f"{name} ({idx + 1})" if offers > 1 else name,
                family_name=name,
                vendor=vendor,
                domain=domain,
                class_id=section,
                category_id=section,
                category_path=[root, section],
                price=price,
                available=True,
                lic=lic,
            ))

    kl = "«Лаборатория Касперского»"
    add("Kaspersky Standard", "Антивирусы для организаций", kl, offers=6, price=1800, aud="home")
    add("Kaspersky Plus + Who Calls", "Антивирусы для организаций", kl, offers=6, price=2500, aud="home")
    add("Kaspersky Endpoint Security для бизнеса Стандартный", "Антивирусы для организаций", kl, offers=20, price=12000, aud="business")
    add("MDaemon Antivirus", "Антивирусы для организаций", "MDaemon", offers=5, price=5000)

    ms = "Программы и лицензии Microsoft Corporation"
    add("Microsoft Windows 11 Pro (Профессиональная)", "ОС Windows", ms, offers=4, price=15000, aud="business")
    add("Microsoft Windows 11 Home (Домашняя)", "ОС Windows", ms, offers=4, price=10000, aud="home")
    add("Microsoft Office 2024 для дома и бизнеса", "Офисные пакеты", ms, offers=4, price=25000)
    add("Microsoft Office Professional Plus 2021", "Офисные пакеты", ms, offers=10, price=30000)
    add("Microsoft Office Outlook 2021", "Офисные пакеты", ms, offers=6, price=12000)
    add("Microsoft Office Word 2021", "Офисные пакеты", ms, offers=6, price=12000)
    add("Microsoft Office Excel 2021", "Офисные пакеты", ms, offers=6, price=12000)
    add("Microsoft 365 бизнес стандарт", "Офисные пакеты", ms, offers=8, price=15000, aud="business")
    add("Microsoft 365 Family (для семьи)", "Офисные пакеты", ms, offers=4, price=11000, aud="home")

    add("Autodesk 3Ds Max", "САПР", "Autodesk", offers=8, price=90000)
    add("Autodesk AutoCAD", "САПР", "Autodesk", offers=10, price=110000)
    add("Archicad 26", "САПР", "GRAPHISOFT", offers=6, price=120000)
    add("Graphisoft Archicad 26 Forward", "САПР", "GRAPHISOFT", offers=4, price=130000)
    add("Archicad Solo", "САПР", "GRAPHISOFT", offers=3, price=80000)
    add("Archicad STAR(T) Edition", "САПР", "GRAPHISOFT", offers=3, price=70000)
    add("Платформа nanoCAD 26", "САПР", "Нанософт Разработка", offers=12, price=25000)
    add("nanoCAD Механика PRO", "САПР", "Нанософт Разработка", offers=8, price=35000)
    add("nanoCAD Землеустройство", "САПР", "Нанософт Разработка", offers=6, price=18000)
    add("nanoCAD Электро", "САПР", "Нанософт Разработка", offers=6, price=22000)
    add("КОМПАС-3D V25", "САПР", "АСКОН", offers=12, price=120000)

    add("CorelDRAW Graphics Suite 2026", "Графика", "Corel Corporation", offers=4, price=45000)
    add("Corel PaintShop Pro 2023", "Графика", "Corel Corporation", offers=12, price=12000)

    add("Astra Linux Special Edition", "Операционные системы", "Группа Астра", offers=12, price=18000)
    add("Код Безопасности Secret Net Studio", "Программы для защиты информации", "Код Безопасности", offers=10, price=9500)
    add("Код Безопасности Сертификат на комплексную техническую поддержку Secret Net Studio", "Программы для защиты информации", "Код Безопасности", offers=25, price=3000)

    add("Кибер Бэкап", "Резервное копирование", "Киберпротект", offers=10, price=14000)
    add("Dr.Web Security Space", "Антивирусы для организаций", "Доктор Веб", offers=8, price=2200)
    add("Ноутбук Lenovo ThinkPad E16", "Ноутбуки", "Lenovo", offers=5, price=75000, domain="hardware", root="Оборудование")
    add("Ноутбук Lenovo IdeaPad Slim 3", "Ноутбуки", "Lenovo", offers=4, price=55000, domain="hardware", root="Оборудование")

    # Защита от разрушающей починки
    add("Team Planner Pro", "Управление проектами", "TeamSoft", offers=8, price=2000)
    add("Pisa Graphics Studio", "Графика", "PisaSoft", offers=5, price=3000)
    add("Qi Security Monitor", "Сетевые утилиты", "QiCorp", offers=5, price=4000)

    monkeypatch_r2.setenv("KZ_KB_DIR", str(kb))
    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    e = Engine.open(replace(cfg, data=data, kb=kb), llm=Disabled())
    yield e
    e.close()


def _shown(res):
    out = []
    for blk in res.get("blocks") or []:
        if blk.get("type") in ("products", "analogs", "kit", "spec", "compare"):
            out.extend(c for c in blk.get("items") or [] if c.get("kind") != "upsell")
    return out


def _ids(res):
    return [c.get("id") or c.get("title") for c in _shown(res)]


def _titles(res):
    return [c.get("title", "") for c in _shown(res)]


def test_strip_invisible_and_accents_preserves_ru_letters():
    cleaned, changed = strip_invisible_and_accents("ка\u200bспе\u0301рский йё")
    assert changed is True
    assert cleaned == "касперский йё"

    fw, changed_fw = strip_invisible_and_accents("ａｎｔｉｖｉｒｕｓ")
    assert changed_fw is True
    assert fw == "antivirus"


@pytest.mark.parametrize("raw,expected", [
    ("антивирус 😀", "антивирус"),
    ("(антивирус)", "антивирус"),
    ("антивирус!!!", "антивирус"),
    ("  антивирус  ", "антивирус"),
    ("АНТИВИРУС", "антивирус"),
    ("ａｎｔｉｖｉｒｕｓ", "antivirus"),
    ("\"касперский\"", "касперский"),
    ("«касперский»?", "касперский"),
    ("[windows 11]", "windows 11"),
    ("windows  11.", "windows 11"),
    ("ноутбук, lenovo", "ноутбук lenovo"),
    ("антивирус: касперский", "антивирус касперский"),
    ("ка\u200bсперский", "касперский"),
    ("каспе\u0301рский", "касперский"),
    ("m$ office", "ms office"),
])
def test_clean_query_formatting_normalization(n3_r2_shop, raw, expected):
    rec = n3_r2_shop.catalog.feed.recovery
    assert rec.clean_query(normalize(raw)) == expected


@pytest.mark.parametrize("raw,expected", [
    ("c++", "c++"),
    ("c#", "c#"),
    ("1с", "1с"),
    (".net", ".net"),
    ("wi-fi 6", "wi-fi 6"),
    ("24/7", "24/7"),
    ("dr.web", "dr.web"),
    ("x64", "x64"),
    ("kl4863ratfs", "kl4863ratfs"),
    ('монитор 27"', 'монитор 27"'),
    ("экран 10,5", "экран 10,5"),
    ("autocad, чем заменить", "autocad, чем заменить"),
])
def test_clean_query_preserves_meaningful_tokens(n3_r2_shop, raw, expected):
    rec = n3_r2_shop.catalog.feed.recovery
    assert rec.clean_query(normalize(raw)) == expected


@pytest.mark.parametrize("blank", ["", "   ", "!!!", "???", "😀", ".", "*"])
def test_clean_query_does_not_mangle_blank_or_symbol_only(n3_r2_shop, blank):
    rec = n3_r2_shop.catalog.feed.recovery
    norm = normalize(blank)
    assert rec.clean_query(norm) == norm


@pytest.mark.parametrize("a,b", [
    ("антивирус", "антивирус 😀"),
    ("антивирус", "(антивирус)"),
    ("антивирус", "антивирус!!!"),
    ("антивирус", "  антивирус  "),
    ("антивирус", "АНТИВИРУС"),
    ("antivirus", "ａｎｔｉｖｉｒｕｓ"),
    ("касперский", "КАСПЕРСКИЙ"),
    ("касперский", '"касперский"'),
    ("касперский", "«касперский»?"),
    ("windows 11", "[windows 11]"),
    ("windows 11", "windows  11."),
    ("dr web", "dr-web"),
    ("ноутбук lenovo", "ноутбук, lenovo"),
    ("ноутбук lenovo", "ноутбук LENOVO"),
    ("office 365", "office365"),
    ("office 365", "o365"),
    ("антивирус касперский", "антивирус: касперский"),
    ("касперский", "ка\u200bсперский"),
    ("касперский", "каспе\u0301рский"),
])
def test_formatting_pairs_identical_top4_and_intent(n3_r2_shop, a, b):
    x = n3_r2_shop.search(Request(q=a, mode="fast"))
    y = n3_r2_shop.search(Request(q=b, mode="fast"))
    assert _ids(x), f"No results for {a!r}"
    assert _ids(x)[:4] == _ids(y)[:4], f"Top-4 mismatch for {a!r} vs {b!r}: {_titles(x)[:4]} != {_titles(y)[:4]}"
    assert x.get("intent") == y.get("intent"), f"Intent mismatch for {a!r} vs {b!r}: {x.get('intent')} != {y.get('intent')}"


@pytest.mark.parametrize("q,expect", [
    ("3d max", "3Ds Max"),
    ("3d макс", "3Ds Max"),
    ("3д макс", "3Ds Max"),
    ("m$ office", "Microsoft Office"),
    ("мс офис", "Microsoft Office"),
    ("ворд", "Word"),
    ("эксель", "Excel"),
    ("аутлук", "Outlook"),
    ("архикад", "Archicad"),
])
def test_round2_aliases_and_flagships(n3_r2_shop, q, expect):
    titles = _titles(n3_r2_shop.search(Request(q=q, mode="fast")))
    assert titles and expect.lower() in titles[0].lower(), f"Expected {expect!r} first for {q!r}, got {titles[:3]}"


def test_has_verb_ignores_typos_and_layout(n3_r2_shop):
    rec = n3_r2_shop.catalog.feed.recovery
    assert rec.has_verb("касперскй") is False
    assert rec.has_verb("фгещсфв") is False
    assert rec.has_verb("купить антивирус") is True


def test_repair_class_layout_and_typos_and_protection(n3_r2_shop):
    rec = n3_r2_shop.catalog.feed.recovery
    sec, fixed, kind = rec.repair_class("jabc")
    assert sec is not None and fixed == "офис" and kind == "layout"

    sec2, fixed2, kind2 = rec.repair_class("резервное копированее")
    assert sec2 is not None and "копирование" in fixed2 and kind2 == "typo"

    sec3, fixed3, kind3 = rec.repair_class("антивирс для организаци")
    assert sec3 is not None and "антивирус" in fixed3 and kind3 == "typo"

    # Защита первого захода не нарушается
    for protected in ("steam", "пицца", "кии"):
        p_sec, _, _ = rec.repair_class(protected)
        assert p_sec is None


def test_brand2_ordering_and_demote_and_vendor_guards(n3_r2_shop):
    # Corel vendor query puts CorelDRAW Graphics Suite ahead of PaintShop Pro
    corel = _titles(n3_r2_shop.search(Request(q="corel", mode="fast")))
    assert corel and corel[0] == "CorelDRAW Graphics Suite 2026"

    # «код безопасности» не теряет «код » и ставит Secret Net Studio выше сертификата техподдержки
    kb_res = _titles(n3_r2_shop.search(Request(q="код безопасности", mode="fast")))
    assert kb_res and kb_res[0] == "Код Безопасности Secret Net Studio"

    # «нанокад» и «архикад» отдают всю линейку, а не 1 карточку
    nano = _titles(n3_r2_shop.search(Request(q="нанокад", mode="fast")))
    assert len(nano) >= 4 and nano[0] == "Платформа nanoCAD 26"
    archi = _titles(n3_r2_shop.search(Request(q="архикад", mode="fast")))
    assert len(archi) >= 4 and archi[0] == "Archicad 26"

    # «астра линукс» и «компас 3d» — прямой товар, не vendor_gap
    for q, expect in [("астра линукс", "Astra Linux"), ("компас 3d", "КОМПАС-3D")]:
        res = n3_r2_shop.search(Request(q=q, mode="fast"))
        titles = _titles(res)
        assert titles and expect.lower() in titles[0].lower()
        assert res.get("intent") != "vendor_gap"
