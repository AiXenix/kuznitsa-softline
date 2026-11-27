"""Тесты третьего раунда потока N2: бренд в задаче, точное название товара, OCR vs переводчик, 12 задач и жаргон."""
from dataclasses import replace
import json
from pathlib import Path
from shutil import copyfile, copytree

import pytest

from kuznitsa.engine import Engine
from kuznitsa.evaluation import cards_from
from kuznitsa.llm.jev import Disabled
from kuznitsa.plans.feed_query import normalize_vendor_adjectives
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def env(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n2_r3")
    kb = copytree(cfg.kb, data / "kb")
    copyfile(Path("kb/feed_solutions.yaml"), kb / "feed_solutions.yaml")
    rows = []

    def add(cid, title, section, vendor="SoftVendor", domain="software", price=5000):
        root = "Оборудование" if domain == "hardware" else "Программное обеспечение"
        rows.append(
            dict(
                offer_id=cid,
                group_id=cid,
                name=title,
                family_name=title,
                class_id=section,
                category_id=section,
                category_path=[root, section],
                domain=domain,
                vendor=vendor,
                price=price,
                available=True,
                lic={},
            )
        )

    # 1. Резервное копирование + бренды
    add("bk_cb", "Кибер Бэкап Стандартная редакция", "Программное обеспечение для резервного копирования", vendor="Киберпротект")
    add("bk_ru", "RuBackup OneClick", "Программное обеспечение для резервного копирования", vendor="Группа Астра")
    add("bk_ar", "Arcserve Backup", "Программное обеспечение для резервного копирования", vendor="Arcserve")
    add("bk_ems", "EMS SQL Backup for SQL Server", "Утилиты для баз данных", vendor="EMS Software")
    add("wipe_oo", "O&O SafeErase", "Программы для очистки диска", vendor="O&O Software")

    # 2. Почтовые серверы + точные названия + АСКОН (для проверки отсутствия у вендора)
    add("mail_iw", "IceWarp Почтовый сервер", "Почтовые утилиты", vendor="IceWarp")
    add("mail_tegu", "Почтовый сервер Tegu", "Почтовые утилиты", vendor="МБК Лаб")
    add("mail_cg", "CommuniGate Pro", "Российская коммуникационная платформа (Импортозамещение)", vendor="АО «СБК»")
    add("cad_ascon", "КОМПАС-3D", "САПР", vendor="АСКОН")

    # 3. Защита конечных точек / антивирусы (корпоративные + домашние)
    add("av_kes", "Kaspersky Endpoint Security для бизнеса", "Антивирусы для организаций", vendor="«Лаборатория Касперского»")
    add("av_drw", "Dr.Web Server Security Suite", "Антивирусы для организаций", vendor="Доктор Веб")
    add("av_pt", "MaxPatrol Endpoint Protection Platform", "Антивирусы для организаций", vendor="Positive Technologies")
    add("av_home_k", "Kaspersky Standard", "Антивирусы для дома", vendor="«Лаборатория Касперского»")
    add("av_home_d", "Dr.Web Security Space", "Антивирусы для дома", vendor="Доктор Веб")

    # 4. Точные названия со словом-классом
    add("ra_rms", "RMS Удаленный доступ 7.1", "Удаленный доступ", vendor="TektonIT")
    add("ra_ad", "AnyDesk", "Сетевые утилиты", vendor="AnyDesk")
    add("ra_as", "АССИСТЕНТ", "Сетевые утилиты", vendor="САФИБ")
    add("arc_wr", "WinRAR", "Архиваторы", vendor="RARLAB")
    add("arc_set", "СЕТЕРЕ Архиватор", "Утилиты", vendor="SETERE")
    add("sp_3i", "3iTech Речевая аналитика", "Речевые технологии", vendor="3iTech")
    add("sp_bit", "БИТ.Аналитика АТС", "Речевые технологии", vendor="Первый БИТ")

    # 5. OCR vs Переводчики + Конвертер документов
    add("ocr_cr", "ContentReader PDF 16", "Программы для распознавания текста и речи", vendor="Content AI")
    add("ocr_cr15", "ContentReader PDF 15 Standard", "Программы для распознавания текста и речи", vendor="Content AI")
    add("tr_promt", "PROMT Master NMT", "Переводчики", vendor="PROMT")
    add("conv_3h", "3-Heights Document Converter", "Текстовые конвертеры", vendor="PDF Tools AG")
    add("conv_ice", "Icecream PDF Converter PRO", "Текстовые конвертеры", vendor="Icecream Apps")
    add("scan_geo", "ТИМ КРЕДО 3D СКАН", "САПР", vendor="Кредо-Диалог")

    # 6. Остальные задачи из пункта 4 + жаргон пункта 5
    add("crm_b24", "1С-Битрикс24", "CRM/ERP-системы", vendor="1С-Битрикс")
    add("crm_mp", "CRM Мегаплан: Бизнес", "CRM/ERP-системы", vendor="Мегаплан")
    add("aud_aa", "Adobe Audition", "Аудиоредакторы", vendor="Adobe Systems")
    add("aud_al", "Ableton Live", "Аудиоредакторы", vendor="Ableton")
    add("par_ksk", "Kaspersky Safe Kids", "Программное обеспечение для родительского контроля", vendor="«Лаборатория Касперского»")
    add("par_kr", "Parental Control Kroha", "Программное обеспечение для родительского контроля", vendor="Kroha")
    add("fw_ti", "Traffic Inspector Next Generation", "Межсетевые экраны", vendor="Смарт-Софт")
    add("fw_ug", "UserGate NGFW", "Межсетевые экраны", vendor="UserGate")
    add("fw_sw", "StormWall для защиты сайтов от DDoS-атак", "Межсетевые экраны", vendor="StormWall")
    add("vms_int", "Интегрированная система безопасности «Интеллект»", "ПО для видеонаблюдения", vendor="ITV")
    add("vms_mac", "ST Macroscop", "ПО для видеонаблюдения", vendor="Macroscop")
    add("inv_10s", "10-Страйк: Инвентаризация Компьютеров", "Программное обеспечение для учета компьютеров", vendor="10-Страйк")
    add("inv_tni", "Total Network Inventory", "Программное обеспечение для учета компьютеров", vendor="Softinventive Lab")
    add("vdi_td", "Termidesk", "Российская виртуализация (Импортозамещение)", vendor="Увеон")
    add("vdi_ti", "TIONIX VDI", "Программы для виртуализации", vendor="ТИОНИКС")
    add("virt_zv", "zVirt", "Российская виртуализация (Импортозамещение)", vendor="Орион софт")
    add("virt_vm", "VMmanager", "Программы для виртуализации", vendor="ISPsystem")
    add("vcs_tc", "TrueConf Server", "Программное обеспечение для онлайн общения", vendor="TrueConf")
    add("vcs_sj", "SaluteJazz", "Коммуникации (SaaS)", vendor="Сбер")
    add("off_ms", "Microsoft Office", "Офисные пакеты программ Microsoft Office", vendor="Microsoft")
    add("off_365", "Microsoft 365", "Офисные пакеты программ Microsoft Office", vendor="Microsoft")
    add("hw_rack", "Rack-сервер DEPO Storm 3470S2A", "Rack-серверы", vendor="DEPO", domain="hardware", price=450000)
    add("hw_pc", "ПК DEPO Neos DF8", "Десктопы", vendor="DEPO", domain="hardware", price=55000)

    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    (data / "feed_categories.json").write_text(
        json.dumps({r["group_id"]: [r["family_name"], r["class_id"]] for r in rows}, ensure_ascii=False),
        encoding="utf-8",
    )
    engine = Engine.open(replace(cfg, data=data, kb=kb), llm=Disabled())
    yield engine
    engine.close()


def _ask(engine, q):
    return engine.search(Request(q=q, mode="fast", source="eval", explain=False, page_size=10))


def _titles(res):
    return [c["title"] for c in cards_from(res["blocks"])]


# --- 1. Бренд / линейка в запросе задачи идут первыми ---


def test_r3_brand_in_solution_goes_first(env):
    for q, expected_first in [
        ("система резервного копирования от киберпротект", "Кибер Бэкап"),
        ("система резервного копирования от rubackup", "RuBackup"),
        ("почтовый сервер от communigate", "CommuniGate Pro"),
        ("платформа защиты конечных точек от positive technologies", "MaxPatrol Endpoint Protection"),
        ("антивирус производства доктор веб", "Dr.Web"),
        ("почтовый сервер communigate", "CommuniGate Pro"),
    ]:
        titles = _titles(_ask(env, q))
        assert titles, f"Пустой ответ для {q!r}"
        assert expected_first.lower() in titles[0].lower(), f"{q!r}: ожидали {expected_first!r} первым, получили {titles[:3]}"


def test_r3_brand_absent_in_solution_honest_note_and_general_list(env):
    res = _ask(env, "почтовый сервер от аскон")
    titles = _titles(res)
    note = (res["understood"].get("agent_note") or "").lower()
    assert titles, "Ожидается общий список почтовых серверов"
    assert any("почтов" in t.lower() or "communigate" in t.lower() for t in titles[:3]), titles[:3]
    assert "компас" not in titles[0].lower(), titles[:3]
    assert "аскон" in note and "нет" in note, note


def test_r3_threat_noun_after_ot_is_not_treated_as_brand(env):
    res = _ask(env, "закрыть сеть офиса от атак")
    titles = _titles(res)
    assert titles, "Пустой ответ"
    assert "traffic inspector" in titles[0].lower(), f"Угроза «от атак» не должна выталкивать StormWall вперёд: {titles[:3]}"
    assert not any("производитель" in c.lower() for c in res["understood"].get("chips", [])), res["understood"].get("chips")


# --- 2. Точное название товара сильнее решения и раздела ---


@pytest.mark.parametrize(
    "title",
    [
        "Почтовый сервер Tegu",
        "IceWarp Почтовый сервер",
        "RMS Удаленный доступ 7.1",
        "СЕТЕРЕ Архиватор",
        "3iTech Речевая аналитика",
        "EMS SQL Backup for SQL Server",
    ],
)
def test_r3_exact_product_title_always_first(env, title):
    for variant in (title, title.lower()):
        res = _ask(env, variant)
        titles = _titles(res)
        assert titles and titles[0] == title, f"{variant!r}: получили {titles[:3]}"
        assert res["understood"]["intent"] == "product", f"{variant!r}: intent={res['understood']['intent']}"
        note = (res["understood"].get("agent_note") or "").lower()
        assert "товаров этого производителя нет" not in note, note


def test_r3_generic_solution_not_broken_by_exact_title_rule(env):
    res = _ask(env, "резервное копирование")
    titles = _titles(res)
    assert any("бэкап" in t.lower() or "backup" in t.lower() for t in titles[:3]), titles[:3]


# --- 3. Распознавание текста != перевод ---


@pytest.mark.parametrize(
    "q",
    [
        "распознать скан документа и сохранить в word",
        "сканы в редактируемый текст",
        "оцифровать бумажные документы",
        "перевести скан документа в редактируемый текст",
        "перевести pdf в word",
    ],
)
def test_r3_ocr_beats_translator(env, q):
    titles = _titles(_ask(env, q))
    assert titles, f"Пусто для {q!r}"
    assert any("contentreader" in t.lower() for t in titles[:3]), f"{q!r}: {titles[:3]}"
    assert "promt" not in titles[0].lower(), f"{q!r}: ушло в переводчик {titles[:3]}"


def test_r3_translator_still_works_for_language_translation(env):
    titles = _titles(_ask(env, "перевести текст с английского на русский"))
    assert titles and "promt" in titles[0].lower(), titles[:3]


# --- 4. Задачи, которые раньше уходили мимо (12 направлений) ---


@pytest.mark.parametrize(
    "q,expected_sub,forbidden_sub",
    [
        ("вести историю клиентов и сделок", "битрикс24", None),
        ("обрезать и свести звук для подкаста", "audition", None),
        ("программа записать подкаст", "audition", None),
        ("ограничить детям доступ в интернет", "safe kids", None),
        ("как закрыть ребёнку доступ к нежелательным сайтам", "safe kids", "битрикс"),
        ("сжать файлы в архив", "winrar", None),
        ("чем распаковать архив rar", "winrar", None),
        ("не потерять данные при поломке диска", "бэкап", "safeerase"),
        ("как защитить файлы от поломки жесткого диска", "бэкап", "safeerase"),
        ("закрыть сеть офиса от атак", "traffic inspector", None),
        ("какой межсетевой экран поставить в офис", "traffic inspector", None),
        ("видеонаблюдение", "интеллект", None),
        ("конвертировать документы из формата в формат", "converter", None),
        ("преобразовать pdf в другой формат", "converter", None),
        ("подключаться к рабочему компьютеру из дома", "anydesk", "depo"),
        ("работать за офисным пк из дома", "anydesk", "depo"),
        ("проверить домашний компьютер на вирусы", "kaspersky standard", "endpoint"),
        ("почистить домашний ноутбук от вирусов", "kaspersky standard", "endpoint"),
        ("учёт компьютеров и ПО в компании", "инвентаризация", None),
        ("терминальный сервер", "termidesk", "rack-сервер"),
        ("сервер терминалов для удалённых пользователей", "termidesk", "rack-сервер"),
    ],
)
def test_r3_twelve_missing_tasks(env, q, expected_sub, forbidden_sub):
    titles = _titles(_ask(env, q))
    assert titles, f"Пустой ответ для {q!r}"
    top3 = " | ".join(titles[:3]).lower()
    assert expected_sub in top3, f"{q!r}: ожидали {expected_sub!r} в top3, получили {titles[:3]}"
    if forbidden_sub:
        assert forbidden_sub not in top3, f"{q!r}: не ожидали {forbidden_sub!r} в top3, получили {titles[:3]}"


# --- 5. Жаргон в задаче и прилагательные от вендора ---


def test_r3_slang_verbs_in_tasks(env):
    for q, expected in [
        ("виртуалки поднять на сервере", "zvirt"),
        ("на чём гонять виртуалки", "zvirt"),
        ("чем бэкапить серверы", "бэкап"),
        ("программа чтобы шарить экран", "trueconf"),
    ]:
        titles = _titles(_ask(env, q))
        assert titles, f"Пустой ответ для {q!r}"
        assert expected in " | ".join(titles[:3]).lower(), f"{q!r}: {titles[:3]}"


def test_r3_vendor_adjective_normalization_unit():
    assert normalize_vendor_adjectives("адобовский иллюстратор") == "адоб иллюстратор"
    assert normalize_vendor_adjectives("майкрософтовский офис") == "майкрософт офис"
    assert normalize_vendor_adjectives("касперовский антивирус") == "касперский антивирус"
    assert normalize_vendor_adjectives("асконовский сапр") == "аскон сапр"


def test_r3_vendor_adjectives_match_normal_queries(env):
    assert _titles(_ask(env, "майкрософтовский офис"))[:2] == _titles(_ask(env, "майкрософт офис"))[:2]
    assert _titles(_ask(env, "касперовский антивирус"))[:2] == _titles(_ask(env, "касперский антивирус"))[:2]
    res_adj = _ask(env, "адобовский иллюстратор")
    res_norm = _ask(env, "адоб иллюстратор")
    assert res_adj["understood"]["intent"] == res_norm["understood"]["intent"]
    assert _titles(res_adj)[:2] == _titles(res_norm)[:2]
