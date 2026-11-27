"""Тесты раунда 3 трека N4: допродажа к ИБП, товар + аппаратное назначение,
заголовок аппаратного блока, политика доли допродажи из kb и противоречивая аудитория."""
import json
from dataclasses import replace

import pytest
import yaml

from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Disabled
from kuznitsa.plans import feed_conditions
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def r3_engine(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n4_r3_feed")
    kb_dir = tmp_path_factory.mktemp("n4_r3_kb")
    # Копируем базу знаний, чтобы проверять реальные правила и политику из kb
    import shutil
    from kuznitsa.config import ROOT
    shutil.copytree(ROOT / "kb", kb_dir, dirs_exist_ok=True)

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
        lic=None,
        offers_count=1,
    ):
        for i in range(offers_count):
            rows.append(
                dict(
                    offer_id=f"{oid}_{i}" if i else oid,
                    group_id=oid,
                    name=title,
                    family_name=title,
                    class_id=section_id,
                    category_id=section_id,
                    category_path=[root, section_name],
                    domain=domain,
                    vendor=vendor,
                    price=price + i * 100,
                    attrs={"domain": domain},
                    lic=lic or {"model": "subscription", "term_months": 12, "metric": "device"},
                    available=True,
                    in_stock=True,
                )
            )

    # 1. ИБП (82080) + сменная батарея (82014) + сетевой фильтр (82661) + PDU (131130)
    # Намеренно даём фильтру и PDU больше офферов (выше quality), чтобы проверить приоритет батареи!
    for model in ("Powercom WOW WOW-300", "Powercom WOW WOW-500U", "APC Back-UPS BX650", "Ippon Back Basic 850", "CyberPower UT650"):
        slug = model.lower().replace(" ", "_").replace("-", "_")
        add(f"ups_{slug}", f"ИБП {model}", "82080", "ИБП (Источники бесперебойного питания)", root="Оборудование", domain="hardware", vendor="Powercom", price=6500)
    add("bat_delta", "Сменная батарея для ИБП Delta DTM", "82014", "Сменные батареи для ИБП", root="Оборудование", domain="hardware", vendor="Delta", price=2100, offers_count=1)
    add("surge_pcpet", "Сетевой фильтр PC Pet AP01006", "82661", "Сетевые фильтры и стабилизаторы", root="Оборудование", domain="hardware", vendor="PC Pet", price=900, offers_count=12)
    add("pdu_lan", "для ИБП Lanmaster PDU", "131130", "Аксессуары для ИБП", root="Оборудование", domain="hardware", vendor="Lanmaster", price=4500, offers_count=12)

    # 2. Российские ОС + сопутствующее ПО + аппаратные разделы (Ноутбуки / Десктопы / Серверы)
    add("red_os", "Операционная система РЕД ОС", "222320", "Российские операционные системы", vendor="РЕД СОФТ", price=5500)
    add("red_adm", "РЕД АДМ", "2942", "Управление инфраструктурой", vendor="РЕД СОФТ", price=7500)
    add("red_virt", "РЕД Виртуализация", "222321", "Виртуализация", vendor="РЕД СОФТ", price=18000)
    add("alt_ws", "Альт Рабочая станция 11", "222320", "Российские операционные системы", vendor="Базальт СПО", price=4900)
    add("alt_srv", "Альт Сервер 11", "222320", "Российские операционные системы", vendor="Базальт СПО", price=15900)
    add("alt_sp", "Альт СП 10", "222320", "Российские операционные системы", vendor="Базальт СПО", price=12900)
    add("k_mail_srv", "Kaspersky Security для почтовых серверов", "650", "Антивирусы для организаций", vendor="Лаборатория Касперского", price=14000)
    add("k_gw", "Kaspersky Security для интернет-шлюзов", "650", "Антивирусы для организаций", vendor="Лаборатория Касперского", price=16000)
    add("k_kes", "Kaspersky Endpoint Security для бизнеса Стандартный", "650", "Антивирусы для организаций", vendor="Лаборатория Касперского", price=3100, lic={"model": "subscription", "term_months": 12, "metric": "device", "audience": "business"})
    add("k_ksos", "Kaspersky Small Office Security", "650", "Антивирусы для организаций", vendor="Лаборатория Касперского", price=4500, lic={"model": "subscription", "term_months": 12, "metric": "device", "audience": "business"})
    add("drweb_desk", "Dr.Web Desktop Security Suite", "650", "Антивирусы для организаций", vendor="Доктор Веб", price=2200, lic={"model": "subscription", "term_months": 12, "metric": "device", "audience": "business"})
    add("cyber_bkp", "Кибер Бэкап Стандартная редакция", "1033", "Резервное копирование", vendor="Киберпротект", price=8900)
    add("myoffice_std", "МойОфис Стандартный 3", "222323", "Российские офисные приложения", vendor="МойОфис", price=4200)
    add("cpro", "Программа КриптоПро CSP 5.0", "687", "Средства криптографической защиты", vendor="КриптоПро", price=2700)

    # 3. Домашние антивирусы (3775) — включая PRO32 с точным qty=2 и флагманы Kaspersky / Dr.Web
    add("pro32_tot", "PRO32 Total Security", "3775", "Антивирусы для дома и семьи", vendor="PRO32", price=1200, lic={"model": "subscription", "term_months": 12, "metric": "device", "qty_min": 2, "qty_max": 2, "audience": "home"})
    add("pro32_ult", "PRO32 Ultimate Security", "3775", "Антивирусы для дома и семьи", vendor="PRO32", price=1500, lic={"model": "subscription", "term_months": 12, "metric": "device", "qty_min": 2, "qty_max": 2, "audience": "home"})
    add("k_std", "Kaspersky Standard", "3775", "Антивирусы для дома и семьи", vendor="Лаборатория Касперского", price=1700, lic={"model": "subscription", "term_months": 12, "metric": "device", "audience": "home"})
    add("k_plus", "Kaspersky Plus + Who Calls", "3775", "Антивирусы для дома и семьи", vendor="Лаборатория Касперского", price=2400, lic={"model": "subscription", "term_months": 12, "metric": "device", "audience": "home"})
    add("drweb_ss", "Dr.Web Security Space", "3775", "Антивирусы для дома и семьи", vendor="Доктор Веб", price=1900, lic={"model": "subscription", "term_months": 12, "metric": "device", "audience": "home"})

    # 4. Оборудование: ноутбуки (8 штук для проверки доли допродажи на странице из 8), десктопы, точки доступа Wi-Fi
    for i in range(1, 10):
        add(f"nb_{i}", f"Ноутбук ASUS ExpertBook B{i}", "70824", "Ноутбуки", root="Оборудование", domain="hardware", vendor="ASUS", price=55000 + i * 2000)
    add("pc_1", "Настольный компьютер HP ProDesk 400", "70187", "Десктопы", root="Оборудование", domain="hardware", vendor="HP", price=49000)
    add("pc_2", "Настольный компьютер Lenovo ThinkCentre", "70187", "Десктопы", root="Оборудование", domain="hardware", vendor="Lenovo", price=52000)
    for i in range(1, 5):
        add(f"ap_{i}", f"Точка доступа Wi-Fi Ubiquiti UniFi U6-{i}", "86348", "Точки доступа", root="Оборудование", domain="hardware", vendor="Ubiquiti", price=14000 + i * 1000)

    # Для роли «бухгалтер» в допродаже к ноутбукам
    add("buh_1c", "1С:Бухгалтерия 8 ПРОФ", "11763", "Бухгалтерский учёт", vendor="1С", price=16000)

    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    (data / "feed_meta.json").write_text(json.dumps({"snapshot": "n4_r3", "source": "test"}), encoding="utf-8")
    (data / "clients.json").write_text(
        json.dumps(
            [
                {"client_id": "guest", "title": "Гость", "segment": "individual", "size_seats": 1},
                {"client_id": "smb_co", "title": "ООО Малый Бизнес", "segment": "smb", "size_seats": 10},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data / "merch.yaml").write_text("rules: []\nbanners: []\n", encoding="utf-8")

    eng = Engine.open(replace(cfg, data=data, kb=kb_dir), llm=Disabled())
    yield eng
    eng.close()


def test_ups_upsell_battery_first(r3_engine):
    """1. Для карточек ИБП первой плиткой идёт сменная батарея (82014), сетевой фильтр и PDU — после."""
    idx = r3_engine.catalog.feed
    for q in (
        "ИБП Powercom WOW WOW-300",
        "ИБП Powercom WOW WOW-500U",
        "ИБП APC Back-UPS BX650",
        "ИБП Ippon Back Basic 850",
        "ИБП CyberPower UT650",
    ):
        res = r3_engine.search(Request(q=q, mode="fast", page_size=8))
        items = res["blocks"][0]["items"]
        upsells = [c for c in items if c.get("kind") == "upsell"]
        assert upsells, f"Нет плитки допродажи для {q}"
        assert idx.card_sections[upsells[0]["card_id"]] == "82014", (
            f"Первой плиткой должна быть батарея 82014, получено {upsells[0]['title']}"
        )
        cross = [x["card"] for b in res["blocks"] if b["type"] == "crosssell" for x in b["items"]]
        cross_secs = [idx.card_sections[c["card_id"]] for c in cross]
        assert "82661" in cross_secs or "131130" in cross_secs


def test_software_product_with_hardware_purpose(r3_engine):
    """2. Программный продукт + «для компьютеров/ноутбуков/серверов» не уходит в аппаратный раздел."""
    for q, expected_sub in (
        ("ред ос для ноутбуков сотрудников", "ред ос"),
        ("альт рабочая станция для компьютеров в классе", "альт рабочая станция"),
        ("касперский для серверов", "kaspersky"),
    ):
        res = r3_engine.search(Request(q=q, mode="fast", page_size=8))
        note = res["understood"].get("agent_note", "")
        assert "товаров этого производителя нет" not in note.lower(), f"Ложный vendor_gap на {q}: {note}"
        items = res["blocks"][0]["items"]
        main = [c for c in items if c.get("kind") != "upsell"]
        assert main and main[0]["domain"] == "software"
        assert expected_sub in main[0]["title"].lower(), f"{q} -> {main[0]['title']}"

    # Для ОС в допродаже (плитки + crosssell) присутствуют антивирус (650) и резервное копирование (1033)
    idx = r3_engine.catalog.feed
    for os_q in ("ред ос для ноутбуков сотрудников", "альт рабочая станция для компьютеров в классе"):
        res = r3_engine.search(Request(q=os_q, mode="fast", page_size=8))
        rec_cids = [c["card_id"] for c in res["blocks"][0]["items"] if c.get("kind") == "upsell"]
        rec_cids += [x["card"]["card_id"] for b in res["blocks"] if b["type"] == "crosssell" for x in b["items"]]
        rec_secs = {idx.card_sections[cid] for cid in rec_cids}
        assert "650" in rec_secs, f"Для {os_q} в допродаже должен быть антивирус (650), получено {rec_secs}"
        assert "1033" in rec_secs, f"Для {os_q} в допродаже должен быть бэкап (1033), получено {rec_secs}"


def test_hardware_block_title_not_licenses(r3_engine):
    """3. Для аппаратных ответов заголовок блока — название раздела или «Подходящие товары», не «Подходящие лицензии»."""
    for q in ("точка доступа wifi", "ноутбук", "ИБП Powercom WOW WOW-300"):
        res = r3_engine.search(Request(q=q, mode="fast", page_size=8))
        b0 = res["blocks"][0]
        assert b0["type"] == "products"
        assert "лиценз" not in b0["title"].lower(), f"Неверный заголовок для {q}: {b0['title']}"


def test_upsell_share_and_kb_policy_control(r3_engine, monkeypatch):
    """4. На 8 карточек не больше 3 плиток, первая не раньше 3-й позиции, не подряд; управляется из kb."""
    assert r3_engine.kb.upsell_policy.get("max_per_page") == 3
    assert r3_engine.kb.upsell_policy.get("min_first_position") == 3

    for q in ("ноутбук для бухгалтера", "ноутбук"):
        res = r3_engine.search(Request(q=q, mode="fast", page_size=8))
        items = res["blocks"][0]["items"]
        up_pos = [i + 1 for i, c in enumerate(items) if c.get("kind") == "upsell"]
        assert len(up_pos) <= 3, f"{q}: слишком много плиток {up_pos}"
        if up_pos:
            assert up_pos[0] >= 3, f"{q}: первая плитка раньше 3-й позиции: {up_pos}"
        assert all(b - a > 1 for a, b in zip(up_pos, up_pos[1:])), f"{q}: две плитки подряд: {up_pos}"

    # Проверяем, что правило реально управляется из kb.upsell_policy (без правки кода)
    strict_policy = dict(r3_engine.kb.upsell_policy, max_per_page=1, min_first_position=5)
    monkeypatch.setattr(r3_engine.kb, "upsell_policy", strict_policy)
    res_strict = r3_engine.search(Request(q="ноутбук для бухгалтера", mode="fast", page_size=8))
    up_pos_strict = [i + 1 for i, c in enumerate(res_strict["blocks"][0]["items"]) if c.get("kind") == "upsell"]
    assert len(up_pos_strict) <= 1
    if up_pos_strict:
        assert up_pos_strict[0] >= 5


def test_contradictory_home_and_smb_audience(r3_engine):
    """5. При явном «домашний» + «небольшая фирма / ИП» в топ-4 входят домашние редакции и малый бизнес-пакет."""
    for q in (
        "антивирус для дома на 2 компьютера, покупает небольшая фирма",
        "домашняя защита на 4 устройства для ИП",
    ):
        smb_ids = [cid for cid, pr in r3_engine.clients.items() if cid != "guest" and getattr(pr, "segment", None) == "smb"]
        client_ids = ["guest"] + smb_ids[:1]
        for client in client_ids:
            res = r3_engine.search(Request(q=q, mode="fast", page_size=8, profile_id=client))
            top4 = [c["title"].lower() for c in res["blocks"][0]["items"][:4]]
            has_home = any(
                ("kaspersky standard" in t or "kaspersky plus" in t or "dr.web security space" in t)
                for t in top4
            )
            has_smb = any("small office" in t for t in top4)
            assert has_home, f"[{client}] {q}: нет домашней редакции в топ-4: {top4}"
            assert has_smb, f"[{client}] {q}: нет малого бизнес-пакета в топ-4: {top4}"
