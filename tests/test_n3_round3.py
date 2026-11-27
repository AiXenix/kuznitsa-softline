"""Тесты N3 (Раунд 3): названное первым, опечатка в модели, порядок антивирусов, чужие совпадения и короткие бренды."""
import json
from dataclasses import replace
from pathlib import Path
from shutil import copytree
from types import SimpleNamespace

import pytest

from kuznitsa.engine import Engine
from kuznitsa.index.feed_flagships import FeedFlagships
from kuznitsa.index.feed_repair import FeedRecovery
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request
from kuznitsa.understand.repair import typo_matcher


@pytest.fixture(scope="module")
def n3_r3_shop(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n3_r3_catalog")
    kb = copytree(Path(__file__).resolve().parents[1] / "kb", data / "kb")
    rows = []

    def add(name, section, vendor, offers=1, price=1000, domain="software", aud=None, root="ПО",
            offer_names=None, action=None, qty_min=None, qty_max=None, term=None):
        names = offer_names or [f"{name} ({i + 1})" if offers > 1 else name for i in range(offers)]
        for idx, oname in enumerate(names):
            lic = {"audience": aud}
            if action:
                lic["action"] = action
            if qty_min is not None:
                lic["qty_min"] = qty_min
            if qty_max is not None:
                lic["qty_max"] = qty_max
            if term:
                lic["model"] = term
            rows.append(dict(
                offer_id=f"{name}__{idx}",
                group_id=name,
                name=oname,
                family_name=name,
                vendor=vendor,
                domain=domain,
                class_id=section,
                category_id=section,
                category_path=[root, section],
                available=True,
                price=price,
                oldprice=None,
                currency="RUB",
                url=f"https://example.test/{len(rows)}",
                image="https://example.test/img.png",
                description=name,
                lic=lic,
                popularity=100 - idx,
            ))

    # 1. Названное первым (продление / количество)
    add("Dr.Web Security Space", "Антивирусы для дома", "Доктор Веб",
        offer_names=["Dr.Web Security Space продление 1 год"], action="renewal")
    add("Dr.Web Desktop Security Suite", "Антивирусы для организаций", "Доктор Веб",
        offer_names=["Dr.Web Desktop Security Suite продление 1 год"], action="renewal")
    add("Dr.Web Server Security Suite", "Антивирусы для организаций", "Доктор Веб",
        offer_names=["Dr.Web Server Security Suite продление 1 год"], action="renewal", price=None)
    add("Dr.Web Server Security Suite Base Price", "Антивирусы для организаций", "Доктор Веб",
        offer_names=["Dr.Web Server Security Suite Base Price продление"], action="renewal")

    add("Kaspersky Standard", "Антивирусы для дома", "«Лаборатория Касперского»",
        offer_names=["Kaspersky Standard продление"], action="renewal")
    add("Kaspersky Endpoint Security для бизнеса Стандартный", "Антивирусы для организаций", "«Лаборатория Касперского»",
        offer_names=["Kaspersky Endpoint Security для бизнеса Стандартный продление"], action="renewal")
    add("Kaspersky Total Security для бизнеса", "Антивирусы для организаций", "«Лаборатория Касперского»",
        offer_names=["Kaspersky Total Security для бизнеса продление"], action="renewal", price=None)
    add("Kaspersky Endpoint Security Cloud", "Антивирусы для организаций", "«Лаборатория Касперского»")
    add("Kaspersky Small Office Security", "Антивирусы для организаций", "«Лаборатория Касперского»",
        offer_names=["Kaspersky Small Office Security бессрочная лицензия"], term="perpetual")

    add("Кибер Бэкап Стандартная редакция", "Резервное копирование", "Киберпротект",
        offer_names=["Кибер Бэкап Стандартная редакция 10-49 серверов"], qty_min=10, qty_max=49)
    add("Кибер Бэкап Расширенная редакция", "Резервное копирование", "Киберпротект",
        offer_names=["Кибер Бэкап Расширенная редакция 10-49 серверов"], qty_min=10, qty_max=49, price=None)

    # 2. Вендор + модель с опечаткой
    add("Рутокен ЭЦП 3.0 3120", "Токены и смарт-карты", "Актив",
        offer_names=["Рутокен ЭЦП 3.0 3120 USB"])
    add("Рутокен Lite (Rutoken)", "Токены и смарт-карты", "Актив",
        offer_names=["Рутокен Lite (версия 1010 micro)"])
    add("JaCarta", "Токены и смарт-карты", "Аладдин Р.Д.",
        offer_names=["JaCarta-2 PKI/NFC смарт-карта"])
    add("JaCarta Management System (JMS)", "Токены и смарт-карты", "Аладдин Р.Д.")

    # 3. Антивирусы: PRO32, MaxPatrol, UserGate NGFW
    add("PRO32 Endpoint Security Advanced", "Антивирусы для организаций", "PRO32")
    add("PRO32 Endpoint Security Standard", "Антивирусы для организаций", "PRO32")
    add("MaxPatrol Endpoint Protection Platform", "Антивирусы для организаций", "Positive Technologies")
    add("UserGate NGFW", "Антивирусы для организаций", "UserGate")
    add("Nano Антивирус Pro", "Антивирусы для организаций", "Nano Security")

    # 4. Офис + чужое совпадение + хвост после точного попадания
    add("Microsoft Office 2024 для дома и бизнеса", "Офисные пакеты", "Microsoft",
        offer_names=["Microsoft Office 2024 для дома и бизнеса бессрочная лицензия"], term="perpetual")
    add("Microsoft Office 2024 для дома и учёбы", "Офисные пакеты", "Microsoft",
        offer_names=["Microsoft Office 2024 для дома и учёбы бессрочная лицензия"], term="perpetual")
    add("Microsoft Office Professional Plus 2021", "Офисные пакеты", "Microsoft",
        offer_names=["Microsoft Office Professional Plus 2021 бессрочная лицензия"], term="perpetual")
    add("Microsoft Office Standard 2021", "Офисные пакеты", "Microsoft",
        offer_names=["Microsoft Office Standard 2021 бессрочная лицензия"], term="perpetual")

    add("AutoCAD LT for Macintosh", "Базовые программы", "Autodesk")
    add("Autodesk AutoCAD", "Базовые программы", "Autodesk")
    add("Autodesk AutoCAD Mechanical", "Программы для машиностроения", "Autodesk")
    add("Autodesk AutoCAD Civil 3D", "Инфраструктура", "Autodesk")
    add("Autodesk CFD – Premium", "Базовые программы", "Autodesk")
    add("Autodesk Flame", "Базовые программы", "Autodesk")

    add("Adobe Acrobat Professional", "Программное обеспечение для работы с документами", "Adobe Systems")
    add("Adobe Acrobat Standard", "Программное обеспечение для работы с документами", "Adobe Systems")
    add("ContentReader PDF 16 Business", "Программное обеспечение для работы с документами", "Content AI")
    add("Adobe Connect", "Программное обеспечение для работы с документами", "Adobe Systems")
    add("4D Write Professional", "Программное обеспечение для работы с документами", "4D")

    # 5. Короткие бренды и 2-словные опечатки
    add("CorelDRAW Graphics Suite 2026", "Графические редакторы", "Corel Corporation")
    add("nanoCAD BIM Электро 26", "Системы автоматизированного проектирования", "Нанософт Разработка")
    add("VMware Workstation 16 Pro for Linux and Windows", "Виртуализация", "VMware")
    add("Adobe Photoshop", "Графические редакторы", "Adobe Systems")

    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    (data / "feed_categories.json").write_text(json.dumps({}, ensure_ascii=False))
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("KZ_KB_DIR", str(kb))
        eng = Engine.open(replace(cfg, data=data, kb=kb), llm=Disabled())
        yield eng
        eng.close()


def _main_titles(resp):
    titles = []
    for blk in resp.get("blocks") or []:
        if blk.get("type") == "products":
            titles.extend(c["title"] for c in blk.get("items") or [] if c.get("kind") != "upsell")
    return titles


# ── 0. Сохранение поведения коммита 8db9866 в apply_audience_order ────────────


def test_apply_audience_order_preserves_section_branch():
    """При заданном разделе (section) Business/Enterprise не поднимаются, вниз уходят только домашние редакции."""
    flagships = FeedFlagships.__new__(FeedFlagships)
    flagships._audience = {"neutral": 0, "biz": 1, "home": -1}
    flagships.core_generic = {}
    ids = ["neutral", "home", "biz"]
    assert flagships.apply_audience_order(ids, {"value": 20}, "антивирус на 20 пк", section="650") == ["neutral", "biz", "home"]
    assert flagships.apply_audience_order(ids, {"value": 20}, "kaspersky на 20 пк", section=None) == ["biz", "neutral", "home"]


# ── 1. Точное название в запросе с продлением или количеством — первым ───────


def test_named_product_first_with_renewal_or_quantity(n3_r3_shop):
    """Полное название карточки с продлением или количеством всегда на 1 месте (даже при price=None или qty>=5)."""
    r1 = n3_r3_shop.search(Request(q="Dr.Web Server Security Suite продление", mode="fast"))
    t1 = _main_titles(r1)
    assert t1[0] == "Dr.Web Server Security Suite"
    assert t1[1] == "Dr.Web Server Security Suite Base Price"

    r2 = n3_r3_shop.search(Request(q="Kaspersky Total Security для бизнеса продление", mode="fast"))
    assert _main_titles(r2)[0] == "Kaspersky Total Security для бизнеса"

    r3 = n3_r3_shop.search(Request(q="Кибер Бэкап Расширенная редакция на 20 серверов", mode="fast"))
    assert _main_titles(r3)[0] == "Кибер Бэкап Расширенная редакция"


# ── 2. Слово модели с опечаткой внутри линейки вендора ────────────────────────


def test_vendor_model_typo_ranking(n3_r3_shop):
    """Опечатка в слове модели внутри распознанного вендора поднимает нужную карточку на первое место."""
    r1 = n3_r3_shop.search(Request(q="рутокен lite mirco", mode="fast"))
    assert _main_titles(r1)[0] == "Рутокен Lite (Rutoken)"

    r2 = n3_r3_shop.search(Request(q="jacarta pki ncf", mode="fast"))
    assert _main_titles(r2)[0] == "JaCarta"

    r3 = n3_r3_shop.search(Request(q="kaspersky endpoint secruity cloud", mode="fast"))
    assert _main_titles(r3)[0] == "Kaspersky Endpoint Security Cloud"


# ── 3. Порядок класса «антивирус» ─────────────────────────────────────────────


def test_antivirus_class_order_and_ngfw_demotion(n3_r3_shop):
    """В антивирусах первыми Kaspersky / Dr.Web / PRO32, NGFW и MaxPatrol ниже середины, но по бренду UserGate NGFW первый."""
    r = n3_r3_shop.search(Request(q="антивирус", mode="fast"))
    titles = _main_titles(r)
    top3_lower = [t.lower() for t in titles[:3]]
    assert any("kaspersky" in t for t in top3_lower)
    assert any("dr.web" in t for t in top3_lower)
    assert any("pro32" in t for t in top3_lower)

    mid = len(titles) // 2
    assert titles.index("UserGate NGFW") >= mid
    assert titles.index("MaxPatrol Endpoint Protection Platform") >= mid

    # При прямом поиске по вендору UserGate NGFW не теряет первое место.
    r_ug = n3_r3_shop.search(Request(q="UserGate", mode="fast"))
    assert _main_titles(r_ug)[0] == "UserGate NGFW"


# ── 4. Слово-совпадение в чужом названии и чистый хвост ──────────────────────


def test_alien_word_collision_and_clean_tail(n3_r3_shop):
    """На «office бессрочная лицензия» нет антивируса; хвост AutoCAD LT и Acrobat — линейка и раздел, без CFD/Flame/Connect."""
    r_off = n3_r3_shop.search(Request(q="office бессрочная лицензия", mode="fast"))
    off_titles = _main_titles(r_off)
    assert off_titles[:4]
    assert all("kaspersky" not in t.lower() for t in off_titles[:4])
    assert all("microsoft office" in t.lower() for t in off_titles[:4])

    r_cad = n3_r3_shop.search(Request(q="автокад lt", mode="fast"))
    cad_titles = _main_titles(r_cad)
    assert cad_titles[0] == "AutoCAD LT for Macintosh"
    assert all("cfd" not in t.lower() and "flame" not in t.lower() for t in cad_titles[:4])
    assert any("autocad" in t.lower() for t in cad_titles[1:4])

    r_acr = n3_r3_shop.search(Request(q="acrobat", mode="fast"))
    acr_titles = _main_titles(r_acr)
    assert acr_titles[0] == "Adobe Acrobat Professional"
    assert "Adobe Connect" not in acr_titles[:4]
    assert "ContentReader PDF 16 Business" in acr_titles[:4]


# ── 5. Опечатки в коротком бренде (5-6 букв) и в двух словах названия ─────────


def test_short_brand_typos_and_protections(n3_r3_shop):
    """Опечатки в 5-6 буквенных брендах и в двух словах находят линейку, без ложных правок защищённых слов."""
    cases = [
        ("abyy finereader", "contentreader"),
        ("acrobt pro", "acrobat"),
        ("corle draw", "coreldraw"),
        ("nanocda bim", "nanocad"),
        ("vmwrae workstaiton", "vmware workstation"),
        ("adboe photshop", "photoshop"),
    ]
    for query, expected in cases:
        resp = n3_r3_shop.search(Request(q=query, mode="fast"))
        titles = _main_titles(resp)
        assert titles and expected in titles[0].lower(), f"{query} -> {titles[:3]}"

    # Защищённые слова не ломаются.
    rec = n3_r3_shop.catalog.feed.recovery
    assert rec._safe_spell("steam", allow_two_short=True) == ()
    assert rec._safe_spell("пицца", allow_two_short=True) == ()
    assert rec._safe_spell("кии", allow_two_short=True) == ()
    assert n3_r3_shop.search(Request(q="steam", mode="fast"))["understood"]["intent"] == "out_of_catalog"
    assert n3_r3_shop.search(Request(q="пицца", mode="fast"))["blocks"][0]["type"] == "clarify"
