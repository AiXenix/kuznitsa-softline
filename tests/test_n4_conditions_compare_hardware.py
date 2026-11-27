"""Тесты трека N4: условия покупки, сравнение продуктов, периферия и оборудование."""
import json
from dataclasses import replace

import pytest

from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Disabled
from kuznitsa.plans.feed_compare import parse_compare
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def n4_engine(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n4_feed")
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
        operation="",
        description="",
        gid=None,
        lic=None,
    ):
        rows.append(
            dict(
                offer_id=oid,
                group_id=gid or oid,
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
                attrs={"operation": operation, "domain": domain},
                description=description,
                lic=lic or {"model": "subscription", "term_months": 12, "metric": "device"},
                available=True,
                in_stock=True,
            )
        )

    # Антивирусы (разные вендоры, цены, платформы)
    add("k_std", "Kaspersky Standard", "av", "Антивирусы для дома", root="Безопасность", vendor="Лаборатория Касперского", price=1500, registry=True, platforms=["Windows", "macOS", "Android"])
    add("k_plus", "Kaspersky Plus", "av", "Антивирусы для дома", root="Безопасность", vendor="Лаборатория Касперского", price=2500, registry=True, platforms=["Windows", "macOS"])
    add("drweb", "Dr.Web Security Space", "av", "Антивирусы для дома", root="Безопасность", vendor="Доктор Веб", price=1800, registry=True, platforms=["Windows", "Android"])
    add("pro32", "PRO32 Ultimate Security", "av", "Антивирусы для дома", root="Безопасность", vendor="PRO32", price=990, registry=True, platforms=["Windows"])
    add("norton", "Norton 360 Deluxe", "av", "Антивирусы для дома", root="Безопасность", vendor="NortonLifeLock", price=3500, registry=False, platforms=["Windows", "macOS"])
    add("av_mac", "Dr.Web Antivirus для macOS", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Доктор Веб", price=2100, registry=True, platforms=["macOS"], description="Защита для macOS")
    add("av_and", "Dr.Web Security Space для Android", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Доктор Веб", price=790, registry=True, platforms=["Android"], description="Мобильный антивирус Android")
    add("av_biz_k", "Kaspersky Endpoint Security", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Лаборатория Касперского", price=3100, registry=True, platforms=["Windows", "Linux"])
    add("av_biz_p", "PRO32 Endpoint Security", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="PRO32", price=1250, registry=True, platforms=["Windows"])

    # Офисные пакеты (Microsoft + российские в соседнем разделе)
    add("ms_off", "Microsoft Office 2024", "off_ms", "Офисные пакеты", root="Офисные приложения", vendor="Microsoft", price=18000, registry=False)
    add("r7", "Р7-Офис Профессиональный", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="АО «Р7»", price=4500, registry=True)
    add("myoff", "МойОфис Стандартный 2", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="МойОфис", price=5200, registry=True)
    add("r7_home", "Р7-Офис для дома", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="АО «Р7»", price=2100, registry=True)
    add("myoff_pro", "МойОфис Профессиональный", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="МойОфис", price=8900, registry=True)
    add("workspad", "Workspad", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="РуПост", price=3000, registry=True)

    # Операционные системы + техподдержка + апгрейд
    add("win11_home", "Microsoft Windows 11 Home", "os_win", "Операционные системы Windows", root="Операционные системы", vendor="Microsoft", price=18900, lic={"model": "perpetual", "metric": "device"})
    add("win11_pro", "Microsoft Windows 11 Pro", "os_win", "Операционные системы Windows", root="Операционные системы", vendor="Microsoft", price=24900, lic={"model": "perpetual", "metric": "device"})
    add("astra_lic", "Astra Linux Special Edition", "os_ru", "Российские операционные системы (Импортозамещение)", root="Операционные системы", vendor="Группа Астра", price=15000, registry=True, gid="astra_se")
    add("astra_sup", "Сертификат техподдержки Astra Linux Special Edition 12 мес.", "os_ru", "Российские операционные системы (Импортозамещение)", root="Операционные системы", vendor="Группа Астра", price=4200, registry=True, operation="Техподдержка", gid="astra_se", lic={"action": "support", "term_months": 12})
    add("redos", "РЕД ОС 8", "os_ru", "Российские операционные системы (Импортозамещение)", root="Операционные системы", vendor="РЕД СОФТ", price=9800, registry=True)
    add("alt", "Альт Рабочая станция", "os_ru", "Российские операционные системы (Импортозамещение)", root="Операционные системы", vendor="Базальт СПО", price=7500, registry=True)

    # Ноутбуки (диапазон цен и сортировка)
    add("nb1", "Ноутбук Acer Extensa 15", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="Acer", price=39900)
    add("nb2", "Ноутбук Lenovo IdeaPad 3", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="Lenovo", price=48500)
    add("nb3", "Ноутбук HP ProBook 450", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="HP", price=74000)
    add("nb4", "Ноутбук Apple MacBook Pro 16", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="Apple", price=185000)

    # Принтеры: торговые (91774, без HP) и офисные (93995, с HP)
    add("tr_pr1", "Принтер этикеток Zebra ZD220", "91774", "Принтеры", root="Торговое оборудование", domain="hardware", vendor="Zebra", price=22000)
    add("hp_pr1", "Принтер HP LaserJet Pro M404dn", "93995", "Принтеры и МФУ", root="Офисная техника", domain="hardware", vendor="HP", price=31000)
    add("hp_pr2", "МФУ HP LaserJet M141w", "93995", "Принтеры и МФУ", root="Офисная техника", domain="hardware", vendor="HP", price=26000)
    add("ky_pr1", "Принтер Kyocera ECOSYS P2040dn", "93995", "Принтеры и МФУ", root="Офисная техника", domain="hardware", vendor="Kyocera", price=35000)

    # Составные разделы периферии
    # Клавиатуры, мыши, комплекты (82833)
    add("combo1", "Комплект клавиатура+мышь Logitech MK270", "82833", "Клавиатуры, мыши, комплекты", root="Периферия", domain="hardware", vendor="Logitech", price=3200)
    add("mouse1", "Мышь Logitech M185", "82833", "Клавиатуры, мыши, комплекты", root="Периферия", domain="hardware", vendor="Logitech", price=1400)
    add("kb1", "Клавиатура Logitech K120", "82833", "Клавиатуры, мыши, комплекты", root="Периферия", domain="hardware", vendor="Logitech", price=1500)
    add("kb2", "Клавиатура Defender Element", "82833", "Клавиатуры, мыши, комплекты", root="Периферия", domain="hardware", vendor="Defender", price=890)
    # Наушники и микрофоны (88831)
    add("mic1", "Микрофон Razer Seiren Mini", "88831", "Наушники и микрофоны", root="Периферия", domain="hardware", vendor="Razer", price=6900)
    add("hp_audio", "Наушники Sony WH-CH520", "88831", "Наушники и микрофоны", root="Периферия", domain="hardware", vendor="Sony", price=5400)
    add("hs1", "Гарнитура Logitech H390", "88831", "Наушники и микрофоны", root="Периферия", domain="hardware", vendor="Logitech", price=3900)
    # Расходные материалы (94694)
    add("film1", "Пленка для ламинирования A4", "94694", "Расходные материалы", root="Офисная техника", domain="hardware", vendor="Fellowes", price=900)
    add("drum1", "Фотобарабан HP 19A", "94694", "Расходные материалы", root="Офисная техника", domain="hardware", vendor="HP", price=6200)
    add("cart1", "Картридж HP 85A черный", "94694", "Расходные материалы", root="Офисная техника", domain="hardware", vendor="HP", price=4900)

    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    engine = Engine.open(replace(cfg, data=data), llm=Disabled())
    yield engine
    engine.close()


def _main_cards(result):
    cards = []
    for b in result["blocks"]:
        if b["type"] in ("products", "analogs", "compare"):
            for item in b.get("items") or []:
                c = item.get("card") if isinstance(item.get("card"), dict) else item
                if c.get("kind") != "upsell":
                    cards.append(c)
    return cards


def test_price_bounds_range_and_fallback(n4_engine):
    # Верхняя граница
    r = n4_engine.search(Request(q="ноутбук дешевле 50000", mode="fast"))
    cards = _main_cards(r)
    assert cards and all(c["price_from"] <= 50000 for c in cards)
    assert r["understood"]["filters"]["price_max"] == 50000

    # Нижняя граница
    r_min = n4_engine.search(Request(q="ноутбук дороже 60000", mode="fast"))
    cards_min = _main_cards(r_min)
    assert cards_min and all(c["price_from"] >= 60000 for c in cards_min)
    assert r_min["understood"]["filters"]["price_min"] == 60000

    # Диапазон от N до M
    r_rng = n4_engine.search(Request(q="ноутбук от 40000 до 80000", mode="fast"))
    cards_rng = _main_cards(r_rng)
    assert cards_rng and all(40000 <= c["price_from"] <= 80000 for c in cards_rng)

    # Невыполнимая граница — не обнуляем ответ, показываем ближайшие с честным пояснением
    r_low = n4_engine.search(Request(q="windows дешевле 15000", mode="fast"))
    cards_low = _main_cards(r_low)
    assert cards_low and "windows" in cards_low[0]["title"].lower()
    assert not r_low["understood"]["zero_reason"]
    assert "дешевле" in r_low["understood"]["agent_note"].lower()
    assert cards_low[0]["price_from"] == 18900


def test_upgrade_not_parsed_as_price(n4_engine):
    r = n4_engine.search(Request(q="апгрейд windows 10 до 11", mode="fast"))
    assert "price_max" not in r["understood"]["filters"]
    cards = _main_cards(r)
    assert cards and "windows 11" in cards[0]["title"].lower()


def test_price_sorting_asc_and_desc(n4_engine):
    r_asc = n4_engine.search(Request(q="антивирус самый дешёвый", mode="fast"))
    prices_asc = [c["price_from"] for c in _main_cards(r_asc)[:4]]
    assert len(prices_asc) >= 3 and prices_asc == sorted(prices_asc)
    assert r_asc["understood"]["filters"]["sort"] == "price_asc"

    r_desc = n4_engine.search(Request(q="ноутбук самый дорогой", mode="fast"))
    prices_desc = [c["price_from"] for c in _main_cards(r_desc)[:4]]
    assert len(prices_desc) >= 3 and prices_desc == sorted(prices_desc, reverse=True)
    assert r_desc["understood"]["filters"]["sort"] == "price_desc"


def test_exclusions_and_russian_origin(n4_engine):
    r_ex = n4_engine.search(Request(q="антивирус не касперский", mode="fast"))
    cards_ex = _main_cards(r_ex)
    assert cards_ex and all("kaspersky" not in c["title"].lower() for c in cards_ex[:4])
    assert r_ex["understood"]["exclude"]

    r_off = n4_engine.search(Request(q="офис кроме microsoft", mode="fast"))
    cards_off = _main_cards(r_off)
    assert cards_off and all("microsoft" not in c["title"].lower() for c in cards_off[:4])
    assert any("р7" in c["title"].lower() or "мойофис" in c["title"].lower() for c in cards_off[:2])

    r_ru = n4_engine.search(Request(q="российский офисный пакет", mode="fast"))
    cards_ru = _main_cards(r_ru)
    assert cards_ru and all("microsoft" not in c["title"].lower() for c in cards_ru[:4])
    assert r_ru["understood"]["filters"]["origin"] == "russian"

    r_reg = n4_engine.search(Request(q="антивирус из реестра", mode="fast"))
    cards_reg = _main_cards(r_reg)
    assert cards_reg and all("norton" not in c["title"].lower() for c in cards_reg[:4])
    assert r_reg["understood"]["filters"]["registry"] is True


def test_support_and_platform(n4_engine):
    r_sup = n4_engine.search(Request(q="техподдержка astra linux", mode="fast"))
    cards_sup = _main_cards(r_sup)
    assert cards_sup and "astra" in cards_sup[0]["title"].lower()
    assert "поддержк" in cards_sup[0]["offer"]["name"].lower()
    assert r_sup["understood"]["filters"]["action"] == "support"

    r_mac = n4_engine.search(Request(q="антивирус для mac", mode="fast"))
    cards_mac = _main_cards(r_mac)
    assert cards_mac and "macos" in r_mac["understood"]["filters"]["platform"]


def test_compare_present_shortened_absent_and_guards(n4_engine):
    # Не перехватываем условия с «или»
    assert parse_compare("касперский на 1 или 2 года") is None
    assert parse_compare("подписка или бессрочная") is None
    assert parse_compare("чем отличается oem от box") is None

    # Оба продукта есть в фиде
    r = n4_engine.search(Request(q="сравнить р7 и мой офис", mode="fast"))
    assert r["understood"]["intent"] == "compare"
    cmp_block = next(b for b in r["blocks"] if b["type"] == "compare")
    assert len(cmp_block["columns"]) == 2
    assert len(cmp_block["rows"]) >= 3
    cards = _main_cards(r)
    assert len(cards) >= 4
    titles_top2 = " ".join(c["title"].lower() for c in cards[:2])
    assert "р7" in titles_top2 and "мойофис" in titles_top2

    # Усечённая правая часть (наследуем бренд)
    r_ed = n4_engine.search(Request(q="windows 11 home vs pro", mode="fast"))
    assert r_ed["understood"]["intent"] == "compare"
    t2 = [c["title"].lower() for c in _main_cards(r_ed)[:2]]
    assert any("home" in t for t in t2) and any("pro" in t for t in t2)

    # Одна сторона отсутствует в каталоге
    r_abs = n4_engine.search(Request(q="сравнить dr.web и eset", mode="fast"))
    assert "нет в каталоге" in r_abs["understood"]["agent_note"].lower()
    assert any("dr.web" in c["title"].lower() for c in _main_cards(r_abs))


def test_hardware_vendor_section_and_peripheral_ranking(n4_engine):
    # «принтер hp» должен попасть в 93995 («Принтеры и МФУ»), а не в 91774 без HP
    r_hp = n4_engine.search(Request(q="принтер hp", mode="fast"))
    cards_hp = _main_cards(r_hp)
    assert cards_hp and "hp" in cards_hp[0]["title"].lower()
    assert "нет" not in r_hp["understood"]["agent_note"].lower()

    # «клавиатура» и «мышь» в составном разделе 82833: одиночный тип выше комплекта
    r_kb = n4_engine.search(Request(q="клавиатура", mode="fast"))
    kb_top = _main_cards(r_kb)[0]["title"].lower()
    assert "клавиатур" in kb_top and "комплект" not in kb_top and "мыш" not in kb_top

    r_ms = n4_engine.search(Request(q="мышь logitech", mode="fast"))
    ms_top = _main_cards(r_ms)[0]["title"].lower()
    assert "мыш" in ms_top and "комплект" not in ms_top and "клавиатур" not in ms_top

    # «наушники» в 88831: наушники выше микрофонов
    r_au = n4_engine.search(Request(q="наушники", mode="fast"))
    assert "наушник" in _main_cards(r_au)[0]["title"].lower()

    # «картридж hp» в 94694: картридж выше фотобарабана и плёнки
    r_ct = n4_engine.search(Request(q="картридж hp", mode="fast"))
    assert "картридж" in _main_cards(r_ct)[0]["title"].lower()
