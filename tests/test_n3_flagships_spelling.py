"""Тесты N3: главные линейки первыми, сленг/раскладка/транслит, тираж → бизнес, неразрушающая починка и вопросы про вендора."""
import json
from dataclasses import replace
from pathlib import Path
from shutil import copytree

import pytest

from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def n3_shop(cfg, tmp_path_factory, monkeypatch_module):
    data = tmp_path_factory.mktemp("n3_catalog")
    kb = copytree(Path(__file__).resolve().parents[1] / "kb", data / "kb")
    rows = []

    def add(name, section, vendor, offers=1, price=1000, domain="software", aud=None, root="ПО", lic_extra=None):
        lic = {"audience": aud}
        if lic_extra:
            lic.update(lic_extra)
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

    # Microsoft: флагманы vs Visio/Project/CAL/Rights Management/аддоны/SCAD Office/Zoho M365
    ms = "Программы и лицензии Microsoft Corporation"
    add("Microsoft Windows 11 Pro (Профессиональная)", "ОС Windows", ms, offers=1, price=15000, aud="business")
    add("Microsoft Windows 11 Home (Домашняя)", "ОС Windows", ms, offers=1, price=10000, aud="home")
    add("Microsoft Windows Rights Management Services External Connector 2019", "ОС Windows", ms, offers=76, price=50000)
    add("Microsoft Office 2024 для дома и бизнеса", "Офисные пакеты программ Microsoft Office", ms, offers=1, price=25000)
    add("Microsoft Office Professional Plus 2021", "Офисные пакеты программ Microsoft Office", ms, offers=10, price=30000)
    add("Microsoft Office Excel 2021", "Офисные пакеты программ Microsoft Office", ms, offers=10, price=12000)
    add("Microsoft Visio Standard 2024", "Офисные пакеты программ Microsoft Office", ms, offers=5, price=49000)
    add("Microsoft Project Standard 2024", "Офисные пакеты программ Microsoft Office", ms, offers=5, price=101000)
    add("Office Flexispace", "Офисные пакеты программ Microsoft Office", "Flexispace", offers=5, price=500)
    add("SCAD Office", "САПР", "SCAD Soft", offers=15, price=60000)
    add("Microsoft 365 Family (для семьи)", "Офисные пакеты программ Microsoft Office", ms, offers=1, price=11000, aud="home")
    add("Microsoft 365 Personal (Персональный)", "Офисные пакеты программ Microsoft Office", ms, offers=1, price=9000, aud="home")
    add("Microsoft 365 корпоративный (Enterprise)", "Офисные пакеты программ Microsoft Office", ms, offers=15, price=None, aud="business")
    add("Microsoft 365 бизнес стандарт", "Офисные пакеты программ Microsoft Office", ms, offers=2, price=None, aud="business")
    add("Microsoft 365 F3", "Офисные пакеты программ Microsoft Office", ms, offers=9, price=None, aud="business")
    add("Microsoft Dynamics 365", "CRM", ms, offers=5, price=50000, aud="business", lic_extra={"metric": "user", "qty_max": 100})
    add("Zoho ManageEngine M365 Manager Plus for Microsoft 365", "Системы автоматизации", "Zoho Corporation Pvt. Ltd.", offers=5, price=93000, aud="business", lic_extra={"metric": "user", "qty_max": 100})
    add("Microsoft Office 365 Advanced Security Management", "Офисные пакеты программ Microsoft Office", ms, offers=2, price=3000)
    add("Microsoft Windows Server Datacenter 2022", "Серверное ПО", ms, offers=6, price=None, aud="business")
    add("Microsoft Windows Server CAL 2022", "Серверное ПО", ms, offers=20, price=3000)
    add("Microsoft SQL Server Standard Edition", "СУБД", ms, offers=30, price=None, aud="business")
    add("Microsoft SQL Server Enterprise Edition", "СУБД", ms, offers=20, price=None, aud="business")
    add("Microsoft SQL Server", "СУБД", ms, offers=12, price=None, aud="business")
    add("Microsoft SQL Server CAL", "СУБД", ms, offers=40, price=5000)
    add("EMS SQL Backup for SQL Server", "СУБД", "EMS", offers=30, price=15000)
    add("Microsoft Exchange Server 2019", "Почтовые серверы", ms, offers=20, price=None)
    add("SPAMfighter Exchange Модуль", "Почтовые серверы", "SPAMfighter", offers=5, price=639)
    add("Microsoft Visual Studio", "Средства разработки", ms, offers=25, price=None)

    # Kaspersky: флагманы vs 680-офферные облачные/виртуальные и курсы
    kl = "«Лаборатория Касперского»"
    add("Kaspersky Security для виртуальных и облачных сред", "Антивирусы для организаций", kl, offers=60, price=643)
    add("Kaspersky Express Course", "Антивирусы для организаций", kl, offers=16, price=2200)
    add("Kaspersky Standard", "Антивирусы для организаций", kl, offers=4, price=1800, aud="home")
    add("Kaspersky Plus + Who Calls", "Антивирусы для организаций", kl, offers=4, price=2500, aud="home")
    add("Kaspersky Small Office Security", "Антивирусы для организаций", kl, offers=10, price=8000, aud="business")
    add("Kaspersky Endpoint Security для бизнеса Стандартный", "Антивирусы для организаций", kl, offers=20, price=12000, aud="business")
    add("MDaemon Antivirus", "Антивирусы для организаций", "MDaemon", offers=5, price=5000)

    # AutoCAD, nanoCAD, КриптоПро, Сканер-ВС, Adobe, Corel, WinRAR, ContentReader
    add("Autodesk AutoCAD", "САПР", "Autodesk", offers=16, price=None)
    add("AutoCAD LT for Macintosh", "САПР", "Autodesk", offers=8, price=None)
    add("ModPlus AutoCAD", "САПР", "ModPlus", offers=5, price=300)
    add("Платформа nanoCAD 26", "САПР", "Нанософт Разработка", offers=25, price=25000)
    add("nanoCAD Механика PRO", "САПР", "Нанософт Разработка", offers=15, price=35000)
    add("ModPlus nanoCAD", "САПР", "ModPlus", offers=5, price=300)
    add("nanoCAD Землеустройство", "САПР", "Нанософт Разработка", offers=15, price=18000)
    add("Программа КриптоПро CSP 5.0", "Программы для защиты информации", "КриптоПро", offers=12, price=2700)
    add("КриптоПро Ключ", "Программы для защиты информации", "КриптоПро", offers=50, price=1500)
    add("КриптоПро CSP TLS", "Программы для защиты информации", "КриптоПро", offers=10, price=2000)
    add("SWG-система Solar webProxy", "Программы для защиты информации", "АО «СОЛАР СЕКЬЮРИТИ»", offers=10, price=10000)
    add("НПО Эшелон Сканер-ВС 6", "Информационная безопасность", "НПО «Эшелон»", offers=8, price=90000)
    add("Adobe Photoshop", "Графика", "Adobe Systems", offers=10, price=None)
    add("Adobe Illustrator", "Графика", "Adobe Systems", offers=10, price=None)
    add("Adobe Creative Cloud Professional for Teams", "Графика", "Adobe Systems", offers=20, price=None)
    add("CorelDRAW Graphics Suite 2026", "Графика", "Corel Corporation", offers=4, price=None)
    add("Архиватор WinRAR 7", "Архиваторы", "RARSoft", offers=8, price=3500)
    add("ContentReader PDF 16 Business", "Работа с PDF", "Content AI", offers=10, price=11760)

    # Вендоры для многословных вопросов
    add("MaxPatrol Endpoint Protection Platform", "Информационная безопасность", "Positive Technologies", offers=6, price=50000)
    add("Positive Technologies XSpider", "Информационная безопасность", "Positive Technologies", offers=12, price=40000)
    add("Pointdev Ideal Migration", "Сетевые утилиты", "Pointdev", offers=5, price=10000)
    add("КОМПАС-3D V25", "САПР", "АСКОН", offers=20, price=120000)
    add("КОМПАС-График V25", "САПР", "АСКОН", offers=10, price=60000)

    # Для проверки неразрушающей починки («steam» ↛ «team», «пицца» ↛ «pisa», «кии» ↛ «qi»)
    add("Team Planner Pro", "Управление проектами", "TeamSoft", offers=8, price=2000)
    add("Pisa Graphics Studio", "Графика", "PisaSoft", offers=5, price=3000)
    add("Qi Security Monitor", "Сетевые утилиты", "QiCorp", offers=5, price=4000)

    # SSD 1TB
    add("Внутренний твердотельный накопитель Kingston NV3 PCIe 4.0 NVMe M.2 2280 1TB", "SSD накопители", "Kingston", offers=1, price=6500, domain="hardware", root="Оборудование")
    add("Внутренний твердотельный накопитель ADATA Legend 960 NVMe 1TB", "SSD накопители", "ADATA", offers=1, price=7200, domain="hardware", root="Оборудование")
    add("Microsoft Core Infrastructure Server Suite Datacenter", "Серверное ПО", ms, offers=20, price=None)

    monkeypatch_module.setenv("KZ_KB_DIR", str(kb))
    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    e = Engine.open(replace(cfg, data=data, kb=kb), llm=Disabled())
    yield e
    e.close()


@pytest.fixture(scope="module")
def monkeypatch_module():
    with pytest.MonkeyPatch.context() as patch:
        yield patch


def _main_titles(res):
    for blk in res.get("blocks", []):
        if blk.get("type") == "products":
            return [c["title"] for c in blk["items"] if c.get("kind") != "upsell"]
    return []


def test_flagships_first_kaspersky(n3_shop):
    titles = _main_titles(n3_shop.search(Request(q="касперский", mode="fast")))
    assert titles[0] == "Kaspersky Standard"
    assert "Kaspersky Security для виртуальных и облачных сред" not in titles[:3]
    assert "Kaspersky Express Course" not in titles[:3]


def test_flagships_first_microsoft_and_office(n3_shop):
    ms_titles = _main_titles(n3_shop.search(Request(q="Microsoft", mode="fast")))
    assert any("Windows 11" in t for t in ms_titles[:2])
    assert "Microsoft Visio Standard 2024" not in ms_titles[:2]

    off_titles = _main_titles(n3_shop.search(Request(q="office", mode="fast")))
    assert off_titles[0].startswith("Microsoft Office")
    assert off_titles[0] not in {"Office Flexispace", "SCAD Office"}

    win_titles = _main_titles(n3_shop.search(Request(q="windows", mode="fast")))
    assert win_titles[0].startswith("Microsoft Windows 11")
    assert all("Rights Management" not in t for t in win_titles[:3])


def test_flagships_first_cad_crypto_exchange_sql(n3_shop):
    assert _main_titles(n3_shop.search(Request(q="AutoCAD", mode="fast")))[0] == "Autodesk AutoCAD"
    nano_titles = _main_titles(n3_shop.search(Request(q="nanoCAD", mode="fast")))
    assert nano_titles[0] == "Платформа nanoCAD 26"
    assert "ModPlus nanoCAD" not in nano_titles[:2]
    assert _main_titles(n3_shop.search(Request(q="КриптоПро CSP", mode="fast")))[0] == "Программа КриптоПро CSP 5.0"
    assert _main_titles(n3_shop.search(Request(q="криптопро", mode="fast")))[0] == "Программа КриптоПро CSP 5.0"
    assert _main_titles(n3_shop.search(Request(q="скзи", mode="fast")))[0] == "Программа КриптоПро CSP 5.0"
    assert _main_titles(n3_shop.search(Request(q="сканер-вс", mode="fast")))[0] == "НПО Эшелон Сканер-ВС 6"
    assert _main_titles(n3_shop.search(Request(q="exchange", mode="fast")))[0] == "Microsoft Exchange Server 2019"
    sql_titles = _main_titles(n3_shop.search(Request(q="SQL Server 2022", mode="fast")))
    assert sql_titles[0].startswith("Microsoft SQL Server")
    assert "EMS SQL Backup for SQL Server" not in sql_titles[:3]


def test_quantity_audience_business_first(n3_shop):
    titles = _main_titles(n3_shop.search(Request(q="microsoft 365 25 пользователей", mode="fast")))
    assert titles[0] in {"Microsoft 365 корпоративный (Enterprise)", "Microsoft 365 бизнес стандарт", "Microsoft 365 F3"}
    assert "Family" not in titles[0] and "Personal" not in titles[0]
    assert "Zoho" not in titles[0] and "Dynamics" not in titles[0]


@pytest.mark.parametrize("q,expect", [
    ("w11", "Windows 11"),
    ("win srv", "Windows Server"),
    ("o365", "Microsoft 365"),
    ("finereader", "ContentReader PDF"),
    ("файнридер", "ContentReader PDF"),
    ("фотошоп", "Adobe Photoshop"),
    ("фш", "Adobe Photoshop"),
    ("люстра", "Adobe Illustrator"),
    ("корел дро", "CorelDRAW"),
    ("вин рар", "WinRAR"),
    ("мс sql", "SQL Server"),
    ("вижуал студио", "Visual Studio"),
    ("цштвщцы 11", "Windows 11"),
    ("ajnjijg", "Adobe Photoshop"),
    ("jaabc 2021", "Office"),
])
def test_spelling_slang_layout_translit(n3_shop, q, expect):
    titles = _main_titles(n3_shop.search(Request(q=q, mode="fast")))
    assert titles, f"Empty result for {q!r}"
    assert expect.lower() in titles[0].lower(), f"Expected {expect!r} in {titles[0]!r} for {q!r}"


@pytest.mark.parametrize("q", ["антивирусс", "антивирус антивирус антивирус", "😀 антивирус"])
def test_noise_dedup_and_doubled_letter_antivirus(n3_shop, q):
    res = n3_shop.search(Request(q=q, mode="fast"))
    titles = _main_titles(res)
    assert titles and titles[0] != "MDaemon Antivirus"
    assert "Kaspersky" in titles[0]


def test_ssd_1tb_finds_ssd_not_server_software(n3_shop):
    titles = _main_titles(n3_shop.search(Request(q="ssd 1tb", mode="fast")))
    assert titles
    assert "твердотельный накопитель" in titles[0].lower() and "1tb" in titles[0].lower()


def test_non_destructive_repair(n3_shop):
    # steam ↛ team, пицца ↛ pisa, кии ↛ qi
    for q, bad in [("steam", "Team Planner Pro"), ("пицца", "Pisa Graphics Studio"), ("кии", "Qi Security Monitor")]:
        res = n3_shop.search(Request(q=q, mode="fast"))
        titles = _main_titles(res)
        assert bad not in titles, f"Destructive repair turned {q!r} into {bad!r}"


@pytest.mark.parametrize("q,expect", [
    ("что есть у Positive Technologies", "MaxPatrol"),
    ("продукты Аскон", "КОМПАС-3D"),
    ("всё от adobe", "Adobe"),
])
def test_multiword_vendor_questions(n3_shop, q, expect):
    titles = _main_titles(n3_shop.search(Request(q=q, mode="fast")))
    assert titles, f"Empty result for {q!r}"
    assert expect.lower() in titles[0].lower(), f"Expected {expect!r} in {titles[0]!r} for {q!r}"
