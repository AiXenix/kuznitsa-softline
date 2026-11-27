"""Тесты второго захода потока N1: разговорные названия, англ. классы, аналоги, пустой ввод и уход в старый конвейер."""
from dataclasses import replace
import json
from shutil import copytree

import pytest

from kuznitsa.config import Config
from kuznitsa.engine import Engine, Trace
from kuznitsa.evaluation import cards_from
from kuznitsa.llm.jev import Disabled
from kuznitsa.plans import feed as feed_plan, feed_guard, feed_noise
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def n1_r2_engine(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n1_r2_feed")
    kb = copytree(Config().kb, data / "kb")

    rows = []

    def add(cid, title, section, vendor, *, domain="software", price=25000, offers=1, lic=None):
        for i in range(offers):
            rows.append(
                dict(
                    group_id=cid,
                    offer_id=f"{cid}-{i + 1}",
                    family_id=cid,
                    family_name=title,
                    name=f"{title} (вариант {i + 1})" if i else title,
                    domain=domain,
                    category_id=section,
                    class_id=section,
                    category_path=["Программы", section],
                    vendor=vendor,
                    price=price + i * 100,
                    available=True,
                    lic=lic or dict(metric="device", qty_min=1, qty_max=100),
                )
            )

    # Microsoft Office standalone apps + suites + Windows
    add("ms_word", "Microsoft Office Word 2021", "Офисные пакеты программ Microsoft Office", "Программы и лицензии Microsoft Corporation", price=14000, offers=5)
    add("ms_excel", "Microsoft Office Excel 2021", "Офисные пакеты программ Microsoft Office", "Программы и лицензии Microsoft Corporation", price=14000, offers=5)
    add("ms_outlook", "Microsoft Office Outlook 2021", "Офисные пакеты программ Microsoft Office", "Программы и лицензии Microsoft Corporation", price=14000, offers=5)
    add("ms_office", "Microsoft Office Standard 2021", "Офисные пакеты программ Microsoft Office", "Программы и лицензии Microsoft Corporation", price=42000, offers=8)
    add("win11_pro", "Microsoft Windows 11 Pro", "Операционные системы", "Microsoft", price=28000, offers=4)
    add("win10_pro", "Microsoft Windows 10 Pro", "Операционные системы", "Microsoft", price=24000, offers=3)

    # САПР и архитектура (с отброшенным префиксом вендора, как в real/v1)
    add("kompas_v25", "КОМПАС-3D V25", "Программы для машиностроения", "АСКОН", price=110000, offers=10)
    add("kompas_kits", "Комплекты КОМПАС-3D: Механика", "Программы для машиностроения", "АСКОН", price=150000, offers=2)
    add("kompas_graph", "КОМПАС-График V25", "Программы для машиностроения", "АСКОН", price=75000, offers=6)
    add("nanocad_26", "Платформа nanoCAD 26", "Базовые программы", "Нанософт Разработка", price=65000, offers=8)
    add("autocad", "Autodesk AutoCAD", "Базовые программы", "Autodesk", price=120000, offers=4)
    add("archicad_1", "Graphisoft Archicad", "Программы для архитекторов", "Graphisoft", price=140000, offers=6)
    add("archicad_2", "Graphisoft Archicad Solo", "Программы для архитекторов", "Graphisoft", price=95000, offers=3)
    add("archicad_3", "Graphisoft Archicad STAR(T) Edition", "Программы для архитекторов", "Graphisoft", price=85000, offers=3)
    add("archicad_4", "Graphisoft Archicad 26 Forward", "Системы автоматизации", "Graphisoft", price=160000, offers=2)
    add("auto_trash", "Автокаталог запчастей", "Системы автоматизации", "АвтоСофт", price=15000, offers=2)

    # Графика и вендор Corel (флагман CorelDRAW vs PaintShop)
    add("photoshop", "Adobe Photoshop", "Графические редакторы", "Adobe Systems", price=35000, offers=8)
    add("corel_paint", "Corel PaintShop Pro 2023", "Графические редакторы", "Corel Corporation", price=12000, offers=2)
    add("corel_draw", "CorelDRAW Graphics Suite 2026", "Графические редакторы", "Corel Corporation", price=49000, offers=6)

    # Безопасность: Код безопасности, КриптоПро, антивирусы, NGFW, бэкапы, почта
    add("sns", "Код безопасности: Secret Net Studio 8", "Программы для защиты информации", "Код безопасности", price=18000, offers=8)
    add("sobol", "Код безопасности: ПАК «Соболь» 4.0", "Программы для защиты информации", "Код безопасности", price=22000, offers=5)
    add("sn_lsp", "Код безопасности: Secret Net LSP", "Программы для защиты информации", "Код безопасности", price=16000, offers=4)
    add("strazh", "Страж NT 4.0", "Программы для защиты информации", "Рубинтех", price=15000, offers=4)
    add("cpro_csp", "КриптоПро CSP 5.0", "Программы для защиты информации", "КриптоПро", price=2700, offers=4)
    add("cpro_jcp", "КриптоПро JCP 2.0", "Программы для защиты информации", "КриптоПро", price=9000, offers=2)
    add("kes", "Kaspersky Endpoint Security", "Антивирусы для организаций", "«Лаборатория Касперского»", price=12000, offers=6)
    add("drweb", "Dr.Web Security Space", "Антивирусы для организаций", "Доктор Веб", price=9000, offers=5)
    add("ug_ngfw", "UserGate NGFW", "Сетевые экраны", "UserGate", price=85000, offers=4)
    add("cyber_bkp", "Кибер Бэкап Стандартный", "Программное обеспечение для резервного копирования", "Киберпротект", price=19000, offers=5)
    add("cgpro", "CommuniGate Pro", "Российская коммуникационная платформа (Импортозамещение)", "АО «СБК»", price=35000, offers=5)
    add("tegu", "Почтовый сервер Tegu", "Почтовые утилиты", "Лаборатория МБК", price=29000, offers=4)
    add("bitrix24", "1С-Битрикс24", "Программное обеспечение для создания сайтов", "1С-Битрикс", price=24000, offers=6)
    add("r7", "Р7-Офис Профессиональный", "Офисные пакеты программ", "Р7", price=6000, offers=5)
    add("pm_1", "Мегаплан", "Программы для управления проектами", "Мегаплан", price=11000, offers=4)
    add("pm_2", "Битрикс24 Управление задачами", "Программы для управления проектами", "1С-Битрикс", price=12000, offers=3)
    add("pm_3", "Адванта", "Программы для управления проектами", "Адванта", price=45000, offers=3)
    add("pm_4", "ProjectMate", "Программы для управления проектами", "ProjectMate", price=22000, offers=3)
    add("legal_srv", "Сертификат на оказание юридических услуг", "Правовое и кадровое обслуживание", "Точка Опоры", price=15000, offers=2)
    add("client_plus", "Клиент Плюс CRM", "CRM системы", "ПлюсСофт", price=19000, offers=3)

    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return Engine.open(replace(cfg, kb=kb, data=data), llm=Disabled())


@pytest.mark.parametrize("q", ["", "   ", "!!!", "???", "😀", ".", "*", "а", "z", "asdfghjkl", "qwertyuiop"])
def test_empty_symbolic_and_mash_return_zero_cards_without_legacy_fallback(n1_r2_engine, q):
    req = Request(q=q, mode="fast")
    res = n1_r2_engine.search(req)
    assert cards_from(res["blocks"]) == [], q
    assert not any(b["type"] in ("products", "analogs") and b.get("items") for b in res["blocks"]), q
    assert res["understood"]["zero_reason"] == "unknown_term", q
    # Не уходит в старый конвейер Engine._search
    direct = feed_plan.search(n1_r2_engine, req, n1_r2_engine.clients["guest"], Trace(n1_r2_engine.timer), (), False)
    assert direct is not None, q


@pytest.mark.parametrize("q,expected", [
    ("ворд", "word"),
    ("купить ворд", "word"),
    ("эксель", "excel"),
    ("аутлук", "outlook"),
    ("fotoshop", "photoshop"),
    ("битрикс 24", "битрикс24"),
    ("мс офис", "microsoft office"),
    ("m$ office", "microsoft office"),
    ("windows 11 pro license", "windows 11 pro"),
    ("компас 3d", "компас-3d v25"),
    ("архикад", "archicad"),
])
def test_colloquial_and_noisy_products_verified_in_catalog(n1_r2_engine, q, expected):
    res = n1_r2_engine.search(Request(q=q, mode="fast"))
    cards = cards_from(res["blocks"])
    assert cards, q
    assert expected in cards[0]["title"].lower(), (q, [c["title"] for c in cards[:3]])
    assert res["understood"]["zero_reason"] is None
    assert not any(b["type"] == "not_in_catalog" for b in res["blocks"])
    if q == "компас 3d":
        assert "этого производителя нет" not in (res["understood"].get("agent_note") or "").lower()
    if q == "архикад":
        assert not any("автокаталог" in c["title"].lower() for c in cards[:4])


def test_colloquial_dict_does_not_hallucinate_absent_product(n1_r2_engine):
    # "директум" есть в словаре spoken_products, но отсутствует в фикстуре n1_r2_engine
    assert feed_guard.resolve_colloquial_product(n1_r2_engine, "директум") is None


def test_vendor_code_of_security_and_corel_flagship_order(n1_r2_engine):
    res_kb = n1_r2_engine.search(Request(q="код безопасности", mode="fast"))
    titles_kb = [c["title"].lower() for c in cards_from(res_kb["blocks"])[:3]]
    assert any("secret net studio" in t for t in titles_kb), titles_kb

    res_corel = n1_r2_engine.search(Request(q="corel", mode="fast"))
    cards_corel = cards_from(res_corel["blocks"])
    assert cards_corel and "coreldraw" in cards_corel[0]["title"].lower(), [c["title"] for c in cards_corel[:3]]


@pytest.mark.parametrize("eng_q,ru_expected", [
    ("antivirus", "антивирус"),
    ("cad software", "сапр"),
    ("office suite for business", "офисный пакет для бизнеса"),
    ("project management", "управление проектами"),
    ("firewall", "межсетевой экран"),
])
def test_english_classes_translate_and_return_relevant_cards(n1_r2_engine, eng_q, ru_expected):
    assert feed_noise.translate_english_class(eng_q) == ru_expected
    res = n1_r2_engine.search(Request(q=eng_q, mode="fast"))
    cards = cards_from(res["blocks"])
    assert cards, eng_q
    assert res["understood"]["zero_reason"] is None


def test_honest_absent_acronis_dallas_lock_and_consultant_plus(n1_r2_engine):
    res_acr = n1_r2_engine.search(Request(q="acronis", mode="fast"))
    assert res_acr["understood"]["intent"] == "out_of_catalog"
    assert any(b["type"] == "not_in_catalog" for b in res_acr["blocks"])
    assert any("кибер бэкап" in c["title"].lower() for c in cards_from(res_acr["blocks"])[:4])

    res_dl = n1_r2_engine.search(Request(q="dallas lock", mode="fast"))
    assert res_dl["understood"]["intent"] == "out_of_catalog"
    titles_dl = [c["title"].lower() for c in cards_from(res_dl["blocks"])[:4]]
    assert any("secret net" in t or "страж" in t for t in titles_dl), titles_dl

    assert feed_noise.is_edition_only("плюс")
    res_cp = n1_r2_engine.search(Request(q="консультант плюс", mode="fast"))
    assert res_cp["understood"]["intent"] == "out_of_catalog"
    titles_cp = [c["title"].lower() for c in cards_from(res_cp["blocks"])[:6]]
    assert not any("клиент плюс" in t for t in titles_cp), titles_cp


def test_analog_binding_repair_and_import_substitution_exchange(n1_r2_engine):
    res_cad = n1_r2_engine.search(Request(q="российский аналог autocad", mode="fast"))
    titles_cad = [c["title"].lower() for c in cards_from(res_cad["blocks"])[:4]]
    assert any("nanocad" in t or "компас" in t for t in titles_cad), titles_cad
    assert not any("autocad" in t for t in titles_cad), titles_cad

    res_ex = n1_r2_engine.search(Request(q="импортозамещение exchange", mode="fast"))
    assert res_ex["query"]["raw"] == "импортозамещение exchange"
    titles_ex = [c["title"].lower() for c in cards_from(res_ex["blocks"])[:4]]
    assert any("communigate" in t or "tegu" in t for t in titles_ex), titles_ex


def test_renewal_for_present_line_without_renewal_tag_is_not_out_of_catalog(n1_r2_engine):
    res = n1_r2_engine.search(Request(q="продление криптопро", mode="fast"))
    assert res["understood"]["intent"] == "renewal"
    assert res["understood"]["zero_reason"] is None
    assert not any(b["type"] == "not_in_catalog" for b in res["blocks"])
    cards = cards_from(res["blocks"])
    assert cards and "криптопро" in cards[0]["title"].lower()


@pytest.mark.parametrize("q", ["пицца", "погода в москве", "рецепт борща", "купить квартиру"])
def test_unmatched_offtopic_does_not_fall_back_to_legacy_engine(n1_r2_engine, q):
    req = Request(q=q, mode="fast")
    direct = feed_plan.search(n1_r2_engine, req, n1_r2_engine.clients["guest"], Trace(n1_r2_engine.timer), (), False)
    assert direct is not None, q
    assert cards_from(direct["blocks"]) == [], q
    assert direct["understood"]["zero_reason"] == "unknown_term", q
