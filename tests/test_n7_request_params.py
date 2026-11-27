"""Тесты трека N7: сортировка, фильтры, исключения, фасеты и страницы на фиде."""
from dataclasses import replace
import json

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from kuznitsa.app import create_app
from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def n7_engine(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n7_feed")
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
                attrs={"domain": domain},
                description=description,
                lic={"model": "subscription", "term_months": 12, "metric": "device"},
                available=True,
                in_stock=True,
            )
        )

    # Ноутбуки (разные вендоры, цены, карточка без цены, 15 вендоров для проверки лимита 12)
    nb_specs = [
        ("nb1", "Ноутбук Lenovo IdeaPad 3", "Lenovo", 49500),
        ("nb2", "Ноутбук Lenovo ThinkPad E15", "Lenovo", 89000),
        ("nb3", "Ноутбук ASUS VivoBook 15", "ASUS", 54000),
        ("nb4", "Ноутбук ASUS ZenBook 14", "ASUS", 112000),
        ("nb5", "Ноутбук Acer Extensa 15", "Acer", 39900),
        ("nb6", "Ноутбук HP ProBook 450", "HP", 74000),
        ("nb7", "Ноутбук Dell Latitude 5540", "Dell", 96000),
        ("nb8", "Ноутбук Apple MacBook Air", "Apple", 125000),
        ("nb9", "Ноутбук MSI Modern 15", "MSI", 62000),
        ("nb10", "Ноутбук Huawei MateBook D15", "Huawei", 58000),
        ("nb11", "Ноутбук Honor MagicBook 15", "Honor", 56000),
        ("nb12", "Ноутбук Maibenben M555", "Maibenben", 43000),
        ("nb13", "Ноутбук Aquarius Cmp NS685", "Aquarius", 82000),
        ("nb14", "Ноутбук Fplus Flaptop", "Fplus", 67000),
        ("nb15", "Ноутбук Гравитон Н15И", "Гравитон", None),
    ]
    for oid, title, vendor, price in nb_specs:
        add(oid, title, "70188", "Ноутбуки", root="Компьютеры", domain="hardware", vendor=vendor, price=price)

    # Посторонняя электроника для проверки, что не просачивается при фильтрах и даёт допродажу
    add("ups1", "Блок питания Ippon E90", "70999", "Блоки питания", root="Компьютеры", domain="hardware", vendor="Ippon", price=4500)
    add("os_win", "Microsoft Windows 11 Pro", "os_win", "Операционные системы Windows", root="Операционные системы", vendor="Microsoft", price=20183)

    # Антивирусы в двух разделах (для проверки vendor.id из KB, category-фасета, vendor-исключений и коллизий в названии)
    add("av_k1", "Kaspersky Standard", "av_home", "Антивирусы для дома", root="Безопасность", vendor="Лаборатория Касперского", price=1500, registry=True)
    add("av_k2", "Kaspersky Plus", "av_home", "Антивирусы для дома", root="Безопасность", vendor="Лаборатория Касперского", price=2900, registry=True)
    add("av_k3", "Kaspersky Endpoint Security", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Лаборатория Касперского", price=4500, registry=True)
    add("av_d1", "Dr.Web Security Space", "av_home", "Антивирусы для дома", root="Безопасность", vendor="Доктор Веб", price=1800, registry=True)
    add("av_d2", "Dr.Web Enterprise Security Suite", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="Доктор Веб", price=6200, registry=True)
    add("av_p1", "PRO32 Ultimate Security", "av_home", "Антивирусы для дома", root="Безопасность", vendor="PRO32", price=990, registry=True)
    # Карточка другого вендора с упоминанием "Kaspersky" в названии — exclude по vendor её НЕ должен убирать
    add("av_p2", "PRO32 Migration from Kaspersky", "av_biz", "Антивирусы для организаций", root="Безопасность", vendor="PRO32", price=3300, registry=True)

    # Резервное копирование (задача из feed_tasks.yaml)
    add("bk1", "Кибер Бэкап Стандартный", "sec_bk", "Резервное копирование", root="Безопасность", vendor="Киберпротект", price=12000, registry=True)
    add("bk2", "Кибер Бэкап Расширенный", "sec_bk", "Резервное копирование", root="Безопасность", vendor="Киберпротект", price=28000, registry=True)
    add("bk3", "RuBackup Enterprise", "sec_bk", "Резервное копирование", root="Безопасность", vendor="Группа Астра", price=45000, registry=True)
    add("bk4", "Handy Backup Standard", "sec_bk", "Резервное копирование", root="Безопасность", vendor="Новософт", price=5500, registry=True)

    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    engine = Engine.open(replace(cfg, data=data), llm=Disabled())
    yield engine
    engine.close()


def _main_cards(res):
    out = []
    for block in res.get("blocks") or []:
        if block.get("type") in ("products", "analogs", "compare"):
            out.extend(block.get("items") or [])
    return out


def _total(res):
    blocks = [b for b in (res.get("blocks") or []) if b.get("type") in ("products", "analogs", "compare")]
    return sum(int(b.get("total") or 0) for b in blocks)


def _upsell_cards(res):
    out = []
    for block in res.get("blocks") or []:
        if block.get("type") == "upsell":
            out.extend(block.get("items") or [])
    return out


def test_sort_schema_rejects_unknown_and_http_422(n7_engine):
    with pytest.raises(ValidationError):
        Request(q="ноутбук", sort="random")
    with pytest.raises(ValidationError):
        Request(q="ноутбук", sort="relevance")
    req_asc = Request(q="ноутбук", sort="price_asc")
    req_desc = Request(q="ноутбук", sort="price_desc")
    assert req_asc.sort == "price_asc"
    assert req_desc.sort == "price_desc"

    with TestClient(create_app(n7_engine)) as client:
        resp = client.post("/api/search", json={"q": "ноутбук", "sort": "bogus"})
        assert resp.status_code == 422


def test_sort_across_full_list_none_last_and_no_upsells(n7_engine):
    r1 = n7_engine.search(Request(q="ноутбук", sort="price_asc", page=1, page_size=5, mode="fast"))
    r2 = n7_engine.search(Request(q="ноутбук", sort="price_asc", page=2, page_size=5, mode="fast"))
    r3 = n7_engine.search(Request(q="ноутбук", sort="price_asc", page=3, page_size=5, mode="fast"))

    all_cards = _main_cards(r1) + _main_cards(r2) + _main_cards(r3)
    assert _total(r1) == 15
    assert len(all_cards) == 15
    assert len({c["card_id"] for c in all_cards}) == 15

    prices = [c["price_from"] for c in all_cards]
    priced = [p for p in prices if p is not None]
    assert priced == sorted(priced)
    assert prices[-1] is None  # карточка без цены в конце
    assert _upsell_cards(r1) == []  # при явной сортировке допродажи не вставляются

    rd = n7_engine.search(Request(q="ноутбук", sort="price_desc", page=1, page_size=15, mode="fast"))
    d_prices = [c["price_from"] for c in _main_cards(rd)]
    d_priced = [p for p in d_prices if p is not None]
    assert d_priced == sorted(d_priced, reverse=True)
    assert d_prices[-1] is None


def test_filters_vendor_id_and_name_or_and_price_and_empty(n7_engine):
    # По названию в разном регистре + OR по нескольким производителям
    r = n7_engine.search(Request(q="ноутбук", filters={"vendor": ["lenovo", "ACER"]}, mode="fast"))
    cards = _main_cards(r)
    assert _total(r) == 3
    assert {c["vendor"]["name"] for c in cards} == {"Lenovo", "Acer"}
    assert "Ippon" not in {c["vendor"]["name"] for c in cards}

    # По коду производителя (vendor.id из карточки) + price_max (AND между ключами)
    r_av = n7_engine.search(Request(q="антивирус", mode="fast"))
    kasp_card = next(c for c in _main_cards(r_av) if c["vendor"]["name"] == "Лаборатория Касперского")
    kasp_vid = kasp_card["vendor"]["id"] or kasp_card["vendor"]["name"]
    r_kasp = n7_engine.search(Request(q="антивирус", filters={"vendor": [kasp_vid]}, mode="fast"))
    assert _total(r_kasp) >= 1
    assert all(c["vendor"]["name"] == "Лаборатория Касперского" for c in _main_cards(r_kasp))

    # AND между vendor и price_max
    r_and = n7_engine.search(Request(q="ноутбук", filters={"vendor": ["Lenovo"], "price_max": 60000}, mode="fast"))
    cards_and = _main_cards(r_and)
    assert _total(r_and) == 1
    assert cards_and[0]["title"] == "Ноутбук Lenovo IdeaPad 3"
    assert cards_and[0]["price_from"] <= 60000

    # Сложение текста и параметров ("ноутбук до 70000" + vendor ASUS)
    r_comb = n7_engine.search(Request(q="ноутбук до 70000", filters={"vendor": ["ASUS"]}, mode="fast"))
    cards_comb = _main_cards(r_comb)
    assert _total(r_comb) == 1
    assert cards_comb[0]["title"] == "Ноутбук ASUS VivoBook 15"

    # Несуществующий производитель -> пустой список, без посторонних товаров, честное пояснение и relax_hints
    r_empty = n7_engine.search(Request(q="ноутбук", filters={"vendor": ["nonexistent_vendor_xyz"]}, mode="fast"))
    assert _main_cards(r_empty) == []
    assert _total(r_empty) == 0
    assert r_empty["understood"]["zero_reason"] == "filters_too_strict"
    assert r_empty["relax_hints"]
    assert r_empty["facets"] == []


def test_filters_category_and_exclude_vendor_and_category(n7_engine):
    # Запрос по бренду Kaspersky охватывает оба раздела (av_home и av_biz)
    r_all_k = n7_engine.search(Request(q="продукты Лаборатория Касперского", mode="fast"))
    assert _total(r_all_k) == 3

    # Фильтр по category_id
    r_cat = n7_engine.search(
        Request(q="продукты Лаборатория Касперского", filters={"category": ["av_home"]}, mode="fast")
    )
    cards_cat = _main_cards(r_cat)
    assert _total(r_cat) == 2
    assert {c["title"] for c in cards_cat} == {"Kaspersky Standard", "Kaspersky Plus"}

    # Исключение раздела параметром
    r_ex_cat = n7_engine.search(
        Request(q="продукты Лаборатория Касперского", exclude={"category": ["av_home"]}, mode="fast")
    )
    assert _total(r_ex_cat) == 1
    assert _main_cards(r_ex_cat)[0]["title"] == "Kaspersky Endpoint Security"

    # Исключение производителя параметром: убирает вендора, но НЕ трогает чужую карточку с этим словом в названии
    r_ex = n7_engine.search(Request(q="антивирус", exclude={"vendor": ["Лаборатория Касперского"]}, mode="fast"))
    cards_ex = _main_cards(r_ex)
    vendors_ex = {c["vendor"]["name"] for c in cards_ex}
    assert "Лаборатория Касперского" not in vendors_ex
    assert any(c["title"] == "PRO32 Migration from Kaspersky" for c in cards_ex)
    assert _total(r_ex) == 2


def test_facets_counts_caps_and_multi_select_independence(n7_engine):
    # Ноутбуки: 15 вендоров -> в фасете vendor не больше 12; один раздел -> category-фасета нет; есть price_max
    r_nb = n7_engine.search(Request(q="ноутбук", mode="fast"))
    fmap = {f["key"]: f for f in r_nb["facets"]}
    assert "vendor" in fmap
    assert len(fmap["vendor"]["values"]) == 12
    assert "category" not in fmap
    assert "price_max" in fmap
    assert 1 <= len(fmap["price_max"]["values"]) <= 5

    # count фасета price_max совпадает с total при выборе этого порога
    v_price = fmap["price_max"]["values"][0]
    assert isinstance(v_price["id"], int)
    assert v_price["label"].startswith("до ")
    r_picked_p = n7_engine.search(Request(q="ноутбук", filters={"price_max": v_price["id"]}, mode="fast"))
    assert _total(r_picked_p) == v_price["count"]

    # Выбор одного вендора сохраняет остальных вендоров в vendor-фасете
    v_lenovo = next(v for v in fmap["vendor"]["values"] if v["label"] == "Lenovo")
    r_lenovo = n7_engine.search(Request(q="ноутбук", filters={"vendor": [v_lenovo["id"]]}, mode="fast"))
    assert _total(r_lenovo) == v_lenovo["count"]
    fmap_l = {f["key"]: f for f in r_lenovo["facets"]}
    vendor_labels = {v["label"] for v in fmap_l["vendor"]["values"]}
    assert {"Lenovo", "ASUS", "Acer"}.issubset(vendor_labels)

    # Два раздела в списке -> есть category-фасет, и count совпадает с total после выбора
    r_vk = n7_engine.search(Request(q="продукты Лаборатория Касперского", mode="fast"))
    fmap_vk = {f["key"]: f for f in r_vk["facets"]}
    assert "category" in fmap_vk
    for v_cat in fmap_vk["category"]["values"]:
        r_c = n7_engine.search(
            Request(q="продукты Лаборатория Касперского", filters={"category": [v_cat["id"]]}, mode="fast")
        )
        assert _total(r_c) == v_cat["count"]


def test_understood_chips_and_ignore_removes_filter(n7_engine):
    base_total = _total(n7_engine.search(Request(q="антивирус", mode="fast")))
    r = n7_engine.search(
        Request(
            q="антивирус",
            filters={"vendor": ["Доктор Веб"], "price_max": 10000},
            exclude={"vendor": ["PRO32"]},
            mode="fast",
        )
    )
    u = r["understood"]
    assert "vendor" in u["filters"]
    assert u["filters"]["price_max"] == 10000
    assert "vendor" in u["exclude"]
    chip_keys = {c["key"]: c for c in u["chips"]}
    assert chip_keys["vendor"]["removable"] is True
    assert chip_keys["price_max"]["removable"] is True
    assert chip_keys["exclude"]["removable"] is True

    # ignore=["vendor"] снимает фильтр по вендору
    r_ign = n7_engine.search(
        Request(q="антивирус", filters={"vendor": ["Доктор Веб"]}, ignore=["vendor"], mode="fast")
    )
    assert _total(r_ign) == base_total
    assert "vendor" not in r_ign["understood"]["filters"]


def test_pagination_pages_distinct_and_upsells_only_page_one(n7_engine):
    p1 = n7_engine.search(Request(q="ноутбук", page=1, page_size=4, mode="fast"))
    p2 = n7_engine.search(Request(q="ноутбук", page=2, page_size=4, mode="fast"))
    p9 = n7_engine.search(Request(q="ноутбук", page=9, page_size=4, mode="fast"))

    ids1 = [c["card_id"] for c in _main_cards(p1)]
    ids2 = [c["card_id"] for c in _main_cards(p2)]
    assert len(ids1) == 4
    assert len(ids2) == 4
    assert set(ids1).isdisjoint(ids2)
    assert _total(p1) == _total(p2) == 15
    assert _upsell_cards(p2) == []
    assert _main_cards(p9) == []


def test_vendor_catalog_and_solution_support_params_and_facets(n7_engine):
    # Список товаров производителя ("продукты Лаборатория Касперского")
    rv = n7_engine.search(
        Request(q="продукты Лаборатория Касперского", sort="price_asc", filters={"category": ["av_home"]}, mode="fast")
    )
    cards_v = _main_cards(rv)
    assert _total(rv) == 2
    assert [c["price_from"] for c in cards_v] == [1500.0, 2900.0]
    assert any(f["key"] == "category" for f in rv["facets"])

    # Задача ("резервное копирование") с сортировкой, фильтром и исключением
    rs = n7_engine.search(
        Request(
            q="резервное копирование",
            sort="price_desc",
            exclude={"vendor": ["Группа Астра"]},
            mode="fast",
        )
    )
    cards_s = _main_cards(rs)
    assert _total(rs) == 3
    assert [c["price_from"] for c in cards_s] == [28000.0, 12000.0, 5500.0]
    assert "Группа Астра" not in {c["vendor"]["name"] for c in cards_s}
    assert any(f["key"] == "vendor" for f in rs["facets"])


def test_compare_has_no_facets(n7_engine):
    rc = n7_engine.search(Request(q="сравни Kaspersky и Dr.Web", mode="fast"))
    assert rc["facets"] == []
