"""Тесты трека N8: наследование предмета диалога в сессии на фиде."""
import json
import re
from dataclasses import replace

import pytest

from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def n8_engine(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n8_feed")
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
        description="",
        gid=None,
        lic=None,
        attrs=None,
    ):
        a = {"domain": domain}
        if attrs:
            a.update(attrs)
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
                attrs=a,
                description=description,
                lic=lic or {"model": "subscription", "term_months": 12, "metric": "device"},
                available=True,
                in_stock=True,
            )
        )

    # Антивирусы для дома
    add("k_std_1", "Kaspersky Standard 1 ПК", "av_home", "Антивирусы для дома", root="Безопасность", vendor="Лаборатория Касперского", price=1500, registry=True, platforms=["Windows", "macOS"], gid="k_std", lic={"model": "subscription", "term_months": 12, "metric": "device", "qty_min": 1, "qty_max": 3})
    add("k_std_5", "Kaspersky Standard 5 ПК", "av_home", "Антивирусы для дома", root="Безопасность", vendor="Лаборатория Касперского", price=2900, registry=True, platforms=["Windows", "macOS"], gid="k_std", lic={"model": "subscription", "term_months": 12, "metric": "device", "qty_min": 5, "qty_max": 5})
    add("k_plus_5", "Kaspersky Plus 5 ПК", "av_home", "Антивирусы для дома", root="Безопасность", vendor="Лаборатория Касперского", price=3900, registry=True, platforms=["Windows", "macOS"], gid="k_plus", lic={"model": "subscription", "term_months": 12, "metric": "device", "qty_min": 5, "qty_max": 5})
    add("k_prem_5", "Kaspersky Premium 5 ПК", "av_home", "Антивирусы для дома", root="Безопасность", vendor="Лаборатория Касперского", price=5500, registry=True, platforms=["Windows", "macOS"], gid="k_prem", lic={"model": "subscription", "term_months": 12, "metric": "device", "qty_min": 5, "qty_max": 5})
    add("k_safe_5", "Kaspersky Safe Kids 5 ПК", "av_home", "Антивирусы для дома", root="Безопасность", vendor="Лаборатория Касперского", price=1200, registry=True, platforms=["Windows", "Android"], gid="k_safe", lic={"model": "subscription", "term_months": 12, "metric": "device", "qty_min": 5, "qty_max": 5})
    add("drweb_h", "Dr.Web Security Space", "av_home", "Антивирусы для дома", root="Безопасность", vendor="Доктор Веб", price=1800, registry=True, platforms=["Windows", "Android"])
    add("pro32_h", "PRO32 Ultimate Security", "av_home", "Антивирусы для дома", root="Безопасность", vendor="PRO32", price=990, registry=True, platforms=["Windows"])

    # Антивирусы для организаций (с Linux и тиражами)
    add("kes_5", "Kaspersky Endpoint Security 5 ПК", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Лаборатория Касперского", price=6100, registry=True, platforms=["Windows", "Linux"], gid="kes", lic={"model": "subscription", "term_months": 12, "metric": "device", "qty_min": 5, "qty_max": 10})
    add("kes_50", "Kaspersky Endpoint Security 50 ПК", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Лаборатория Касперского", price=49000, registry=True, platforms=["Windows", "Linux"], gid="kes", lic={"model": "subscription", "term_months": 12, "metric": "device", "qty_min": 25, "qty_max": 100})
    add("ksos_5", "Kaspersky Small Office Security 5 ПК", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Лаборатория Касперского", price=4800, registry=True, platforms=["Windows", "macOS"], gid="ksos", lic={"model": "subscription", "term_months": 12, "metric": "device", "qty_min": 5, "qty_max": 10})
    add("ksc_5", "Kaspersky Security для бизнеса Стандартный 5 ПК", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Лаборатория Касперского", price=7200, registry=True, platforms=["Windows", "Linux"], gid="ksc", lic={"model": "subscription", "term_months": 12, "metric": "device", "qty_min": 5, "qty_max": 10})
    add("ksc_adv", "Kaspersky Security для бизнеса Расширенный 5 ПК", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Лаборатория Касперского", price=9500, registry=True, platforms=["Windows", "Linux"], gid="ksc_adv", lic={"model": "subscription", "term_months": 12, "metric": "device", "qty_min": 5, "qty_max": 10})
    add("drweb_b", "Dr.Web Enterprise Security Suite", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Доктор Веб", price=2900, registry=True, platforms=["Windows", "Linux"])
    add("pro32_b", "PRO32 Endpoint Security", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="PRO32", price=1250, registry=True, platforms=["Windows", "Linux"])
    add("alt_av", "Антивирус Защита Linux", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Код Безопасности", price=3400, registry=True, platforms=["Linux"])

    # Ноутбуки (разные вендоры и цены)
    add("nb1", "Ноутбук Acer Extensa 15 15.6-inch 8 ГБ", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="Acer", price=39900)
    add("nb2", "Ноутбук Lenovo IdeaPad 3 15.6-inch 8 ГБ", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="Lenovo", price=48500)
    add("nb3", "Ноутбук Lenovo V15 15.6-inch 8 ГБ", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="Lenovo", price=54000)
    add("nb4", "Ноутбук Lenovo ThinkPad E15 15.6-inch 16 ГБ", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="Lenovo", price=72000)
    add("nb5", "Ноутбук Lenovo ThinkBook 14 14.0-inch 16 ГБ", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="Lenovo", price=69000)
    add("nb6", "Ноутбук Lenovo ThinkPad X1 Carbon 14.0-inch 16 ГБ", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="Lenovo", price=145000)
    add("nb7", "Ноутбук HP ProBook 450 15.6-inch 16 ГБ", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="HP", price=58000)
    add("nb8", "Ноутбук ASUS VivoBook 15 15.6-inch 8 ГБ", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="ASUS", price=51000)
    add("nb9", "Ноутбук Apple MacBook Pro 16 16.0-inch 16 ГБ", "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor="Apple", price=185000)

    # Мониторы (разные вендоры, цены, диагонали)
    add("mon1", "Монитор ACER K242HYL 24.0-inch черный", "70190", "Мониторы", root="Периферия", domain="hardware", vendor="Acer", price=12500)
    add("mon2", "Монитор ACER B277KL 27.0-inch черный", "70190", "Мониторы", root="Периферия", domain="hardware", vendor="Acer", price=28000)
    add("mon3", "Монитор Samsung S24R350 24.0-inch черный", "70190", "Мониторы", root="Периферия", domain="hardware", vendor="Samsung", price=14900)
    add("mon4", "Монитор Samsung S27A600 27.0-inch черный", "70190", "Мониторы", root="Периферия", domain="hardware", vendor="Samsung", price=24500)
    add("mon5", "Монитор Samsung Odyssey G5 27.0-inch черный", "70190", "Мониторы", root="Периферия", domain="hardware", vendor="Samsung", price=34900)
    add("mon6", "Монитор Samsung ViewFinity S6 27.0-inch черный", "70190", "Мониторы", root="Периферия", domain="hardware", vendor="Samsung", price=41000)
    add("mon7", "Монитор Samsung S32A700 32.0-inch черный", "70190", "Мониторы", root="Периферия", domain="hardware", vendor="Samsung", price=49000)
    add("mon8", "Монитор LG 27MP60G 27.0-inch IPS черный", "70190", "Мониторы", root="Периферия", domain="hardware", vendor="LG", price=19900)
    add("mon9", "Монитор Dell P2722H 27.0-inch IPS черный", "70190", "Мониторы", root="Периферия", domain="hardware", vendor="Dell", price=31500)

    # Принтеры (включая дороже 60000, чтобы проверить сброс цены)
    add("pr1", "Принтер HP LaserJet Enterprise M507dn", "93995", "Принтеры и МФУ", root="Офисная техника", domain="hardware", vendor="HP", price=85000)
    add("pr2", "Принтер Kyocera ECOSYS P3155dn", "93995", "Принтеры и МФУ", root="Офисная техника", domain="hardware", vendor="Kyocera", price=78000)
    add("pr3", "МФУ HP LaserJet M141w", "93995", "Принтеры и МФУ", root="Офисная техника", domain="hardware", vendor="HP", price=26000)
    add("pr4", "Принтер Pantum P2500W", "93995", "Принтеры и МФУ", root="Офисная техника", domain="hardware", vendor="Pantum", price=14000)

    # Windows 11 (Home / Pro)
    add("win11_home", "Microsoft Windows 11 Home", "os_win", "Операционные системы Windows", root="Операционные системы", vendor="Microsoft", price=18900, lic={"model": "perpetual", "metric": "device"})
    add("win11_pro", "Microsoft Windows 11 Pro", "os_win", "Операционные системы Windows", root="Операционные системы", vendor="Microsoft", price=24900, lic={"model": "perpetual", "metric": "device"})
    add("win10_pro", "Microsoft Windows 10 Pro", "os_win", "Операционные системы Windows", root="Операционные системы", vendor="Microsoft", price=21500, lic={"model": "perpetual", "metric": "device"})

    # Office 2021 + российские офисные пакеты
    add("ms_off21", "Microsoft Office 2021 Home and Business", "off_ms", "Офисные пакеты", root="Офисные приложения", vendor="Microsoft", price=22000, registry=False)
    add("r7_pro", "Р7-Офис Профессиональный", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="АО «Р7»", price=4500, registry=True)
    add("myoff_std", "МойОфис Стандартный 2", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="МойОфис", price=5200, registry=True)
    add("r7_home", "Р7-Офис для дома", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="АО «Р7»", price=2100, registry=True)
    add("myoff_pro", "МойОфис Профессиональный", "off_ru", "Российские офисные приложения (Импортозамещение)", root="Офисные приложения", vendor="МойОфис", price=8900, registry=True)

    (data / "catalog.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )
    engine = Engine.open(replace(cfg, data=data), llm=Disabled())
    yield engine
    engine.close()


def _cards(result):
    out = []
    for b in result.get("blocks") or []:
        if b.get("type") in ("products", "analogs"):
            for item in b.get("items") or []:
                c = item.get("card") if isinstance(item.get("card"), dict) else item
                if c.get("kind") != "upsell":
                    out.append(c)
    return out


def _run_chain(engine, sid, *steps, **last_kwargs):
    res = None
    for i, q in enumerate(steps):
        kw = dict(q=q, mode="fast", session_id=sid, context="on")
        if i == len(steps) - 1:
            kw.update(last_kwargs)
        res = engine.search(Request(**kw))
    return res


def test_price_refinement_and_chip(n8_engine):
    r = _run_chain(n8_engine, "s_price_1", "ноутбук", "до 60000")
    cards = _cards(r)
    assert len(cards) >= 4
    assert all(c["title"].lower().startswith("ноутбук") for c in cards)
    assert all((c["price_from"] or 1e18) <= 60000 for c in cards)
    u = r["understood"]
    assert (u.get("inherited") or {}).get("from_q") == "ноутбук"
    chips = [c for c in u.get("chips") or [] if c.get("key") == "context"]
    assert chips and chips[0].get("removable") is True
    assert "ноутбук" in chips[0]["label"]


def test_vendor_and_price_accumulation(n8_engine):
    r1 = _run_chain(n8_engine, "s_accum", "ноутбук", "lenovo")
    c1 = _cards(r1)
    assert len(c1) >= 4
    assert all(c["title"].lower().startswith("ноутбук") and "lenovo" in c["vendor"]["name"].lower() for c in c1)
    assert (r1["understood"].get("inherited") or {}).get("from_q") == "ноутбук"

    r2 = n8_engine.search(Request(q="до 80000", mode="fast", session_id="s_accum", context="on"))
    c2 = _cards(r2)
    assert len(c2) >= 4
    assert all(c["title"].lower().startswith("ноутбук") for c in c2)
    assert all("lenovo" in c["vendor"]["name"].lower() for c in c2)
    assert all((c["price_from"] or 1e18) <= 80000 for c in c2)
    assert all("x1 carbon" not in c["title"].lower() for c in c2)
    assert r2["understood"].get("inherited") is not None


def test_quantity_and_cheaper_chain(n8_engine):
    r1 = _run_chain(n8_engine, "s_kasp", "антивирус касперский", "на 5 пк")
    c1 = _cards(r1)
    assert len(c1) >= 4
    assert all(re.search(r"kaspersky|касперск", c["title"] + c["vendor"]["name"], re.I) for c in c1)
    assert (r1["understood"].get("qty") or {}).get("value") == 5
    assert r1["understood"].get("inherited") is not None

    r2 = n8_engine.search(Request(q="а подешевле", mode="fast", session_id="s_kasp", context="on"))
    c2 = _cards(r2)
    assert len(c2) >= 4
    assert all(re.search(r"kaspersky|касперск", c["title"] + c["vendor"]["name"], re.I) for c in c2)
    prices = [c["price_from"] for c in c2 if c.get("price_from") is not None]
    assert prices == sorted(prices)


def test_edition_and_audience_switch(n8_engine):
    r1 = _run_chain(n8_engine, "s_win", "windows 11", "pro")
    c1 = _cards(r1)
    assert c1 and re.search(r"windows 11 pro", c1[0]["title"], re.I)
    assert r1["understood"].get("inherited") is not None

    r2 = n8_engine.search(Request(q="а для дома", mode="fast", session_id="s_win", context="on"))
    c2 = _cards(r2)
    assert c2 and re.search(r"windows 11 home", c2[0]["title"], re.I)
    assert r2["understood"].get("inherited") is not None


def test_platform_and_audience_refinement(n8_engine):
    r_lin = _run_chain(n8_engine, "s_av_lin", "антивирус", "для linux")
    c_lin = _cards(r_lin)
    assert len(c_lin) >= 4
    assert all(re.search(r"kaspersky|dr\.web|pro32|антивирус", c["title"], re.I) for c in c_lin)
    assert r_lin["understood"].get("inherited") is not None

    r_home = _run_chain(n8_engine, "s_av_home", "антивирус", "для дома")
    c_home = _cards(r_home)
    assert len(c_home) >= 4
    assert r_home["understood"].get("inherited") is not None
    assert "av_home" in (r_home["understood"]["filters"].get("category") or [])


def test_monitors_sort_vendor_and_property(n8_engine):
    r_asc = _run_chain(n8_engine, "s_mon_asc", "монитор", "подешевле")
    c_asc = _cards(r_asc)[:4]
    assert len(c_asc) == 4
    assert all(c["title"].lower().startswith("монитор") for c in c_asc)
    assert [c["price_from"] for c in c_asc] == sorted(c["price_from"] for c in c_asc)

    r_desc = _run_chain(n8_engine, "s_mon_desc", "монитор", "подороже")
    c_desc = _cards(r_desc)[:4]
    assert len(c_desc) == 4
    assert [c["price_from"] for c in c_desc] == sorted((c["price_from"] for c in c_desc), reverse=True)

    r_ven = _run_chain(n8_engine, "s_mon_sam", "монитор", "samsung")
    c_ven = _cards(r_ven)[:4]
    assert len(c_ven) == 4
    assert all(c["title"].lower().startswith("монитор") and "samsung" in c["vendor"]["name"].lower() for c in c_ven)

    r_prop = _run_chain(n8_engine, "s_mon_27", "монитор", "27 дюймов")
    c_prop = _cards(r_prop)[:4]
    assert len(c_prop) == 4
    assert all(c["title"].lower().startswith("монитор") and re.search(r"\b27", c["title"]) for c in c_prop)

    # Накопление: свойство -> производитель
    r_prop_ven = n8_engine.search(Request(q="samsung", mode="fast", session_id="s_mon_27", context="on"))
    c_pv = _cards(r_prop_ven)
    assert len(c_pv) >= 3
    assert all("samsung" in c["vendor"]["name"].lower() and re.search(r"\b27", c["title"]) for c in c_pv)


def test_russian_analog_refinement(n8_engine):
    r = _run_chain(n8_engine, "s_off_ru", "office 2021", "а что-нибудь российское")
    c = _cards(r)[:4]
    ru_hits = [x for x in c if re.search(r"р7|мойофис", x["title"], re.I) and not re.search(r"microsoft", x["title"], re.I)]
    assert len(ru_hits) >= 2
    assert r["understood"].get("inherited") is not None


def test_new_subject_resets_context_and_price(n8_engine):
    r1 = _run_chain(n8_engine, "s_reset_1", "касперский", "ноутбук")
    c1 = _cards(r1)[:4]
    assert len(c1) == 4
    assert all(c["title"].lower().startswith("ноутбук") for c in c1)
    assert not r1["understood"].get("inherited")

    r2 = _run_chain(n8_engine, "s_reset_2", "ноутбук", "антивирус касперский")
    c2 = _cards(r2)[:4]
    assert len(c2) == 4
    assert all(re.search(r"kaspersky|касперск", c["title"] + c["vendor"]["name"], re.I) for c in c2)
    assert not r2["understood"].get("inherited")

    # Новый предмет сбрасывает прежнюю цену (принтеры дороже 60000 присутствуют)
    r3 = _run_chain(n8_engine, "s_reset_3", "ноутбук", "до 60000", "принтер")
    c3 = _cards(r3)[:4]
    assert len(c3) == 4
    assert all(re.search(r"принтер|мфу", c["title"], re.I) for c in c3)
    assert any((c["price_from"] or 0) > 60000 for c in c3)
    assert not r3["understood"].get("inherited")

    # Несовместимый производитель начинает разговор заново
    r4 = _run_chain(n8_engine, "s_reset_4", "ноутбук", "касперский")
    c4 = _cards(r4)[:4]
    assert c4 and all(re.search(r"kaspersky|касперск", c["title"] + c["vendor"]["name"], re.I) for c in c4)
    assert not r4["understood"].get("inherited")


def test_context_controls_isolation_and_pagination(n8_engine):
    # context="off" даёт ответ как на отдельный запрос
    a = _run_chain(n8_engine, "s_off", "ноутбук", "lenovo", context="off")
    b = n8_engine.search(Request(q="lenovo", mode="fast", session_id="s_off_ref"))
    assert [c["card_id"] for c in _cards(a)[:4]] == [c["card_id"] for c in _cards(b)[:4]]
    assert not a["understood"].get("inherited")

    # ignore=["context"] снимает наследование
    a_ign = _run_chain(n8_engine, "s_ign", "ноутбук", "lenovo", ignore=["context"])
    assert [c["card_id"] for c in _cards(a_ign)[:4]] == [c["card_id"] for c in _cards(b)[:4]]
    assert not a_ign["understood"].get("inherited")

    # Другая сессия ничего не наследует
    n8_engine.search(Request(q="ноутбук", mode="fast", session_id="s_iso_a", context="on"))
    r_other = n8_engine.search(Request(q="до 60000", mode="fast", session_id="s_iso_b", context="on"))
    assert not r_other["understood"].get("inherited")

    # Вторая страница того же запроса — не уточнение
    n8_engine.search(Request(q="ноутбук", mode="fast", session_id="s_page", context="on", page=1, page_size=4))
    r_p2 = n8_engine.search(Request(q="ноутбук", mode="fast", session_id="s_page", context="on", page=2, page_size=4))
    assert not r_p2["understood"].get("inherited")
    assert len(_cards(r_p2)) >= 4

    # Вторая страница уточнённого запроса не ломает контекст
    _run_chain(n8_engine, "s_page_ref", "ноутбук", "до 80000", page=1, page_size=4)
    r_ref_p2 = n8_engine.search(Request(q="до 80000", mode="fast", session_id="s_page_ref", context="on", page=2, page_size=4))
    c_ref_p2 = _cards(r_ref_p2)
    assert c_ref_p2 and all(c["title"].lower().startswith("ноутбук") and (c["price_from"] or 1e18) <= 80000 for c in c_ref_p2)


def test_session_ttl_expiry(n8_engine):
    now = [1000.0]
    orig_clock = n8_engine.sessions.clock
    n8_engine.sessions.clock = lambda: now[0]
    try:
        n8_engine.search(Request(q="ноутбук", mode="fast", session_id="s_ttl", context="on"))
        now[0] += 1000.0  # > 900s TTL
        r = n8_engine.search(Request(q="до 60000", mode="fast", session_id="s_ttl", context="on"))
        assert not r["understood"].get("inherited")
    finally:
        n8_engine.sessions.clock = orig_clock


def test_conversational_wrappers_and_exclusions(n8_engine):
    # «а есть lenovo» после «ноутбук»
    r = _run_chain(n8_engine, "s_wrap_1", "ноутбук", "а есть lenovo")
    cards = _cards(r)
    assert len(cards) >= 4
    assert all(c["title"].lower().startswith("ноутбук") and "lenovo" in c["vendor"]["name"].lower() for c in cards)
    assert r["understood"].get("inherited") is not None

    # «самый дешёвый» после «монитор»
    r_ch = _run_chain(n8_engine, "s_wrap_2", "монитор", "самый дешёвый")
    c_ch = _cards(r_ch)[:4]
    assert len(c_ch) == 4
    assert [c["price_from"] for c in c_ch] == sorted(c["price_from"] for c in c_ch)
    assert r_ch["understood"].get("inherited") is not None

    # «кроме касперского» после «антивирус»
    r_ex = _run_chain(n8_engine, "s_wrap_3", "антивирус", "кроме касперского")
    c_ex = _cards(r_ex)
    assert c_ex and all("kaspersky" not in c["title"].lower() and "касперск" not in c["vendor"]["name"].lower() for c in c_ex)
    assert r_ex["understood"].get("inherited") is not None

    # «монитор» -> «27 дюймов» -> «до 30000» (накопление свойства и цены)
    r_p1 = _run_chain(n8_engine, "s_prop_p", "монитор", "27 дюймов", "до 30000")
    c_p1 = _cards(r_p1)
    assert c_p1 and all(re.search(r"\b27", c["title"]) and (c["price_from"] or 1e18) <= 30000 for c in c_p1)
    assert r_p1["understood"].get("inherited") is not None
