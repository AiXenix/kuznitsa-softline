"""Тесты второго захода потока N2: роли, совместимость, услуги, миграции, длинные запросы, generic-guard и kb-check."""
from dataclasses import replace
import json
from pathlib import Path
from shutil import copyfile, copytree

import pytest

from kuznitsa.cli import main as cli_main
from kuznitsa.engine import Engine
from kuznitsa.evaluation import cards_from
from kuznitsa.llm.jev import Disabled
from kuznitsa.plans.feed_query import (
    extract_os_compat,
    migration_target,
    strip_question,
)
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def env(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n2_r2")
    kb = copytree(cfg.kb, data / "kb")
    copyfile(Path("kb/feed_solutions.yaml"), kb / "feed_solutions.yaml")
    rows = []

    def add(
        cid,
        title,
        section,
        vendor="SoftVendor",
        domain="software",
        price=5000,
        offers=None,
        domestic=False,
        registry=False,
        platforms=None,
    ):
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
                    domestic=off.get("domestic", domestic),
                    registry=off.get("registry", registry),
                    platforms=off.get("platforms", platforms or []),
                    lic=off.get("lic", {}),
                )
            )

    # Ловушки для GENERIC_HEAD (железо «Система ...» и случайное «Программное обеспечение ...»)
    add("hw_cool", "Система водяного охлаждения Thermalright", "Системы охлаждения", vendor="Thermalright", domain="hardware", price=9000)
    add("sw_msdn", "Программное обеспечение MSDN Platforms", "Средства разработки", vendor="Microsoft", price=120000)

    # Удалённый доступ и бэкап
    add("sw_ra1", "АССИСТЕНТ Удалённый доступ", "Удалённый доступ", vendor="САФИБ", domestic=True, registry=True)
    add("sw_ra2", "RuDesktop", "Удалённый доступ", vendor="RuDesktop", domestic=True, registry=True)
    add("sw_bk1", "Киберпротект Кибер Бэкап Стандартная", "Программное обеспечение для резервного копирования", vendor="Киберпротект", domestic=True, registry=True)
    add("sw_bk2", "RuBackup OneClick", "Программное обеспечение для резервного копирования", vendor="Группа Астра", domestic=True, registry=True)
    add("sw_bk3", "Arcserve Backup", "Программное обеспечение для резервного копирования", vendor="Arcserve")
    add("sw_bk4", "Handy Backup Server", "Программное обеспечение для резервного копирования", vendor="Новософт", domestic=True)

    # Офис (российский + Microsoft)
    add("sw_r7", "Р7-Офис. Для бизнеса", "Российское офисное ПО (Импортозамещение)", vendor="Р7", domestic=True, registry=True, platforms=["Linux", "Windows"])
    add("sw_mo", "МойОфис Стандартный 3", "Российское офисное ПО (Импортозамещение)", vendor="МойОфис", domestic=True, registry=True, platforms=["Linux", "Windows"])
    add("sw_ms", "Microsoft Office 2024 для дома и бизнеса", "Офисные пакеты программ Microsoft Office", vendor="Microsoft", platforms=["Windows"])
    add("sw_xl", "Microsoft Excel", "Офисные пакеты программ Microsoft Office", vendor="Microsoft", platforms=["Windows"])

    # САПР + DWG
    add("sw_cad1", "КОМПАС-3D V25", "Системы автоматизированного проектирования (САПР)", vendor="АСКОН", domestic=True, registry=True, platforms=["Linux", "Windows"])
    add("sw_cad2", "Платформа nanoCAD 26", "Системы автоматизированного проектирования (САПР)", vendor="Нанософт Разработка", domestic=True, registry=True, platforms=["Linux", "Windows"])
    add("sw_cad3", "nanoCAD Конструкции PS для Linux", "Системы автоматизированного проектирования (САПР)", vendor="Нанософт Разработка", domestic=True, registry=True, platforms=["Linux"])
    add("sw_cad4", "Autodesk AutoCAD", "Системы автоматизированного проектирования (САПР)", vendor="Autodesk", platforms=["Windows"])
    add("sw_dwg", "ABViewer", "Системы автоматизированного проектирования (САПР)", vendor="CADSoftTools", platforms=["Windows"])

    # ОС (Astra Linux, РЕД ОС, Windows)
    add("sw_as1", "Astra Linux Special Edition", "Российские операционные системы (Импортозамещение)", vendor="Группа Астра", domestic=True, registry=True)
    add("sw_as2", "Astra Linux Common Edition", "Российские операционные системы (Импортозамещение)", vendor="Группа Астра", domestic=True, registry=True)
    add("sw_as3", "Операционная система РЕД ОС", "Российские операционные системы (Импортозамещение)", vendor="РЕД СОФТ", domestic=True, registry=True)
    add("sw_win", "Microsoft Windows 11 Pro", "Операционные системы Windows", vendor="Microsoft")
    add("sw_astra_dci", "DCImanager", "Управление инфраструктурой", vendor="Группа Астра", domestic=True)

    # Антивирусы + серверный + поддержка + курсы
    add("sw_ks_srv", "Kaspersky Security для Windows Server", "Антивирусы для организаций", vendor="Лаборатория Касперского", domestic=True, registry=True)
    add("sw_dw_srv", "Доктор Веб Dr.Web Server Security Suite", "Антивирусы для организаций", vendor="Доктор Веб", domestic=True, registry=True)
    add("sw_ks_std", "Kaspersky Standard", "Антивирусы для дома", vendor="Лаборатория Касперского", domestic=True, registry=True)
    add("sw_ks_sup", "Kaspersky Softline Expert Services", "Сервисы и поддержка", vendor="Лаборатория Касперского", domestic=True)
    add("sw_dw_ss", "Доктор Веб Dr.Web Security Space", "Антивирусы для дома", vendor="Доктор Веб", domestic=True, registry=True)

    # КриптоПро (только action="new", без отдельного action="renewal")
    add(
        "sw_csp",
        "Программа КриптоПро CSP 5.0",
        "Программы для защиты информации",
        vendor="КриптоПро",
        domestic=True,
        registry=True,
        offers=[dict(offer_id="csp_new", name="КриптоПро CSP 5.0 бессрочная", price=2700, lic={"action": "new"})],
    )

    # Видеомонтаж (проверка коллизии вендор-алиаса «видеомонтаж» -> AMS Software)
    add("sw_vid1", "Мовавика Видео", "Видеоредакторы", vendor="Мовавика", domestic=True)
    add("sw_vid2", "AMS Software ВидеоМОНТАЖ", "Видеоредакторы", vendor="AMS Software", domestic=True)
    add("sw_vid3", "Wondershare Filmora", "Видеоредакторы", vendor="Wondershare")

    # Учебные курсы каталога (для fallback в resolve_service_query)
    add("sw_crs1", "Учебный центр Softline IT-курс для специалистов", "Курсы и обучение", vendor="Softline", domestic=True)
    add("sw_crs2", "Labmedia «Электронный курс»", "Курсы и обучение", vendor="Labmedia", domestic=True)

    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    engine = Engine.open(replace(cfg, data=data, kb=kb), llm=Disabled())
    try:
        yield engine
    finally:
        engine.close()


def _search(engine, q):
    return engine.search(Request(q=q, mode="fast", source="eval"))


def test_unit_migration_and_os_compat_and_commercial_strip():
    mig = migration_target("переход с windows на astra linux")
    assert mig is not None and mig[0] == "windows" and mig[1] == "astra linux"
    mig_r7 = migration_target("миграция с microsoft office на р7")
    assert mig_r7 is not None and mig_r7[1] == "р7 офис"

    subj, tag, label = extract_os_compat("сапр для astra linux")
    assert subj == "сапр" and tag == "linux" and label == "Astra Linux"
    subj2, tag2, _ = extract_os_compat("просто сапр")
    assert subj2 == "просто сапр" and tag2 is None

    assert strip_question("докупить лицензии dr.web") == "dr.web"
    assert strip_question("докупить дополнительные лицензии kaspersky") == "kaspersky"
    assert strip_question("расширение лицензии kaspersky") == "kaspersky"


def test_generic_head_does_not_hijack_task_queries(env):
    r1 = _search(env, "система для удаленного подключения к пк сотрудников")
    titles1 = [c["title"] for c in cards_from(r1["blocks"])]
    assert any("АССИСТЕНТ" in t or "RuDesktop" in t for t in titles1[:3])
    assert not any("Thermalright" in t for t in titles1[:4])

    r2 = _search(env, "программное обеспечение для резервного копирования виртуальных машин")
    titles2 = [c["title"] for c in cards_from(r2["blocks"])]
    assert any("Бэкап" in t or "RuBackup" in t for t in titles2[:3])
    assert not any("MSDN" in t for t in titles2[:4])


def test_os_compat_cad_and_office_on_linux(env):
    r_cad = _search(env, "сапр для astra linux")
    titles_cad = [c["title"] for c in cards_from(r_cad["blocks"])]
    assert any("nanoCAD" in t or "КОМПАС" in t for t in titles_cad[:3])
    assert not any("DCImanager" in t for t in titles_cad[:4])
    assert not any("Autodesk" in t for t in titles_cad[:4])
    assert any(ch.get("key") == "platform" for ch in r_cad["understood"]["chips"])

    r_off = _search(env, "офисный пакет для linux")
    titles_off = [c["title"] for c in cards_from(r_off["blocks"])]
    assert any("Р7-Офис" in t or "МойОфис" in t for t in titles_off[:3])
    assert not any("Microsoft" in t for t in titles_off[:4])

    r_srv = _search(env, "антивирус для windows server")
    titles_srv = [c["title"] for c in cards_from(r_srv["blocks"])]
    assert any("Windows Server" in t or "Server Security" in t for t in titles_srv[:3])


def test_solution_respects_origin_and_registry_conditions(env):
    r = _search(env, "поставка лицензий офисного пакета из реестра российского по на 30 рабочих мест")
    titles = [c["title"] for c in cards_from(r["blocks"])]
    assert any("Р7-Офис" in t or "МойОфис" in t for t in titles[:3])
    assert not any("Microsoft" in t for t in titles[:4])


def test_migration_target_routing_and_nofix(env):
    r1 = _search(env, "переход с windows на astra linux")
    titles1 = [c["title"] for c in cards_from(r1["blocks"])]
    assert titles1 and any("Astra Linux" in t for t in titles1[:3])

    r2 = _search(env, "миграция с microsoft office на р7")
    titles2 = [c["title"] for c in cards_from(r2["blocks"])]
    assert titles2 and any("Р7-Офис" in t for t in titles2[:3])
    assert r2["query"]["corrections"] == []


def test_service_queries_direct_and_honest_fallback(env):
    # Прямой сервис поддержки в каталоге (Kaspersky Softline Expert Services)
    r_sup = _search(env, "техподдержка касперский")
    titles_sup = [c["title"] for c in cards_from(r_sup["blocks"])]
    assert titles_sup and "Expert Services" in titles_sup[0]

    # Обучение, которого нет отдельным товаром: честное пояснение + сам продукт + близкие курсы
    r_tr = _search(env, "обучение astra linux")
    titles_tr = [c["title"] for c in cards_from(r_tr["blocks"])]
    assert len(titles_tr) >= 3
    assert any("Astra Linux" in t for t in titles_tr[:4])
    assert any("курс" in t.lower() for t in titles_tr)
    assert "не выделено" in (r_tr["understood"]["agent_note"] or "").lower()

    r_xl = _search(env, "курсы excel")
    titles_xl = [c["title"] for c in cards_from(r_xl["blocks"])]
    assert len(titles_xl) >= 3
    assert any("Excel" in t for t in titles_xl[:4])


def test_renewal_fallback_keeps_product_intent_and_commercial_wrappers(env):
    r_ren = _search(env, "продление криптопро")
    titles_ren = [c["title"] for c in cards_from(r_ren["blocks"])]
    assert r_ren["understood"]["intent"] != "out_of_catalog"
    assert any("КриптоПро" in t for t in titles_ren[:3])

    r_buy = _search(env, "докупить лицензии dr.web")
    titles_buy = [c["title"] for c in cards_from(r_buy["blocks"])]
    assert any("Dr.Web" in t for t in titles_buy[:3])


def test_vendor_alias_collision_does_not_steal_video_editing(env):
    r = _search(env, "софт для видеомонтажа")
    titles = [c["title"] for c in cards_from(r["blocks"])]
    assert any("Мовавика" in t or "ВидеоМОНТАЖ" in t or "Filmora" in t for t in titles[:3])


def test_kb_check_runs_feed_solutions_check_snapshot(monkeypatch, capsys):
    rc = cli_main(["kb-check"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["errors"] == []


def test_restore_platform_subject_for_license_question(env):
    r = _search(env, "где купить лицензию на windows?")
    titles = [c["title"] for c in cards_from(r["blocks"])]
    assert titles and any("Windows" in t for t in titles[:3])


def test_training_phrase_with_work_in_prefix(env):
    r = _search(env, "обучение работе в microsoft excel")
    titles = [c["title"] for c in cards_from(r["blocks"])]
    assert len(titles) >= 3
    assert any("Excel" in t for t in titles[:4])
