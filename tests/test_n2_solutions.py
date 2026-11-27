"""Тесты потока N2: курируемые бизнес-задачи, вопросы, приоритет продукта и железа."""
from dataclasses import replace
import json
from pathlib import Path
from shutil import copyfile, copytree

import pytest
import yaml

from kuznitsa.engine import Engine
from kuznitsa.evaluation import cards_from
from kuznitsa.index.feed_solutions import bind, load_rows
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def env(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n2")
    kb = copytree(cfg.kb, data / "kb")
    copyfile(Path("kb/feed_solutions.yaml"), kb / "feed_solutions.yaml")
    rows = []

    def add(cid, title, section, vendor="SoftVendor", domain="software", price=5000, offers=None):
        root = "Оборудование" if domain == "hardware" else "Программное обеспечение"
        if offers is None:
            offers = [dict(offer_id=cid, price=price, available=True)]
        for idx, off in enumerate(offers):
            rows.append(
                dict(
                    offer_id=off.get("offer_id", f"{cid}_{idx}"),
                    group_id=cid,
                    name=off.get("name", title),
                    family_name=title,
                    class_id=section,
                    category_id=section,
                    category_path=[root, section],
                    domain=domain,
                    vendor=vendor,
                    price=off.get("price", price),
                    available=off.get("available", True),
                    metric=off.get("metric"),
                    qty_min=off.get("qty_min"),
                    qty_max=off.get("qty_max"),
                )
            )

    # Железо
    add("hw_srv", "DEPO Storm Rack-сервер 2U", "Серверы", vendor="DEPO", domain="hardware", price=250000)
    add("hw_nb", "Ноутбук Aquarius Cmp NS685", "Ноутбуки", vendor="Aquarius", domain="hardware", price=75000)
    add("hw_prn", "Принтер Pantum P2500W", "Принтеры", vendor="Pantum", domain="hardware", price=15000)
    add("hw_mon", "Монитор 27 дюймов Acer", "Мониторы", vendor="Acer", domain="hardware", price=22000)
    add("hw_acc", "Аккумулятор Omni Qi 10000mAh", "Аккумуляторы", vendor="Omni", domain="hardware", price=3000)
    add("hw_chair", "Defender Офисное кресло Dallas", "Кресла", vendor="Defender", domain="hardware", price=12000)

    # Бэкап и виртуализация
    add("sw_bk1", "Киберпротект Кибер Бэкап Стандартная", "Программное обеспечение для резервного копирования", vendor="Киберпротект")
    add("sw_bk2", "Кибер Бэкап Облачный", "Программное обеспечение для резервного копирования", vendor="Киберпротект")
    add("sw_bk3", "Arcserve Backup", "Программное обеспечение для резервного копирования", vendor="Arcserve")
    add("sw_bk4", "Новософт Handy Backup", "Программное обеспечение для резервного копирования", vendor="Новософт")

    add("sw_v1", "Orion soft Zvirt", "Российская виртуализация (Импортозамещение)", vendor="Orion soft")
    add("sw_v2", "VMmanager", "Программы для виртуализации", vendor="ISPsystem")
    add("sw_v3", "BaseALT Альт Виртуализация 11", "Российская виртуализация (Импортозамещение)", vendor="BaseALT")
    add("sw_v4", "Blue Hill Virtual Machines", "Программы для виртуализации", vendor="Blue Hill")

    # Почта и шифрование
    add("sw_m1", "IceWarp Почтовый сервер", "Почтовые утилиты", vendor="IceWarp")
    add("sw_m2", "Почтовый сервер Tegu", "Почтовые утилиты", vendor="МБК Лаб")
    add("sw_m3", "MDaemon Messaging Server", "Почтовые клиенты", vendor="MDaemon")
    add("sw_m4", "CommuniGate Systems", "Российская коммуникационная платформа (Импортозамещение)", vendor="CommuniGate")

    add("sw_e1", "Secret Disk 5", "Программы для защиты информации", vendor="Код безопасности")
    add("sw_e2", "EgoSecure Full Disk Encryption", "Программы для защиты информации", vendor="EgoSecure")

    # ИБ / DLP / SIEM / КИИ / антивирусы
    add("sw_dlp1", "Staffcop Enterprise", "Программное обеспечение для контроля персонала", vendor="Атом Безопасность")
    add("sw_dlp2", "Стахановец: Про", "Программное обеспечение для контроля персонала", vendor="Стахановец")
    add("sw_dlp3", "ИНСАЙДЕР", "Программное обеспечение для контроля персонала", vendor="ИНСАЙДЕР")
    add("sw_siem1", "Ipswitch Event Tracker SIEM", "Программы для защиты информации", vendor="Ipswitch")
    add("sw_szi1", "Код безопасности Secret Net Studio", "Программы для защиты информации", vendor="Код безопасности")
    add("sw_szi2", "Код безопасности АПКШ «Континент»", "Межсетевые экраны", vendor="Код безопасности")
    add("sw_szi3", "Эшелон «СКАНЕР-ВС»", "Программы для защиты информации", vendor="НПО Эшелон")
    add("sw_pt1", "Positive Technologies XSpider", "Программы для защиты информации", vendor="Positive Technologies")
    add("sw_pt2", "Positive Technologies MaxPatrol Endpoint Protection", "Программы для защиты информации", vendor="Positive Technologies")
    add("sw_csp", "Программа КриптоПро CSP 5.0", "Программы для защиты информации", vendor="КриптоПро")

    add(
        "sw_av1",
        "Kaspersky Endpoint Security для бизнеса Расширенный",
        "Антивирусы для организаций",
        vendor="Лаборатория Касперского",
        offers=[
            dict(offer_id="av1_10", name="Kaspersky Endpoint Security 10-14 devices", price=12000, metric="device", qty_min=10, qty_max=14),
            dict(offer_id="av1_50", name="Kaspersky Endpoint Security 50-99 devices", price=48000, metric="device", qty_min=50, qty_max=99),
        ],
    )
    add(
        "sw_av2",
        "Kaspersky Small Office Security",
        "Антивирусы для организаций",
        vendor="Лаборатория Касперского",
        offers=[dict(offer_id="av2_10", name="KSOS 10 devices", price=9000, metric="device", qty_min=5, qty_max=10)],
    )
    add("sw_av3", "Kaspersky Standard", "Антивирусы для дома", vendor="Лаборатория Касперского", price=1900)
    add("sw_av4", "Доктор Веб Dr.Web Security Space", "Антивирусы для дома", vendor="Доктор Веб", price=1800)
    add("sw_av5", "PRO32 Endpoint Security Standard", "Антивирусы для организаций", vendor="PRO32", price=3500)
    add("sw_av6", "Kaspersky Security для Microsoft Office 365", "Программы для защиты информации", vendor="Лаборатория Касперского", price=4000)

    # Офис, ОС, AD, ВКС, удалённый доступ, СЭД
    add("sw_os1", "Astra Linux Special Edition", "Российские операционные системы (Импортозамещение)", vendor="Группа Астра")
    add("sw_os2", "Microsoft Windows 11 Pro", "Операционные системы Windows", vendor="Microsoft")
    add("sw_ad1", "ALD Pro", "Российские операционные системы (Импортозамещение)", vendor="Группа Астра")
    add("sw_ad2", "BaseALT Альт Домен 11", "Российские операционные системы (Импортозамещение)", vendor="BaseALT")
    add("sw_ad3", "РОСА Dynamic Directory", "Российские операционные системы (Импортозамещение)", vendor="РОСА")
    add("sw_off1", "«Р7-Офис» для юридических лиц", "Российское офисное ПО (Импортозамещение)", vendor="Р7")
    add("sw_off2", "МойОфис Стандартный 3", "Российское офисное ПО (Импортозамещение)", vendor="МойОфис")
    add("sw_off3", "Microsoft Office", "Офисные пакеты программ Microsoft Office", vendor="Microsoft")
    add("sw_off4", "Microsoft 365 Бизнес стандарт", "Офисные пакеты программ Microsoft Office", vendor="Microsoft")
    add("sw_vcs1", "TrueConf Server", "Коммуникации (SaaS)", vendor="TrueConf")
    add("sw_vcs2", "SberDevices SaluteJazz", "Коммуникации (SaaS)", vendor="SberDevices")
    add("sw_vcs3", "СКБ Контур Контур.Толк", "Коммуникации (SaaS)", vendor="СКБ Контур")
    add("sw_rd1", "AnyDesk", "Сетевые утилиты", vendor="AnyDesk")
    add("sw_rd2", "TeamViewer", "Сетевые утилиты", vendor="TeamViewer")
    add("sw_edo1", "Directum СЭД+", "Программное обеспечение для работы с документами", vendor="DIRECTUM")
    add("sw_edo2", "Docsvision", "Программное обеспечение для работы с документами", vendor="Docsvision")

    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    conf = replace(cfg, data=data, kb=kb)
    engine = Engine.open(conf, llm=Disabled())
    yield engine
    engine.close()


def run(engine, q):
    return engine.search(Request(q=q, mode="fast", source="eval"))


def test_solutions_yaml_integrity():
    rows, warnings = load_rows(Path("kb"))
    assert len(rows) >= 80, f"Ожидалось >= 80 задач, получено {len(rows)}"
    assert not warnings, f"Ошибки загрузки kb/feed_solutions.yaml: {warnings}"
    for row in rows:
        assert row["id"] and row["title"] and row["phrases"]
        assert row.get("pins") or row.get("sections")


def test_bind_graceful_warnings_and_pin_filtering():
    rows = [
        dict(
            id="demo",
            title="Демо",
            phrases=["тест"],
            pins=["Microsoft Office", "Несуществующий Продукт"],
            sections=["Несуществующий Раздел"],
            avoid=["кресло"],
        )
    ]
    cards = [
        ("c1", "Kaspersky Security для Microsoft Office 365", "Kaspersky", "software"),
        ("c2", "Microsoft Office", "Microsoft", "software"),
        ("c3", "Курс Microsoft Office обучение", "Edu", "software"),
        ("c4", "Defender кресло Dallas", "Defender", "hardware"),
    ]
    bound, warnings = bind(rows, cards, classes={})
    filled, secs, pinned = bound["demo"]
    assert pinned == ("c2",), "Должен выбраться сам Microsoft Office, а не 'для Microsoft Office' и не курс"
    assert not secs
    assert len(warnings) == 2


@pytest.mark.parametrize(
    "query,expected_sub,forbidden_sub",
    [
        ("резервное копирование сервера", "бэкап", "rack"),
        ("виртуализация серверов", "zvirt", "rack"),
        ("почтовый сервер для компании", "почтовый", "rack"),
        ("шифрование дисков на ноутбуках", "secret disk", "ноутбук"),
    ],
)
def test_hardware_words_inside_software_tasks(env, query, expected_sub, forbidden_sub):
    res = run(env, query)
    titles = [c["title"].lower() for c in cards_from(res["blocks"])[:4]]
    assert any(expected_sub in t for t in titles), f"{query}: {titles}"
    assert not any(forbidden_sub in t for t in titles), f"{query}: {titles}"


@pytest.mark.parametrize("query", ["сервер", "ноутбук", "принтер", "монитор 27"])
def test_pure_hardware_untouched(env, query):
    res = run(env, query)
    top = cards_from(res["blocks"])[:2]
    assert top and all(c["domain"] == "hardware" for c in top), f"{query}: {top}"


def test_product_and_vendor_precedence(env):
    r1 = run(env, "виртуальные машины Blue Hill")
    top1 = [c["title"] for c in cards_from(r1["blocks"])[:2]]
    assert any("Blue Hill" in t for t in top1), top1

    r2 = run(env, "Astra Linux Special Edition для внутреннего документооборота")
    assert r2["understood"]["intent"] == "product"
    assert "Astra Linux" in cards_from(r2["blocks"])[0]["title"]


def test_question_wrappers_and_context_clauses(env):
    r_price = run(env, "сколько стоит касперский на 10 компьютеров?")
    assert any("kaspersky" in c["title"].lower() for c in cards_from(r_price["blocks"])[:3])
    assert r_price["understood"]["qty"] == {"value": 10, "metric": "device"}

    r_win = run(env, "где купить лицензию на windows?")
    assert any("windows" in c["title"].lower() for c in cards_from(r_win["blocks"])[:3])

    r_pt = run(env, "что есть у Positive Technologies")
    assert any("xspider" in c["title"].lower() or "maxpatrol" in c["title"].lower() for c in cards_from(r_pt["blocks"])[:3])

    r_bk = run(env, "у нас сервер 1с, чем его бэкапить")
    assert any("бэкап" in c["title"].lower() or "backup" in c["title"].lower() for c in cards_from(r_bk["blocks"])[:3])


def test_replacement_solutions_vs_analogs(env):
    r_ad = run(env, "что поставить вместо Active Directory?")
    top_ad = [c["title"].lower() for c in cards_from(r_ad["blocks"])[:4]]
    assert any("ald pro" in t or "альт домен" in t or "dynamic directory" in t for t in top_ad), top_ad

    r_off = run(env, "чем заменить Microsoft Office?")
    top_off = [c["title"].lower() for c in cards_from(r_off["blocks"])[:4]]
    assert any("р7-офис" in t or "мойофис" in t for t in top_off), top_off
    assert not any("microsoft" in t for t in top_off), top_off


def test_abbreviations_no_false_spell_repair(env):
    for q, needle in [("кии", "secret net"), ("dlp", "staffcop"), ("siem", "siem"), ("скзи", "криптопро")]:
        res = run(env, q)
        assert not res["query"]["corrections"], f"{q}: unexpected corrections {res['query']['corrections']}"
        titles = [c["title"].lower() for c in cards_from(res["blocks"])[:4]]
        assert any(needle in t for t in titles), f"{q}: {titles}"
        assert not any("аккумулятор" in t for t in titles), f"{q}: {titles}"


def test_english_tasks_and_quantities(env):
    r_ep = run(env, "endpoint protection 50 devices")
    assert r_ep["understood"]["qty"] == {"value": 50, "metric": "device"}
    assert "kaspersky" in cards_from(r_ep["blocks"])[0]["title"].lower()

    r_bk = run(env, "backup software for servers")
    assert any("бэкап" in c["title"].lower() or "backup" in c["title"].lower() for c in cards_from(r_bk["blocks"])[:3])

    r_vcs = run(env, "video conferencing")
    assert any("trueconf" in c["title"].lower() or "salutejazz" in c["title"].lower() for c in cards_from(r_vcs["blocks"])[:3])


def test_complex_kit_keeps_cards_with_qty_and_note(env):
    res = run(env, "открываем новый офис на 15 человек, что нужно из софта?")
    assert res["understood"]["qty"] == {"value": 15, "metric": "user"}
    cards = cards_from(res["blocks"])
    assert len(cards) >= 4
    assert "офис" in res["understood"]["agent_note"].lower()
    assert res["cost"]["llm_calls"] == 0
