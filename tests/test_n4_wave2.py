"""Тесты второго захода трека N4: бюджет, реестр, текстовые исключения, мульти-продукт и платформа."""
import json
from dataclasses import replace

import pytest

from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Disabled
from kuznitsa.plans import feed_conditions
from kuznitsa.plans.feed_compare import parse_multi
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def w2_engine(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n4_w2_feed")
    rows = []

    def add(
        oid,
        title,
        section_id,
        section_name,
        *,
        root="Программное обеспечение",
        domain="software",
        vendor="Лаборатория Касперского",
        price=1000.0,
        registry=False,
        platforms=(),
        lic=None,
    ):
        rows.append(
            dict(
                offer_id=oid,
                group_id=oid,
                name=title,
                family_name=title,
                class_id=section_id,
                category_id=section_id,
                category_path=[root, section_name],
                domain=domain,
                vendor=vendor,
                price=price,
                registry=registry,
                platforms=list(platforms),
                attrs={"domain": domain},
                lic=lic or {"model": "subscription", "term_months": 12, "metric": "device"},
                available=True,
                in_stock=True,
            )
        )

    # Антивирусы
    add("k_es", "Kaspersky Endpoint Security", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Лаборатория Касперского", price=3100, registry=True, platforms=["Windows", "macOS"])
    add("k_sc", "Kaspersky Security Center", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Лаборатория Касперского", price=4200, registry=True, platforms=["Windows"])
    add("k_std", "Kaspersky Standard", "av_home", "Антивирусы для дома", root="Безопасность", vendor="Лаборатория Касперского", price=1500, registry=True, platforms=["Windows", "macOS"])
    add("drweb_biz", "Dr.Web Enterprise Security Suite", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Доктор Веб", price=2200, registry=True, platforms=["Windows", "macOS", "Linux"])
    add("drweb_home", "Dr.Web Security Space", "av_home", "Антивирусы для дома", root="Безопасность", vendor="Доктор Веб", price=1800, registry=True, platforms=["Windows", "Android"])
    add("pro32_biz", "PRO32 Endpoint Security", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="PRO32", price=1250, registry=True, platforms=["Windows"])
    add("norton", "Norton 360 Deluxe", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="NortonLifeLock", price=3500, registry=False, platforms=["Windows"])

    # Офисные пакеты
    add("ms_off", "Microsoft Office 2024 Standard", "off_ms", "Офисные пакеты", root="Офисные приложения", vendor="Microsoft", price=18000, registry=False)
    add("ms_visio", "Microsoft Visio 2024", "off_ms", "Офисные пакеты", root="Офисные приложения", vendor="Microsoft", price=900, registry=False)
    add("r7_pro", "Р7-Офис Профессиональный", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="АО «Р7»", price=4500, registry=True)
    add("r7_home", "Р7-Офис для дома", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="АО «Р7»", price=2100, registry=True)
    add("myoff_std", "МойОфис Стандартный 2", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="МойОфис", price=5200, registry=True)
    add("myoff_pro", "МойОфис Профессиональный", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="МойОфис", price=8900, registry=True)

    # ОС и 1С
    add("win11_pro", "Microsoft Windows 11 Pro", "os_win", "Операционные системы Windows", root="Операционные системы", vendor="Microsoft", price=24900)
    add("win11_home", "Microsoft Windows 11 Home", "os_win", "Операционные системы Windows", root="Операционные системы", vendor="Microsoft", price=18900)
    add("c1_zup", "1С:Зарплата и управление персоналом 8 ПРОФ", "acc", "Бухгалтерия и кадры", root="Бизнес-приложения", vendor="1С", price=22600, registry=True)

    # Ноутбуки и мониторы (для исключений на 2 страницах)
    for idx, (vid, vname, price) in enumerate([
        ("len1", "Lenovo", 48000), ("len2", "Lenovo", 52000),
        ("asus1", "ASUS", 49000), ("acer1", "Acer", 41000),
        ("hp1", "HP", 55000), ("hp2", "HP", 62000),
        ("dell1", "Dell", 67000), ("msi1", "MSI", 71000),
        ("huawei1", "Huawei", 58000), ("apple1", "Apple", 145000),
    ], 1):
        add(f"nb_{idx}", f"Ноутбук {vname} Book {idx}", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor=vname, price=price)

    for idx, (vname, price) in enumerate([
        ("Samsung", 18000), ("LG", 19000), ("Dell", 24000), ("HP", 21000), ("AOC", 15000),
    ], 1):
        add(f"mon_{idx}", f"Монитор {vname} 24\"", "70200", "Мониторы", root="Периферия", domain="hardware", vendor=vname, price=price)

    # Периферия: комплект клавиатура+мышь
    add("combo1", "Комплект клавиатура+мышь Logitech MK270", "82833", "Клавиатуры, мыши, комплекты", root="Периферия", domain="hardware", vendor="Logitech", price=3200)
    add("kb1", "Клавиатура Logitech K120", "82833", "Клавиатуры, мыши, комплекты", root="Периферия", domain="hardware", vendor="Logitech", price=1500)
    add("mouse1", "Мышь Logitech M185", "82833", "Клавиатуры, мыши, комплекты", root="Периферия", domain="hardware", vendor="Logitech", price=1400)

    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    engine = Engine.open(replace(cfg, data=data), llm=Disabled())
    yield engine
    engine.close()


def _products_items(res):
    return [it for b in res["blocks"] if b["type"] == "products" for it in b.get("items", [])]


def _all_items(res):
    out = []
    for b in res["blocks"]:
        if b["type"] in ("products", "analogs", "crosssell"):
            for it in b.get("items", []):
                out.append(it["card"] if isinstance(it, dict) and "card" in it else it)
    return out


def test_free_software_honest_note_and_cheapest_first(w2_engine):
    res = w2_engine.search(Request(q="бесплатный антивирус", mode="fast"))
    items = _products_items(res)
    assert len(items) >= 3
    note = res["understood"]["agent_note"].lower()
    assert "бесплатн" in note
    assert "нет в каталоге" not in note
    prices = [it["price_from"] for it in items if it.get("price_from")]
    assert prices == sorted(prices)


def test_cheap_and_registry_office_suite(w2_engine):
    res_cheap = w2_engine.search(Request(q="недорогой офисный пакет", mode="fast"))
    items_cheap = _products_items(res_cheap)
    assert len(items_cheap) >= 3
    prices = [it["price_from"] for it in items_cheap if it.get("price_from")]
    assert prices == sorted(prices)
    assert all("visio" not in it["title"].lower() for it in items_cheap)

    res_reg = w2_engine.search(Request(q="офисный пакет из реестра отечественного по", mode="fast"))
    items_reg = _products_items(res_reg)
    assert len(items_reg) >= 3
    assert all("microsoft" not in it["title"].lower() for it in items_reg)
    assert res_reg["understood"]["filters"].get("registry") is True


def test_textual_exclusions_all_forms_and_pages(w2_engine):
    cases = [
        ("антивирус не касперский", ("kaspersky", "касперск")),
        ("антивирус кроме касперского", ("kaspersky", "касперск")),
        ("антивирус без dr.web", ("dr.web", "доктор веб")),
        ("ноутбук не lenovo", ("lenovo",)),
        ("ноутбук кроме asus и acer", ("asus", "acer")),
        ("антивирус -касперский", ("kaspersky", "касперск")),
        ("монитор только не samsung", ("samsung",)),
    ]
    for q, banned in cases:
        for page in (1, 2):
            res = w2_engine.search(Request(q=q, mode="fast", page=page, page_size=4))
            for it in _all_items(res):
                blob = f"{it['title']} {it['vendor']['name']}".lower()
                for b in banned:
                    assert b not in blob, f"Banned {b!r} leaked on page {page} for {q!r}: {it['title']}"
        p1 = _products_items(w2_engine.search(Request(q=q, mode="fast", page=1, page_size=4)))
        assert len(p1) >= 2, f"Too few results for {q!r}"


def test_multi_product_two_blocks_and_guards(w2_engine):
    for q in (
        "kaspersky & dr.web",
        "win+office",
        "office/windows",
        "windows и office",
        "антивирус и офис на 10 пк",
    ):
        res = w2_engine.search(Request(q=q, mode="fast"))
        pblocks = [b for b in res["blocks"] if b["type"] == "products"]
        assert len(pblocks) == 2, f"Expected 2 products blocks for {q!r}, got {[(b['type'], b.get('title')) for b in res['blocks']]}"
        total = sum(len(b["items"]) for b in pblocks)
        assert total >= 4, f"Expected >= 4 cards total for {q!r}, got {total}"
        assert res["understood"]["intent"] == "spec_list"

    # Отрицательные проверки: составные названия, комплекты и технические записи не дробятся
    for q in (
        "1С:Зарплата и управление персоналом",
        "Kaspersky Endpoint Security и Security Center",
        "клавиатура+мышь",
        "wi-fi 6",
        "24/7",
        "c++",
    ):
        res = w2_engine.search(Request(q=q, mode="fast"))
        assert res["understood"]["intent"] != "spec_list", f"False multi-product split for {q!r}"
        pblocks = [b for b in res["blocks"] if b["type"] == "products"]
        assert len(pblocks) <= 1, f"Unexpected 2 blocks for {q!r}"


def test_platform_false_positive_guard(w2_engine):
    ok = w2_engine.search(Request(q="антивирус для mac", mode="fast"))
    assert ok["understood"]["filters"].get("platform") == ["macos"]

    for q in ("игра для mac", "чехол для айфона", "мышь для mac"):
        cond = feed_conditions.extract(w2_engine, q, Request(q=q, mode="fast"))
        assert cond.platform is None, f"Unexpected platform filter {cond.platform} for {q!r}"


def test_unified_soft_vs_strict_budget(w2_engine):
    soft = w2_engine.search(Request(q="windows дешевле 5000", mode="fast"))
    assert len(_products_items(soft)) >= 1
    assert "нет" in soft["understood"]["agent_note"].lower()

    strict = w2_engine.search(Request(q="windows", mode="fast", filters={"price_max": 100}))
    assert _products_items(strict) == []
    assert strict["understood"]["zero_reason"] == "filters_too_strict"


def test_n7_api_compatibility(w2_engine):
    req = Request(q="антивирус до 5000", mode="fast")
    cond = feed_conditions.extract(w2_engine, "антивирус до 5000", req)
    for field in (
        "subject", "raw_for_analogs", "price_min", "price_max", "sort",
        "exclude_vendors", "exclude_terms", "exclude_labels",
        "origin", "registry", "platform", "service", "upgrade", "active",
    ):
        assert hasattr(cond, field)
    assert callable(feed_conditions.apply_conditions)
    assert callable(feed_conditions.populate_result)
    assert callable(feed_conditions.is_domestic_card)
    assert parse_multi(w2_engine.catalog.feed, "24/7") is None
