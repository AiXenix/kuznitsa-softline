"""Тесты N5: подсказки при наборе для фида (на маленьких выдуманных карточках)."""
import json
from pathlib import Path
from shutil import copytree

import pytest
import yaml

from kuznitsa.config import Config
from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Disabled
from kuznitsa.suggest.index import suggest

REPO_KB = Path(__file__).resolve().parents[1] / "kb"


@pytest.fixture(scope="module")
def shop(tmp_path_factory):
    data = tmp_path_factory.mktemp("n5_suggest")
    kb = copytree(REPO_KB, data / "kb")
    rows = []

    def add(name, section, vendor, domain="software", offers=1, aud=None, price=1500, cid=None):
        gid = cid or name
        for i in range(offers):
            rows.append(dict(
                offer_id=f"{gid}#{i}",
                group_id=gid,
                name=name,
                family_name=name,
                vendor=vendor,
                domain=domain,
                class_id=section,
                category_id=section,
                category_path=["ПО" if domain == "software" else "Оборудование", section],
                price=price + i * 100,
                lic={"audience": aud} if aud else {},
            ))

    # Антивирусы + шумная карточка техподдержки
    add("Kaspersky Standard", "Антивирусы для дома", "Лаборатория Касперского", offers=8, aud="home")
    add("Kaspersky Plus", "Антивирусы для дома", "Лаборатория Касперского", offers=6, aud="home")
    add("Kaspersky Endpoint Security для бизнеса", "Антивирусы для организаций", "Лаборатория Касперского", offers=5, aud="business")
    add("Dr.Web Security Space", "Антивирусы для дома", "Доктор Веб", offers=7, aud="home")
    add("Dr.Web Desktop Security Suite", "Антивирусы для организаций", "Доктор Веб", offers=2, aud="business")
    add("Сертификат на комплексную техническую поддержку антивирус", "Техническая поддержка", "Softline", offers=1)

    # Windows / Office / SQL / Adobe / Autodesk / nanoCAD / Postgres / Linux / VPN / ЭЦП / Бэкап
    add("Microsoft Windows 11 Pro", "Windows 11: лицензии Home и Pro", "Microsoft", offers=8, aud="business")
    add("Microsoft Windows 11 Home", "Windows 11: лицензии Home и Pro", "Microsoft", offers=7, aud="home")
    add("Microsoft Windows 10 Pro", "Операционные системы Windows", "Microsoft", offers=5, aud="business")
    add("Microsoft Windows Server 2022", "Серверные ОС", "Microsoft", offers=6, aud="business")
    add("Microsoft Windows Server CAL 2019", "Серверные ОС", "Microsoft", offers=4, aud="business")
    add("Microsoft Office для дома и бизнеса 2021", "Офисные пакеты программ Microsoft Office", "Microsoft", offers=8, aud="home")
    add("Microsoft Office 2024 Standard", "Офисные пакеты программ Microsoft Office", "Microsoft", offers=6, aud="business")
    add("Microsoft 365 Персональный", "Офисные пакеты программ Microsoft Office", "Microsoft", offers=7, aud="home")
    add("Microsoft SQL Server 2022", "СУБД", "Microsoft", offers=6, aud="business")
    add("Office Flexispace", "Офисные приложения", "OtherCo", offers=1)
    add("MicroSurvey CAD", "САПР", "MicroSurvey", offers=1)
    add("SQL Manager for InterBase", "Утилиты БД", "EMS", offers=1)
    add("Autodesk AutoCAD", "Системы проектирования", "Autodesk", offers=6)
    add("Autodesk AutoCAD LT for Macintosh", "Системы проектирования", "Autodesk", offers=1)
    add("АвтоКаталог", "Автобизнес", "АвтоСофт", offers=1)
    add("Adobe Photoshop", "Программы для обработки цифрового фото", "Adobe", offers=6)
    add("ФотоМАСТЕР", "Программы для обработки цифрового фото", "AMS Software", offers=3)
    add("ФотоШОУ PRO", "Видео и фото", "AMS", offers=1)
    add("nanoCAD Платформа", "Системы проектирования", "Нанософт", offers=6)
    add("Сетевой адаптер Nano PCI-E", "Сетевые карты", "NetCo", domain="hardware", offers=1)
    add("Postgres Pro Standard", "СУБД", "Postgres Professional", offers=5)
    add("Astra Linux Special Edition", "Российские операционные системы", "Группа Астра", offers=6)
    add("Альт Рабочая станция", "Российские операционные системы", "Базальт СПО", offers=5)
    add("Кибер Бэкап", "Программное обеспечение для резервного копирования", "Киберпротект", offers=6)
    add("Модем Zyxel резервный канал", "Модемы", "Zyxel", domain="hardware", offers=1)
    add("Континент АП VPN", "Межсетевые экраны", "Код Безопасности", offers=5)
    add("КриптоАРМ ГОСТ", "Программы для защиты информации", "Цифровые технологии", offers=6)
    add("КриптоПро CSP", "Программы для защиты информации", "КРИПТО-ПРО", offers=6)
    add("Secret Net Studio", "Защита от НСД", "Код Безопасности", offers=5)
    add("Secret Disk 5", "Шифрование дисков", "Аладдин", offers=2)
    add("Офисное кресло Бюрократ", "Офисные кресла", "Бюрократ", domain="hardware", offers=2)
    add("Код активации ОФД", "Онлайн-кассы", "ОФД", offers=2)

    # Оборудование
    add("Ноутбук Lenovo ThinkPad E14", "Ноутбуки", "Lenovo", domain="hardware", offers=5)
    add("Ноутбук HP ProBook 450", "Ноутбуки", "HP", domain="hardware", offers=4)
    add("Монитор Dell 27 P2722H", "Мониторы", "Dell", domain="hardware", offers=5)
    add("Монитор Samsung 24 S24", "Мониторы", "Samsung", domain="hardware", offers=3)
    add("Мышь Logitech MX Master 3S", "Мыши", "Logitech", domain="hardware", offers=5)
    add("Принтер HP LaserJet Pro", "Принтеры и МФУ", "HP", domain="hardware", offers=5)

    # Допродажа, включающая уже показанный товар (проверка дедупликации)
    rules = [
        dict(
            id="win_upsell_dup",
            when={"classes": ["Windows 11: лицензии Home и Pro"]},
            offer={"classes": ["Windows 11: лицензии Home и Pro", "Антивирусы для дома"]},
            reason="Рекомендуем вместе",
        ),
        dict(
            id="kasp_upsell",
            when={"classes": ["Антивирусы для дома"]},
            offer={"classes": ["Офисные пакеты программ Microsoft Office"]},
            reason="Для работы с документами",
        ),
    ]
    (kb / "upsell_n5.yaml").write_text(yaml.safe_dump(rules, allow_unicode=True))
    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))

    conf = Config(data=data, kb=kb, cache=data / "cache", embed="off")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KZ_KB_DIR", str(kb))
        eng = Engine.open(conf, llm=Disabled())
        try:
            yield eng
        finally:
            eng.close()


def _groups(eng, q):
    resp = suggest(eng, q)
    return resp, {g["type"]: g["items"] for g in resp["groups"]}


def _titles(groups, gtype="products"):
    return [item["text"] for item in groups.get(gtype, [])]


# 1. Один путь для любого ввода: исправление раскладки и опечатки ведёт туда же, куда чистый ввод
@pytest.mark.parametrize("broken,clean,expected", [
    ("цшт", "win", "Windows"),
    ("rfcg", "касп", "Kaspersky"),
    ("fdnjrfl", "автокад", "AutoCAD"),
    ("касперскй", "касперский", "Kaspersky"),
    ("автакад", "автокад", "AutoCAD"),
])
def test_n5_unified_correction_pipeline(shop, broken, clean, expected):
    r_broken, g_broken = _groups(shop, broken)
    _, g_clean = _groups(shop, clean)
    assert r_broken["corrected"], f"expected corrected for {broken!r}"
    assert _titles(g_broken), f"no products for {broken!r}"
    assert expected.lower() in _titles(g_broken)[0].lower()
    assert _titles(g_broken)[:2] == _titles(g_clean)[:2]


# 2. Толкование незаконченного ввода: русские написания брендов, точные начала, разделы и оборудование
@pytest.mark.parametrize("q,expected", [
    ("авток", "AutoCAD"),
    ("фотош", "Adobe Photoshop"),
    ("фотошоп", "Adobe Photoshop"),
    ("нанок", "nanoCAD"),
    ("постгрес", "Postgres Pro"),
    ("ворд", "Microsoft"),
    ("эксель", "Microsoft"),
    ("dr.web sec", "Dr.Web Security Space"),
    ("антив", "Kaspersky"),
    ("резерв", "Кибер Бэкап"),
    ("впн", "VPN"),
    ("эцп", "Крипто"),
    ("линукс", "Astra Linux"),
    ("ноут", "Ноутбук"),
    ("прин", "Принтер"),
])
def test_n5_prefix_interpretation(shop, q, expected):
    _, g = _groups(shop, q)
    titles = _titles(g)
    assert titles, f"empty suggest for {q!r}"
    assert any(expected.lower() in t.lower() for t in titles[:3]), f"{q!r} -> {titles}"


# 3. Порядок: точное начало и главные бренды выше случайных подстрок и нишевых товаров
def test_n5_ordering_and_significance(shop):
    _, g_office = _groups(shop, "office")
    assert _titles(g_office)[0].startswith("Microsoft")
    assert all("Flexispace" not in t for t in _titles(g_office)[:2])

    _, g_micr = _groups(shop, "micr")
    assert _titles(g_micr)[0].startswith("Microsoft")
    assert all("MicroSurvey" not in t for t in _titles(g_micr)[:2])

    _, g_sql = _groups(shop, "sql")
    assert "SQL Server" in _titles(g_sql)[0]

    _, g_secret = _groups(shop, "secret")
    assert "Secret Net Studio" in _titles(g_secret)[0]

    _, g_autoc = _groups(shop, "autoc")
    assert _titles(g_autoc)[0] == "Autodesk AutoCAD"

    _, g_of = _groups(shop, "оф")
    assert not any("кресло" in t.lower() or "офд" in t.lower() for t in _titles(g_of))


# 4. Числа, срок и служебные слова не обнуляют подсказки, а версия уточняет карточку
def test_n5_numbers_service_words_and_versions(shop):
    for q in ("кас 10", "касперский 10 пк", "купить каспер", "цена касперский на 2 года", "лицензия касперский"):
        _, g = _groups(shop, q)
        titles = _titles(g)
        assert titles and any("kaspersky" in t.lower() for t in titles), f"{q!r} -> {titles}"

    _, g_w10 = _groups(shop, "windows 10")
    assert "Windows 10" in _titles(g_w10)[0]

    _, g_w11p = _groups(shop, "windows 11 p")
    assert "Windows 11 Pro" in _titles(g_w11p)[0]

    _, g_off21 = _groups(shop, "office 2021")
    assert "2021" in _titles(g_off21)[0]


# 5. Тип товара целым словом и с продолжением: раздел, уточнённые товары и варианты в queries
def test_n5_type_and_continuation(shop):
    _, g_av = _groups(shop, "антивирус")
    assert any("антивирус" in it["text"].lower() for it in g_av.get("categories", []))
    assert all("сертификат" not in t.lower() for t in _titles(g_av))

    _, g_av_for = _groups(shop, "антивирус для")
    assert g_av_for.get("products") or g_av_for.get("queries")
    assert any("антивирус" in it["text"].lower() for it in g_av_for.get("queries", []))

    _, g_av_home = _groups(shop, "антивирус для дома")
    assert any(
        "kaspersky standard" in t.lower() or "dr.web security space" in t.lower()
        for t in _titles(g_av_home)[:2]
    )

    _, g_nb = _groups(shop, "ноутбук len")
    assert "Lenovo" in _titles(g_nb)[0]

    _, g_mon = _groups(shop, "монитор 27")
    assert "27" in _titles(g_mon)[0]

    _, g_mouse = _groups(shop, "мышь log")
    assert "Logitech" in _titles(g_mouse)[0]

    _, g_prn = _groups(shop, "принтер hp")
    assert "HP" in _titles(g_prn)[0]


# 6. Без повторов карточек во всём ответе и пустой ответ на бессмыслицу
def test_n5_dedup_and_gibberish(shop):
    for q in ("windows 11", "касперский", "антивирус"):
        resp, _ = _groups(shop, q)
        ids = [
            item["card_id"]
            for grp in resp["groups"]
            for item in grp["items"]
            if item.get("card_id")
        ]
        assert len(ids) == len(set(ids)), f"duplicate card_id in {q!r}: {ids}"

    resp_bad, g_bad = _groups(shop, "xyzq")
    assert resp_bad["groups"] == []
    assert not g_bad


# 7. Скорость: предрасчётный индекс и быстрый ответ на каждое нажатие клавиши
def test_n5_latency_and_prebuilt_index(shop):
    assert shop.suggestions.feed_suggest is not None
    suggest(shop, "касп")
    for q in ("касп", "антив", "антивирус для", "micr", "цшт", "ноутбук len", "xyzq"):
        resp = suggest(shop, q)
        assert resp["ms"] < 40, f"{q!r} took {resp['ms']} ms"


# 8. Группа analogs для отсутствующего товара и поддержка всех групп + клавиш в web/js/suggest.js
def test_n5_analogs_and_frontend_groups(shop):
    _, g_absent = _groups(shop, "Luminar Neo")
    assert "analogs" in g_absent
    assert any("ФотоМАСТЕР" in item["text"] for item in g_absent["analogs"])

    js = (Path(__file__).resolve().parents[1] / "web" / "js" / "suggest.js").read_text(encoding="utf-8")
    for group_type in ("products", "analogs", "categories", "queries", "corrections", "upsell"):
        assert f"'{group_type}'" in js, f"group {group_type} missing in web/js/suggest.js"
    for key in ("ArrowDown", "ArrowUp", "Enter", "Escape"):
        assert f"'{key}'" in js, f"keyboard handler for {key} missing in web/js/suggest.js"
