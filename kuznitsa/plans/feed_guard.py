"""Проверка правды о наличии, защита от разрушительных исправлений и чистые ответы на мусор."""
import re
from uuid import uuid4

from kuznitsa.index.feed import STOP, words
from kuznitsa.index.feed_language import sold_as
from kuznitsa.llm.recovery import cost_summary
from kuznitsa.plans.presentation import profile_info
from kuznitsa.plans.response_guard import COLLECTION
from kuznitsa.text import normalize, tokens
from kuznitsa.understand.intent import TITLES
from kuznitsa.understand.spell_index import cyrillic, roman
from . import feed_analogs
from .feed_noise import (
    GARBAGE_NOTE,
    extract_conditions_and_noise,
    is_garbage_syntax,
    normalize_spoken_brands,
    resolve_vendor,
)

# Поздние хвостовые модификаторы редакции/плана, которые можно аккуратно отбросить при поиске линейки.
RELAX_QUALIFIERS = frozenset({
    "dc", "cc", "e1", "e3", "e5", "f1", "f3", "lt", "pro", "professional",
    "standard", "enterprise", "ultimate", "business", "home", "basic", "starter",
    "team", "teams", "suite", "graphics", "cloud", "desktop", "online",
    "plus", "premium", "essential", "essentials", "edition", "corporate",
    "про", "стандарт", "профессиональный", "бизнес", "дом",
})

# Поколения/старые версии (не 2020-е годы), отсутствие которых в линейке нужно называть честно.
MISSING_GENERATION_RE = re.compile(
    r"^(.+?)\s+(xp|vista|me|nt|95|98|2000|2003|2007|2008|2010|2012|2013|2015|\d{1,2})$"
)
RECENT_YEAR_RE = re.compile(r"\b(202\d)\b")

# Устаревшие/настольные версии, приоритетные при показе актуальной линейки (например, Windows 11/10 вместо 7).
DESKTOP_VERSION_RE = re.compile(r"\b(1[01])\b")

# Клавиатурные последовательности и мусорные латинские наборы.
KEYBOARD_MASH = ("qwerty", "asdf", "zxcv", "qazw", "wsx", "edc", "rfv", "tgb", "yhn", "ujm")

OFFICE_STANDALONE_APPS = frozenset({
    "word", "excel", "powerpoint", "outlook", "access", "publisher",
    "visio", "project", "onenote", "teams", "sharepoint", "exchange",
})
OFFICE_SUITE_MARKERS = frozenset({
    "standard", "профессиональный", "professional", "home", "дом",
    "business", "бизнес", "ltsc", "для", "студент", "учеб",
})


def popular_section_options(index, limit: int = 3) -> list[dict]:
    """Детерминированные популярные разделы каталога для clarify на мусорных запросах."""
    sections = sorted(
        index.groups,
        key=lambda k: (
            index.cat.cards[index.groups[k][0]].offers[0].domain == "software",
            len(index.groups[k]),
            index.classes[k],
        ),
        reverse=True,
    )
    return [
        dict(label=index.classes[k], apply=dict(q=index.classes[k], category=k))
        for k in sections[:limit]
    ]


def popular_queries(engine, limit: int = 6) -> list[str]:
    """Короткий список популярных направлений каталога для подсказок."""
    index = engine.catalog.feed
    sections = sorted(
        index.groups,
        key=lambda k: (
            index.cat.cards[index.groups[k][0]].offers[0].domain == "software",
            len(index.groups[k]),
            index.classes[k],
        ),
        reverse=True,
    )
    return [index.classes[k] for k in sections[:limit]]


def build_garbage_result(
    engine,
    req,
    profile,
    trace,
    norm: str,
    *,
    zero_reason: str = "unknown_term",
    intent: str = "broad",
    note: str | None = None,
    missing_block: dict | None = None,
) -> dict:
    """Чистый ответ без карточек-заглушек на мусор, оффтоп или нераспознанный запрос."""
    index = engine.catalog.feed
    text = note or GARBAGE_NOTE
    if missing_block is not None:
        blocks = [missing_block]
    else:
        blocks = [
            dict(
                type="clarify",
                title="Уточните раздел",
                question=text,
                options=popular_section_options(index, 3),
            )
        ]
    trace.add("guard", "Проверка запроса", text)
    return dict(
        search_id="s_" + uuid4().hex,
        engine="kuznitsa",
        engine_version="1.0",
        mode=req.mode,
        query=dict(
            raw=req.q,
            normalized=norm,
            corrected=norm,
            corrections=[],
            did_you_mean=None,
        ),
        understood=dict(
            intent=intent,
            intent_title=TITLES[intent],
            intent_conf=0.9,
            intent_source="rules",
            filters={},
            exclude={},
            qty=None,
            entities=[],
            chips=[],
            zero_reason=zero_reason,
            agent_note=text,
        ),
        blocks=blocks,
        facets=[],
        notes=[],
        banners=[],
        relax_hints=[],
        related_queries=popular_queries(engine, 6),
        profile=profile_info(profile),
        cost=cost_summary([], engine.usd_rub),
        trace=trace.steps,
        timing_ms={},
    )


def is_plausible_absent_brand(raw_q: str, norm_q: str) -> bool:
    """Отличает правдоподобное латинское название продукта (steam) от клавиатурного мусора (asdfghjkl, qxwzzzt)."""
    s = (norm_q or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9.+-]{2,20}", s):
        return False
    if not re.search(r"[aeiouy]", s):
        return False
    if re.search(r"[^aeiouy\d.+-]{4,}", s):
        return False
    if re.search(r"(.)\1\1", s):
        return False
    if any(m in s for m in KEYBOARD_MASH):
        return False
    return True


def is_destructive_repair(index, orig: str, fixed: str, ids, kind: str | None = None) -> bool:
    """Запрещает разрушительные исправления (steam -> team, пицца -> pisa)."""
    if not fixed or not orig or orig == fixed or kind == "layout":
        return False
    orig_w = words(orig)
    fixed_w = words(fixed)
    if not orig_w or not fixed_w:
        return False

    # 1. Короткое односложное исправление в одном алфавите со сменой первой буквы (steam -> team).
    if len(orig_w) == 1 and len(fixed_w) == 1:
        ow, fw = orig_w[0], fixed_w[0]
        same_script = (
            (bool(re.fullmatch(r"[a-z0-9]+", ow)) and bool(re.fullmatch(r"[a-z0-9]+", fw)))
            or (bool(re.fullmatch(r"[а-яё0-9]+", ow)) and bool(re.fullmatch(r"[а-яё0-9]+", fw)))
        )
        if same_script and len(ow) <= 5 and len(fw) <= 5 and ow[0] != fw[0]:
            return True

    # 2. Односложное межскриптовое фонетическое исправление (пицца -> pisa): цель должна реально продаваться под этим именем.
    orig_cyr = bool(re.search(r"[а-яё]", orig))
    fixed_lat = bool(re.search(r"[a-z]", fixed))
    orig_lat = bool(re.search(r"[a-z]", orig))
    fixed_cyr = bool(re.search(r"[а-яё]", fixed))
    if len(orig_w) == 1 and len(fixed_w) == 1 and ((orig_cyr and fixed_lat) or (orig_lat and fixed_cyr)):
        if fixed in index.vendor_names or fixed in index.aliases:
            return False
        if ids and any(sold_as(index.cat.cards[cid], fixed) for cid in ids[:5]):
            return False
        return True

    return False


def rank_vendor_cards(index, cids) -> list[str]:
    """Сортирует карточки вендора: основные продукты и ПО выше вспомогательных, с учётом качества."""
    return sorted(
        dict.fromkeys(cids),
        key=lambda cid: (
            index.cat.cards[cid].offers[0].domain == "software",
            not re.search(r"\b(?:course|курс|обучен|тренинг)\b", index.cat.cards[cid].title, re.I),
            index.browse_quality.get(cid, (0,)),
            index.quality.get(cid, (0,)),
            cid,
        ),
        reverse=True,
    )


def build_vendor_result(engine, req, profile, trace, priorities, record, norm: str, vid: str, display_name: str) -> dict | None:
    """Собирает выдачу по запросу «всё от X / продукты X / что есть у X»."""
    from .feed import display, finish, order, recommend

    index = engine.catalog.feed
    raw_cids = list(index.language.vendor_cards.get(vid, ())) or list(index.tags["vendors"].get(vid, ()))
    if not raw_cids:
        return None
    ids = rank_vendor_cards(index, raw_cids)
    title = f"Продукты {display_name}"
    note = f"Предложения производителя {display_name} в каталоге."
    trace.add("retrieve", "Каталог производителя", title, candidates=len(ids))
    start = (req.page - 1) * req.page_size
    items = [display(engine, cid, profile) for cid in ids[start:start + req.page_size]]
    for i, c in enumerate(items, 1):
        c["position"] = i
    merch = order(engine, req, profile, trace, priorities, "category", None, items)
    if merch is None:
        return None
    items = merch["cards"]
    main = [c["card_id"] for c in items]
    together, _ = recommend(engine, norm, items, profile, "category")
    for i, c in enumerate(items, 1):
        c["position"] = i
    blocks = [dict(type="products", title=title, category_id=None, total=len(ids), items=items)]
    if together:
        blocks.append(together)
    result = dict(
        search_id="s_" + uuid4().hex,
        engine="kuznitsa",
        engine_version="1.0",
        mode=req.mode,
        query=dict(raw=req.q, normalized=norm, corrected=norm, corrections=[], did_you_mean=None),
        understood=dict(
            intent="category",
            intent_title=TITLES["category"],
            intent_conf=0.95,
            intent_source="rules",
            filters=dict(vendor=[vid]),
            exclude={},
            qty=None,
            entities=[],
            chips=[dict(key="vendor", label=display_name, removable=False)],
            zero_reason=None,
            agent_note=note,
        ),
        blocks=blocks,
        facets=[],
        notes=[],
        banners=merch["banners"],
        relax_hints=[],
        related_queries=[],
        profile=profile_info(profile),
        cost=cost_summary([], engine.usd_rub),
        trace=trace.steps,
        timing_ms={},
    )
    return finish(engine, req, trace, record, result, items, len(main), [])


def check_missing_generation(index, text: str) -> tuple[str, str, list[str]] | None:
    """Проверяет запрос старого поколения существующей линейки (например, windows 7 -> нет 7, есть 11/10)."""
    norm = " ".join(normalize(text).split())
    if not norm or index.edition(norm):
        return None
    m = MISSING_GENERATION_RE.match(norm)
    if not m:
        return None
    head, ver = m[1].strip(), m[2].strip()
    if not head or len(words(head)) > 3:
        return None
    # Если точное название с версией реально продаётся — это не пропуск.
    direct = index.products(norm, fuzzy=False)
    if any(sold_as(index.cat.cards[cid], norm) for cid in direct):
        return None
    # Ищем саму линейку (например, windows) среди реально продаваемых карточек.
    head_ids = [cid for cid in index.products(head, fuzzy=False) if sold_as(index.cat.cards[cid], head)]
    if not head_ids:
        return None
    # Проверяем, нет ли этой версии в заголовках карточек линейки (например, КОМПАС-3D v21).
    for cid in head_ids:
        t = normalize(index.cat.cards[cid].title)
        if ver in words(t) or f"v{ver}" in t:
            return None
    # Убеждаемся, что у линейки в каталоге действительно есть другие числовые версии/поколения.
    has_other_versions = any(
        re.search(r"\b(?:\d{1,2}|20\d\d)\b", normalize(index.cat.cards[cid].title))
        for cid in head_ids
    )
    if not has_other_versions:
        return None
    # Ставим актуальные основные версии (для Windows — 11 и 10, не Server) первыми.
    ordered = sorted(
        head_ids,
        key=lambda cid: (
            bool(DESKTOP_VERSION_RE.search(normalize(index.cat.cards[cid].title))),
            "server" not in normalize(index.cat.cards[cid].title),
            index.quality.get(cid, (0,)),
            cid,
        ),
        reverse=True,
    )
    return norm, head, ordered


def build_missing_generation_result(
    engine,
    req,
    profile,
    trace,
    priorities,
    record,
    norm: str,
    requested_label: str,
    head: str,
    ids: list[str],
) -> dict | None:
    """Собирает честный ответ: «X в каталоге нет. Ниже доступные версии линейки»."""
    from .feed import display, finish, order

    display_req = req.q.strip() or requested_label
    note = f"«{display_req}» в каталоге нет. Ниже доступные версии линейки."
    trace.add("retrieve", "Устаревшая версия линейки", note, candidates=len(ids))
    start = (req.page - 1) * req.page_size
    items = [display(engine, cid, profile) for cid in ids[start:start + req.page_size]]
    for i, c in enumerate(items, 1):
        c["position"] = i
    merch = order(engine, req, profile, trace, priorities, "out_of_catalog", None, items)
    if merch is None:
        return None
    items = merch["cards"]
    blocks = [
        dict(type="not_in_catalog", title="Нет в каталоге", reason="not_in_catalog", text=note),
        dict(
            type="analogs",
            title="Доступные версии линейки",
            items=[dict(card=c, reason="Доступная версия линейки") for c in items],
        ),
    ]
    result = dict(
        search_id="s_" + uuid4().hex,
        engine="kuznitsa",
        engine_version="1.0",
        mode=req.mode,
        query=dict(raw=req.q, normalized=norm, corrected=norm, corrections=[], did_you_mean=None),
        understood=dict(
            intent="out_of_catalog",
            intent_title=TITLES["out_of_catalog"],
            intent_conf=0.92,
            intent_source="rules",
            filters={},
            exclude={},
            qty=None,
            entities=[],
            chips=[],
            zero_reason="not_in_catalog",
            agent_note=note,
        ),
        blocks=blocks,
        facets=[],
        notes=[],
        banners=merch["banners"],
        relax_hints=[],
        related_queries=[],
        profile=profile_info(profile),
        cost=cost_summary([], engine.usd_rub),
        trace=trace.steps,
        timing_ms={},
        _allow_missing_generation=True,
    )
    return finish(engine, req, trace, record, result, items, len(items), [])


def _sold_or_all(index, cids, name: str) -> list[str]:
    if not cids:
        return []
    confirmed = [cid for cid in cids if sold_as(index.cat.cards[cid], name)]
    return confirmed or list(cids)


def resolve_feed_product(engine, text: str, *, segment=None, _depth: int = 0) -> tuple[list[str], str, str] | None:
    """Единая лестница подтверждения товара в реальном фиде (редакция, аналоги in_catalog, КБ-алиасы, год, тир)."""
    if _depth > 5:
        return None
    index = engine.catalog.feed
    s = normalize_spoken_brands(" ".join(normalize(text).split()))
    if not s:
        return None

    # 1. Прямая редакция в фиде.
    ed = index.edition(s)
    if ed:
        return list(ed.cards), ed.query, ed.note

    # 2. Прямой поиск в фиде (с проверкой продаваемости).
    direct = index.products(s, fuzzy=False, segment=segment)
    if direct:
        confirmed = [cid for cid in direct if sold_as(index.cat.cards[cid], s)]
        if confirmed:
            return confirmed, s, ""

    # 3. Алиасы «office 365» -> «microsoft 365».
    if re.search(r"\b(?:office|офис)\s*365\b", s):
        m365 = re.sub(r"\b(?:office|офис)\s*365\b", "microsoft 365", s)
        res = resolve_feed_product(engine, m365, segment=segment, _depth=_depth + 1)
        if res:
            return res

    # 4. Строки kb/feed_analogs.yaml с in_catalog=True (Корел Дро, MS SQL, Вижуал Студио, Вин рар, Автокад LT...).
    row = index.analogs.lookup(s, fuzzy=True)
    if row and row.get("in_catalog"):
        for candidate in row.get("names") or ():
            cand_norm = normalize(str(candidate))
            if not cand_norm:
                continue
            ed = index.edition(cand_norm)
            if ed:
                return list(ed.cards), ed.query, ed.note
            found = index.products(cand_norm, fuzzy=False, segment=segment)
            if found:
                return _sold_or_all(index, found, cand_norm), cand_norm, ""
        # Если в row указан вариант вроде AutoCAD LT, пробуем отбросить хвостовой квалификатор у основного имени.
        primary = normalize(str((row.get("names") or ("",))[0]))
        if primary and primary != s:
            res = resolve_feed_product(engine, primary, segment=segment, _depth=_depth + 1)
            if res:
                return res

    # 5. Полное совпадение с семейством/вендором в лексиконе КБ (например, «фш» -> Adobe Photoshop).
    toks = tokens(s)
    if toks:
        for start, end, matches in engine.lex.match(toks):
            if start != 0 or end != len(toks):
                continue
            for kind, key, _ in matches:
                if kind == "family":
                    row_f = engine.kb.rows["families"].get(key, {})
                    fname = normalize(str(row_f.get("name") or ""))
                    if fname:
                        found = index.products(fname, fuzzy=False, segment=segment)
                        if found:
                            return _sold_or_all(index, found, fname), fname, ""
                    members = index.tags["families"].get(key)
                    if members:
                        ordered = sorted(members, key=index.quality.get, reverse=True)
                        return ordered, fname or s, ""
                if kind == "vendor":
                    found_v = resolve_vendor(index, engine, s)
                    if found_v:
                        vid, _ = found_v
                        raw_cids = list(index.language.vendor_cards.get(vid, ()))
                        if raw_cids:
                            return rank_vendor_cards(index, raw_cids), s, ""

    # 6. Ослабление 4-значного свежего года (2020–2029), например «autocad 2025», «coreldraw graphics suite 2024».
    if RECENT_YEAR_RE.search(s):
        no_year = " ".join(RECENT_YEAR_RE.sub(" ", s).split())
        if no_year and no_year != s:
            res = resolve_feed_product(engine, no_year, segment=segment, _depth=_depth + 1)
            if res:
                cids, rq, _ = res
                return cids, rq, "Показаны доступные версии линейки в каталоге."

    # 7. Снятие хвостовых модификаторов редакции/плана (dc, e3, lt, suite, graphics...), если голова продаётся.
    parts = s.split()
    if len(parts) >= 2 and parts[-1] in RELAX_QUALIFIERS:
        head = " ".join(parts[:-1])
        if head and head not in RELAX_QUALIFIERS:
            res = resolve_feed_product(engine, head, segment=segment, _depth=_depth + 1)
            if res:
                cids, rq, _ = res
                return cids, rq, "Показаны доступные редакции линейки в каталоге."

    return None


def prefer_suite_for_office_year(index, q: str, ids: list[str]) -> list[str]:
    """Для запроса вида «microsoft office 2021» ставит пакеты Office Standard/Профессиональный выше отдельных программ."""
    if not ids:
        return ids
    q_words = set(words(q))
    if not ({"office", "офис"} & q_words):
        return ids
    if OFFICE_STANDALONE_APPS & q_words:
        return ids
    years = [w for w in q_words if re.fullmatch(r"20\d\d", w)]
    if not years:
        return ids

    def score(cid):
        t_words = set(words(index.cat.cards[cid].title))
        has_office = "office" in t_words or "офис" in t_words
        has_suite = bool(OFFICE_SUITE_MARKERS & t_words)
        has_year = any(y in t_words for y in years)
        is_standalone = bool(OFFICE_STANDALONE_APPS & t_words) and not has_office
        return (has_office and has_suite and has_year, has_office and has_year, not is_standalone)

    return sorted(ids, key=score, reverse=True)


def prefer_software_over_courses(index, q: str, ids: list[str]) -> list[str]:
    """Если покупатель не искал курсы/обучение, опускает учебные курсы ниже самих продуктов."""
    if not ids or re.search(r"\b(?:курс|обучен|тренинг|course|exam)\b", q, re.I):
        return ids
    return sorted(
        ids,
        key=lambda cid: not bool(re.search(r"\b(?:express\s+course|курс|обучен|тренинг)\b", index.cat.cards[cid].title, re.I)),
        reverse=True,
    )


def _strip_empty_blocks(blocks: list[dict]) -> None:
    for block in blocks[:]:
        field = COLLECTION.get(block.get("type"))
        if field is not None and not block.get(field):
            blocks.remove(block)


def _has_lexical_grounding(engine, norm: str, cards: list[dict]) -> bool:
    """Проверяет, есть ли хоть какая-то лексическая опора у ответа старого конвейера в тексте карточек или индексе."""
    index = engine.catalog.feed
    content = [w for w in words(norm) if len(w) >= 3 and w not in STOP]
    if not content:
        return False
    # Проверяем совпадение с классами, вендорами, сленгом, аналогами, SKU.
    if (
        index.class_match(norm)
        or norm in index.vendor_names
        or norm in index.slang
        or norm in index.aliases
        or norm in engine.catalog.source_codes
        or index.analogs.lookup(norm, fuzzy=False)
    ):
        return True
    for w in content:
        if w in index.vendor_names or w in index.slang or w in index.aliases:
            return True
    # Проверяем лексическое совпадение слов запроса с карточками топ-4 (леммы и 4-буквенный префикс).
    card_words: set[str] = set()
    for card in cards[:4]:
        card_words.update(words(card.get("title") or ""))
        vendor = card.get("vendor")
        if isinstance(vendor, dict):
            card_words.update(words(vendor.get("name") or ""))
        elif isinstance(vendor, str):
            card_words.update(words(vendor))
        cat = card.get("category")
        if isinstance(cat, dict):
            card_words.update(words(cat.get("title") or ""))
        elif isinstance(cat, str):
            card_words.update(words(cat))
    for w in content:
        if w in card_words:
            return True
        if len(w) >= 4 and any(cw.startswith(w[:4]) or w.startswith(cw[:4]) for cw in card_words if len(cw) >= 4):
            return True
        # Транслит для брендов.
        if re.search(r"[а-яё]", w):
            rw = roman(w)
            if len(rw) >= 4 and any(cw.startswith(rw[:4]) for cw in card_words if len(cw) >= 4):
                return True
        elif re.fullmatch(r"[a-z]+", w):
            cw_cyr = "".join(words(cyrillic(w)))
            if len(cw_cyr) >= 4 and any(cw.startswith(cw_cyr[:4]) for cw in card_words if len(cw) >= 4):
                return True
    return False


def _replace_with_feed_cards(engine, req, profile, result: dict, cids: list[str], resolved_q: str, note: str) -> None:
    """Подменяет ложное «нет в каталоге» реальными карточками из FeedIndex."""
    from .feed import display

    index = engine.catalog.feed
    cids = prefer_software_over_courses(index, resolved_q, prefer_suite_for_office_year(index, resolved_q, cids))
    start = (req.page - 1) * req.page_size
    items = [display(engine, cid, profile) for cid in cids[start:start + req.page_size]]
    for i, c in enumerate(items, 1):
        c["position"] = i
    title = TITLES["product"]
    result["blocks"] = [dict(type="products", title=title, category_id=None, total=len(cids), items=items)]
    result["understood"].update(
        intent="product",
        intent_title=TITLES["product"],
        zero_reason=None,
        reason=None,
        agent_note=note or title,
    )
    if resolved_q and resolved_q != result["query"]["normalized"]:
        result["query"]["corrected"] = resolved_q


def verify_response(engine, req, profile, result: dict, *, from_legacy: bool = False) -> dict:
    """Единая финальная проверка ответа на фиде: без пустых блоков, без ложного «нет» и без заглушек на мусоре."""
    index = getattr(engine.catalog, "feed", None)
    if not index:
        result.pop("_allow_missing_generation", None)
        return result

    allow_missing_gen = bool(result.pop("_allow_missing_generation", False))
    blocks = result["blocks"]
    understood = result["understood"]
    norm = result["query"]["normalized"]

    _strip_empty_blocks(blocks)

    # 1. Защита от ложного «нет в каталоге» (в том числе от старого vendor_left на реальном фиде).
    claims_absent = (
        any(b.get("type") == "not_in_catalog" for b in blocks)
        or understood.get("zero_reason") == "not_in_catalog"
        or understood.get("intent") == "out_of_catalog"
    )
    if (
        claims_absent
        and not allow_missing_gen
        and not req.verbatim
        and not feed_analogs.requested(norm)
        and not (req.filters.keys() - {"price_max"})
        and not any("Отдельной лицензии" in (b.get("text") or "") for b in blocks)
        and understood.get("filters", {}).get("action") != "renewal"
    ):
        cleaned = extract_conditions_and_noise(engine, index, norm)
        resolved = resolve_feed_product(engine, cleaned.subject, segment=profile.segment)
        if resolved:
            cids, rq, note = resolved
            _replace_with_feed_cards(engine, req, profile, result, cids, rq, note)
            _strip_empty_blocks(result["blocks"])
            return result

    # 2. Защита от карточек-заглушек и оффтопного dense-шума на мусорных запросах из старого конвейера.
    if from_legacy and req.page == 1:
        intent = understood.get("intent")
        zero_reason = understood.get("zero_reason")
        subtype = understood.get("subtype")

        # 2a. Явный оффтоп / unknown_term (кроме пиратства) — убираем fill-карточки, оставляем чистый clarify.
        if (zero_reason == "unknown_term" or intent == "off_topic") and subtype != "piracy":
            blocks[:] = [b for b in blocks if b.get("type") not in ("products", "crosssell", "analogs")]
            if not any(b.get("type") == "clarify" and b.get("options") for b in blocks):
                blocks.append(
                    dict(
                        type="clarify",
                        title="Уточните раздел",
                        question=GARBAGE_NOTE,
                        options=popular_section_options(index, 3),
                    )
                )
            understood.update(
                intent="broad",
                intent_title=TITLES["broad"],
                subtype=None,
                zero_reason="unknown_term",
                agent_note=GARBAGE_NOTE,
            )
            result["related_queries"] = popular_queries(engine, 6)
            return result

        # 2b. Незамеченный мусор (как «рецепт борща» -> блендеры через dense) без единой лексической опоры.
        kb_entities = [e for e in (understood.get("entities") or ()) if e.get("source") != "embed"]
        non_embed_filters = {
            k: v
            for k, v in (understood.get("filters") or {}).items()
            if not (k == "category" and not kb_entities)
        }
        if (
            not req.category
            and not req.filters
            and intent not in ("compare", "spec", "my_licenses", "kit", "analog", "out_of_catalog", "faq", "doc_answer", "status", "off_topic")
            and not kb_entities
            and not non_embed_filters
        ):
            visible = [
                c
                for b in blocks
                if b.get("type") == "products"
                for c in (b.get("items") or ())
                if c.get("kind") != "upsell" and not c.get("fill")
            ]
            if visible and not _has_lexical_grounding(engine, norm, visible):
                if is_garbage_syntax(req.q, norm, index, engine.catalog) or not _has_lexical_grounding(engine, norm, visible):
                    blocks[:] = [
                        dict(
                            type="clarify",
                            title="Уточните раздел",
                            question=GARBAGE_NOTE,
                            options=popular_section_options(index, 3),
                        )
                    ]
                    understood.update(
                        intent="broad",
                        intent_title=TITLES["broad"],
                        subtype=None,
                        zero_reason="unknown_term",
                        agent_note=GARBAGE_NOTE,
                    )
                    result["query"]["corrections"] = []
                    result["query"]["corrected"] = norm
                    result["related_queries"] = popular_queries(engine, 6)
                    return result

    _strip_empty_blocks(blocks)
    return result
