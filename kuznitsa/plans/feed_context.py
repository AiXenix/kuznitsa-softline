"""Наследование предмета диалога между запросами одной сессии на фиде."""
from __future__ import annotations

import re
from uuid import uuid4

from kuznitsa.index.feed import HARDWARE, words
from kuznitsa.index.feed_editions import LEVEL as EDITION_LEVELS
from kuznitsa.index.feed_language import sold_as
from kuznitsa.index.hardware import (
    hardware_head,
    rank_hardware_section,
    resolve_hardware_section,
)
from kuznitsa.llm.recovery import cost_summary
from kuznitsa.plans.presentation import profile_info
from kuznitsa.text import normalize
from kuznitsa.understand.intent import TITLES
from kuznitsa.understand.quantities import spoken_numbers

from . import feed_analogs, feed_conditions, feed_noise
from .feed_query import (
    HOME,
    matching_variants,
    split_conditions,
    vendor_class,
)

# Сентинел на кириллице (без [a-z]), чтобы feed_conditions.extract не считал
# остаток пустым и принимал платформу/сортировку/происхождение/исключения.
_PROBE_SENTINEL = "предметконтекста"

# Разговорные вводные в начале уточнения («а ...», «а есть ...», «а что-нибудь ...»).
# Важно: не снимать «только» перед «не» («только не microsoft» — исключение).
_LEAD_DISCOURSE = re.compile(
    r"^(?:"
    r"а(?:\s+есть(?:\s+ли)?)?"
    r"|и|но|ну|ещ[её]|тогда|лучше|может(?:\s+быть)?"
    r"|давай(?:те)?|покажи(?:те)?|подскажи(?:те)?|найди(?:те)?|подбери(?:те)?"
    r"|нуж(?:ен|на|но|ны)|хочу|можно"
    r"|есть(?:\s+ли)?"
    r"|что[- ]?нибудь|какой[- ]?нибудь|какое[- ]?нибудь|какие[- ]?нибудь|какую[- ]?нибудь"
    r"|вариант(?:ы)?|модел[иь]"
    r"|только(?!\s+не\b)"
    r")(?:\s+|,\s*)",
    re.I,
)
_TRAIL_DISCOURSE = re.compile(
    r"(?:\s+(?:есть|будет|в\s+наличии|пожалуйста|плиз|подскажите))?[?!.,;:]*$",
    re.I,
)
_VENDOR_PREFIX = re.compile(
    r"^(?:от|производител\w*|вендор\w*|бренд\w*|фирм\w*|марк\w*)\s+",
    re.I,
)

# Общие слова-заглушки, которые сами по себе не задают новый предмет.
_GENERIC_PLACEHOLDERS = frozenset({
    "по", "программа", "программы", "программ", "программу", "софт",
    "решение", "решения", "вариант", "варианты", "товар", "товары",
    "модель", "модели", "продукт", "продукты", "лицензия", "лицензии",
    "устройство", "устройства", "техника", "оборудование",
    "аналог", "аналоги", "замена", "замены", "альтернатива", "альтернативы",
    "что", "нибудь", "такое", "подобное", "другой", "другие", "другое",
})

_ANALOG_ONLY_RE = re.compile(
    r"^(?:аналог\w*|замен\w*|альтернатив\w*|чем\s+(?:можно\s+)?заменить|что\s+вместо|вместо(?:\s+него|\s+не[её]|\s+этого)?|другой\s+(?:производитель|вендор))$",
    re.I,
)

# Уточнения аудитории («для дома», «домашняя», «для бизнеса», «для организаций», ...).
_AUDIENCE_ONLY_RE = re.compile(
    r"^(?:"
    r"(?:для\s+)?(?:дома|семьи|домашн\w*|личн\w*(?:\s+использовани\w*)?|физ\.?\s*лиц\w*)"
    r"|(?:для\s+)?(?:бизнес\w*|организац\w*|компани\w*|офис\w*|корпоратив\w*|юр\.?\s*лиц\w*|команд\w*|предприят\w*)"
    r"|(?:для\s+)?(?:школ\w*|вуз\w*|университет\w*|учебн\w*|образован\w*|студент\w*)"
    r"|(?:для\s+)?(?:гос\w*)"
    r")$",
    re.I,
)

# Характеристики с единицами измерения (диагональ, память, частота, мощность).
_INCH_RE = re.compile(
    r"^(?:диагональ\s+|экран\s+|на\s+)?(\d+(?:[.,]\d+)?)\s*(?:дюйм\w*|inch(?:es)?|\"|''|″)$",
    re.I,
)
_STORAGE_RE = re.compile(
    r"^(?:на\s+|с\s+|от\s+|озу\s+|ram\s+|ssd\s+|hdd\s+)?(\d+(?:[.,]\d+)?)\s*(гб|gb|тб|tb|мб|mb)$",
    re.I,
)
_FREQ_RE = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*(гц|hz|ггц|ghz|мгц|mhz)$",
    re.I,
)
_POWER_RE = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*(вт|w|ва|va)$",
    re.I,
)

# Двуязычные соответствия частых свойств оборудования.
_PROP_SYNONYMS: dict[str, tuple[str, ...]] = {
    "беспроводной": ("беспроводн", "wireless", "bluetooth", "bt"),
    "проводной": ("проводн", "wired", "usb"),
    "черный": ("черн", "чёрн", "black"),
    "белый": ("бел", "white"),
    "серый": ("сер", "gray", "grey", "silver"),
    "лазерный": ("лазерн", "laser"),
    "струйный": ("струйн", "inkjet"),
    "цветной": ("цветн", "color", "colour"),
    "монохромный": ("монохром", "mono", "ч/б"),
    "сенсорный": ("сенсорн", "touch"),
    "изогнутый": ("изогнут", "curved"),
    "игровой": ("игров", "gaming", "gamer"),
    "матовый": ("матов", "matte"),
    "глянцевый": ("глянцев", "glossy"),
}

_QTY_UNIT_WORD = {
    "device": "пк",
    "user": "пользователей",
    "server": "серверов",
    "cpu": "процессоров",
    "core": "ядер",
    None: "мест",
}

_ASTRA_PLAT_RE = re.compile(r"^(?:для|под|на)\s+(?:астр\w*|astra(?:\s+linux)?)$", re.I)


def _clean_spaces(text: str) -> str:
    return " ".join(text.strip(" ,;:-\"«»").split())


def _strip_discourse(text: str) -> str:
    """Снять разговорную обёртку в начале и конце уточнения."""
    s = _clean_spaces(text)
    if not s:
        return ""
    if re.match(r"^(?:что\s+есть\s+(?:у|от)\b|что\s+(?:выбрать|поставить|взять|использовать)\b)", s, re.I):
        return s
    prev = None
    while s and s != prev:
        prev = s
        m = _LEAD_DISCOURSE.match(s)
        if m:
            rest = _clean_spaces(s[m.end():])
            if rest:
                s = rest
    s = _clean_spaces(_TRAIL_DISCOURSE.sub("", s))
    return s


def _cond_to_dict(cond: feed_conditions.Conditions) -> dict:
    return {
        "price_min": cond.price_min,
        "price_max": cond.price_max,
        "sort": cond.sort,
        "exclude_vendors": list(cond.exclude_vendors),
        "exclude_terms": list(cond.exclude_terms),
        "exclude_labels": list(cond.exclude_labels),
        "origin": cond.origin,
        "registry": bool(cond.registry),
        "platform": cond.platform,
        "service": cond.service,
    }


def _merge_cond_dicts(prev_c: dict | None, new_c: dict) -> dict:
    """Объединить накопленные условия с новыми (новые значения того же типа заменяют старые)."""
    base = dict(prev_c or {})
    out = {
        "price_min": base.get("price_min"),
        "price_max": base.get("price_max"),
        "sort": base.get("sort"),
        "exclude_vendors": list(base.get("exclude_vendors") or []),
        "exclude_terms": list(base.get("exclude_terms") or []),
        "exclude_labels": list(base.get("exclude_labels") or []),
        "origin": base.get("origin"),
        "registry": bool(base.get("registry")),
        "platform": base.get("platform"),
        "service": base.get("service"),
    }
    if new_c.get("price_max") is not None:
        out["price_max"] = new_c["price_max"]
        if out["price_min"] is not None and out["price_min"] > out["price_max"]:
            out["price_min"] = None
    if new_c.get("price_min") is not None:
        out["price_min"] = new_c["price_min"]
        if out["price_max"] is not None and out["price_max"] < out["price_min"]:
            out["price_max"] = None
    if new_c.get("sort"):
        out["sort"] = new_c["sort"]
    if new_c.get("exclude_vendors"):
        out["exclude_vendors"] = list(dict.fromkeys([*out["exclude_vendors"], *new_c["exclude_vendors"]]))
    if new_c.get("exclude_terms"):
        out["exclude_terms"] = list(dict.fromkeys([*out["exclude_terms"], *new_c["exclude_terms"]]))
    if new_c.get("exclude_labels"):
        out["exclude_labels"] = list(dict.fromkeys([*out["exclude_labels"], *new_c["exclude_labels"]]))
    if new_c.get("origin"):
        out["origin"] = new_c["origin"]
    if new_c.get("registry"):
        out["registry"] = True
        out["origin"] = out["origin"] or "russian"
    if new_c.get("platform"):
        out["platform"] = new_c["platform"]
    if new_c.get("service"):
        out["service"] = new_c["service"]
    return out


def _cond_from_dict(subject: str, d: dict) -> feed_conditions.Conditions:
    active = bool(
        d.get("price_min") is not None
        or d.get("price_max") is not None
        or d.get("sort")
        or d.get("exclude_vendors")
        or d.get("exclude_terms")
        or d.get("origin")
        or d.get("registry")
        or d.get("platform")
        or d.get("service")
    )
    return feed_conditions.Conditions(
        subject=subject,
        raw_for_analogs=subject,
        price_min=d.get("price_min"),
        price_max=d.get("price_max"),
        sort=d.get("sort"),
        exclude_vendors=tuple(d.get("exclude_vendors") or ()),
        exclude_terms=tuple(d.get("exclude_terms") or ()),
        exclude_labels=tuple(d.get("exclude_labels") or ()),
        origin=d.get("origin"),
        registry=bool(d.get("registry")),
        platform=d.get("platform"),
        service=d.get("service"),
        upgrade=False,
        active=active,
    )


def _probe_conditions(engine, tail: str, req):
    """Извлечь условия из уточнения через feed_conditions.extract и split_conditions."""
    probe_req = req.model_copy(update={"filters": {}, "exclude": {}, "sort": None, "ignore": []})
    probe_text = f"{_PROBE_SENTINEL} {tail}"
    cond = feed_conditions.extract(engine, probe_text, probe_req)

    rem = cond.subject
    if rem.startswith(_PROBE_SENTINEL):
        rem = _clean_spaces(rem[len(_PROBE_SENTINEL):])
    elif _PROBE_SENTINEL in rem:
        rem = _clean_spaces(rem.replace(_PROBE_SENTINEL, " "))

    plat = cond.platform
    if not plat and rem and _ASTRA_PLAT_RE.fullmatch(rem):
        plat = "linux"
        rem = ""

    parsed_rem = spoken_numbers(rem) if rem else ""
    rem_base, qty, renewal = split_conditions(parsed_rem) if parsed_rem else ("", None, False)

    if (qty or renewal) and rem_base and rem_base != rem:
        cond2 = feed_conditions.extract(engine, f"{_PROBE_SENTINEL} {rem_base}", probe_req)
        rem2 = cond2.subject
        if rem2.startswith(_PROBE_SENTINEL):
            rem2 = _clean_spaces(rem2[len(_PROBE_SENTINEL):])
        elif _PROBE_SENTINEL in rem2:
            rem2 = _clean_spaces(rem2.replace(_PROBE_SENTINEL, " "))
        c_dict = _merge_cond_dicts(_cond_to_dict(cond), _cond_to_dict(cond2))
        rem_base = rem2
    else:
        c_dict = _cond_to_dict(cond)

    if plat:
        c_dict["platform"] = plat

    has_any_cond = bool(
        qty
        or renewal
        or c_dict["price_min"] is not None
        or c_dict["price_max"] is not None
        or c_dict["sort"]
        or c_dict["exclude_vendors"]
        or c_dict["exclude_terms"]
        or c_dict["origin"]
        or c_dict["registry"]
        or c_dict["platform"]
        or c_dict["service"]
    )
    if has_any_cond and rem_base:
        rem_clean = _strip_discourse(rem_base)
        rem_toks = re.findall(r"[\w]+", rem_clean.lower())
        if not rem_toks or all(t in _GENERIC_PLACEHOLDERS for t in rem_toks):
            rem_base = ""
        else:
            rem_base = rem_clean

    return c_dict, qty, renewal, _clean_spaces(rem_base), has_any_cond


def _is_edition_only(text: str) -> bool:
    toks = re.findall(r"[\w]+", normalize(text))
    if not toks:
        return False
    allowed = frozenset(EDITION_LEVELS) | feed_noise.EDITION_ONLY_WORDS | {"и", "and"}
    has_ed = any(t in EDITION_LEVELS or t in feed_noise.EDITION_ONLY_WORDS for t in toks)
    return has_ed and all(t in allowed or re.fullmatch(r"\d+(?:\.\d+)?", t) for t in toks)


def _has_own_subject(engine, index, text: str) -> bool:
    """Проверить, задаёт ли текст собственный предмет (товар, раздел, задачу, сравнение)."""
    if not text:
        return False
    norm = _clean_spaces(normalize(text))
    if not norm:
        return False
    if index.class_match(norm):
        return True
    if hardware_head(index, norm):
        return True
    if norm in HARDWARE:
        return True
    if index.task_class(norm) or index.solutions.match(norm):
        return True
    if vendor_class(index, norm)[0]:
        return True
    if index.edition(norm):
        return True
    rep = feed_analogs.requested(norm)
    if rep:
        rep_toks = re.findall(r"[\w]+", rep.lower())
        if rep_toks and not all(t in _GENERIC_PLACEHOLDERS for t in rep_toks):
            return True
    row = index.analogs.lookup(norm, fuzzy=False)
    if row and not row.get("in_catalog"):
        return True
    if not _is_edition_only(norm) and not _AUDIENCE_ONLY_RE.fullmatch(norm):
        is_vendor_only = feed_noise.resolve_vendor(index, engine, _VENDOR_PREFIX.sub("", norm)) is not None
        if not is_vendor_only:
            if index.recovery.full_name(norm)[0]:
                return True
            if norm in index.slang and index.slang[norm][0] in {"families", "classes"}:
                return True
            if norm in index.aliases:
                return True
            hits = index.products(norm, domain="software", fuzzy=False)
            if hits and any(sold_as(index.cat.cards[cid], norm) for cid in hits[:3]):
                return True
    return False


def _vendor_compatible_section(index, prev_section: str | None, prev_root_q: str, vid: str) -> str | None:
    """Проверить, есть ли у вендора vid товары в предыдущем разделе (или его точном аналоге)."""
    if not prev_section or prev_section not in index.groups:
        return None
    if any(index.card_vendors.get(cid) == vid for cid in index.groups[prev_section]):
        return prev_section
    resolved = resolve_hardware_section(index, prev_root_q, prev_section, vid)
    if resolved and resolved in index.groups and any(index.card_vendors.get(cid) == vid for cid in index.groups[resolved]):
        return resolved
    anchor = index.cat.cards[index.groups[prev_section][0]].offers[0]
    sec_terms = set(index.class_terms.get(prev_section, ())) - feed_conditions._GENERIC_CLASS_WORDS
    if sec_terms:
        for sec, members in index.groups.items():
            if sec == prev_section or not members:
                continue
            other = index.cat.cards[members[0]].offers[0]
            if other.domain != anchor.domain or other.category_path[:1] != anchor.category_path[:1]:
                continue
            other_terms = set(index.class_terms.get(sec, ())) - feed_conditions._GENERIC_CLASS_WORDS
            if sec_terms & other_terms and any(index.card_vendors.get(cid) == vid for cid in members):
                return sec
    return None


def _card_matches_prop(card, prop: str) -> int:
    """Проверить, подходит ли карточка под свойство товара (2=точно, 1=приблизительно, 0=нет)."""
    prop_norm = _clean_spaces(normalize(prop))
    if not prop_norm:
        return 0
    title = card.title or ""
    title_l = title.lower()
    offer = card.offers[0] if card.offers else None
    attrs = offer.attrs if offer else {}
    attrs_text = " ".join(f"{k} {v}" for k, v in attrs.items() if isinstance(v, (str, int, float)))
    attrs_l = attrs_text.lower()

    m_inch = _INCH_RE.fullmatch(prop_norm)
    if m_inch:
        num = m_inch.group(1).replace(",", ".")
        num_esc = re.escape(num)
        rx_unit = re.compile(
            rf"(?<![\d.a-zа-я]){num_esc}(?:[.,]0)?\s*(?:-?inch(?:es)?|дюйм\w*|\"|''|″)",
            re.I,
        )
        if rx_unit.search(title):
            return 2
        rx_attr_val = re.compile(rf"^\s*{num_esc}(?:[.,]0)?(?:\s*(?:\"|''|″|дюйм\w*|inch\w*))?\s*$", re.I)
        for k, v in attrs.items():
            kl = str(k).lower()
            if any(w in kl for w in ("диагонал", "размер экрана", "экран", "diagonal", "screen")):
                if rx_attr_val.search(str(v)):
                    return 1
        if re.search(rf"(?<![\d.]){num_esc}(?![\d.])", title):
            return 1
        return 0

    m_mem = _STORAGE_RE.fullmatch(prop_norm)
    if m_mem:
        num = re.escape(m_mem.group(1).replace(",", "."))
        unit = m_mem.group(2).lower()
        u_rx = r"(?:гб|gb)" if unit in ("гб", "gb") else r"(?:тб|tb)" if unit in ("тб", "tb") else r"(?:мб|mb)"
        rx = re.compile(rf"(?<![\d.]){num}\s*{u_rx}\b", re.I)
        if rx.search(title) or rx.search(attrs_text):
            return 2
        return 0

    m_freq = _FREQ_RE.fullmatch(prop_norm)
    if m_freq:
        num = re.escape(m_freq.group(1).replace(",", "."))
        unit = m_freq.group(2).lower()
        u_rx = r"(?:ггц|ghz)" if unit in ("ггц", "ghz") else r"(?:мгц|mhz)" if unit in ("мгц", "mhz") else r"(?:гц|hz)"
        rx = re.compile(rf"(?<![\d.]){num}\s*{u_rx}\b", re.I)
        if rx.search(title) or rx.search(attrs_text):
            return 2
        return 0

    m_pow = _POWER_RE.fullmatch(prop_norm)
    if m_pow:
        num = re.escape(m_pow.group(1).replace(",", "."))
        unit = m_pow.group(2).lower()
        u_rx = r"(?:вт|w)" if unit in ("вт", "w") else r"(?:ва|va)"
        rx = re.compile(rf"(?<![\d.]){num}\s*{u_rx}\b", re.I)
        if rx.search(title) or rx.search(attrs_text):
            return 2
        return 0

    prop_words = words(prop_norm)
    raw_toks = [t for t in re.findall(r"[\w+-]+", prop_norm) if len(t) >= 2]
    if not prop_words and not raw_toks:
        return 0

    title_words = set(words(title_l))
    desc_l = (offer.description[:400].lower() if offer and offer.description else "")
    haystack = f"{title_l} {attrs_l} {desc_l}"

    def token_hit(w: str, raw: str) -> int:
        syns = _PROP_SYNONYMS.get(w, ())
        if w in title_words or re.search(rf"(?<![a-zа-я0-9]){re.escape(raw)}(?![a-zа-я0-9])", title_l):
            return 2
        if syns and any(s in title_l for s in syns):
            return 2
        if re.search(rf"(?<![a-zа-я0-9]){re.escape(raw)}(?![a-zа-я0-9])", attrs_l):
            return 2
        if syns and any(s in attrs_l for s in syns):
            return 2
        if w in set(words(attrs_l)):
            return 2
        if re.search(rf"(?<![a-zа-я0-9]){re.escape(raw)}(?![a-zа-я0-9])", haystack):
            return 1
        if syns and any(s in haystack for s in syns):
            return 1
        return 0

    scores = []
    for i, raw in enumerate(raw_toks):
        w = prop_words[i] if i < len(prop_words) else raw
        h = token_hit(w, raw)
        if not h:
            return 0
        scores.append(h)
    return min(scores) if scores else 0


def _filter_by_props(index, pool: list[str], props: list[str]) -> list[str]:
    """Отфильтровать пул карточек по всем накопленным свойствам."""
    if not props:
        return pool
    exact: list[str] = []
    approx: list[str] = []
    for cid in pool:
        card = index.cat.cards[cid]
        min_score = 2
        for p in props:
            sc = _card_matches_prop(card, p)
            if sc == 0:
                min_score = 0
                break
            min_score = min(min_score, sc)
        if min_score == 2:
            exact.append(cid)
        elif min_score == 1:
            approx.append(cid)
    return exact or approx


def _build_effective_query(
    root_q: str,
    vendor_text: str | None,
    edition_text: str | None,
    audience_text: str | None,
    cond_dict: dict,
    qty: dict | None,
    renewal: bool,
) -> tuple[str, dict, str | None]:
    """Собрать составной запрос, filters и sort для вызова feed.search."""
    parts = [root_q]
    if vendor_text and vendor_text.lower() not in root_q.lower():
        parts.append(vendor_text)
    if edition_text and edition_text.lower() not in " ".join(parts).lower():
        parts.append(edition_text)
    if audience_text and audience_text.lower() not in " ".join(parts).lower():
        parts.append(audience_text)
    if cond_dict.get("platform"):
        parts.append(f"для {cond_dict['platform']}")
    if cond_dict.get("exclude_labels"):
        for lbl in cond_dict["exclude_labels"]:
            parts.append(f"кроме {lbl}")
    if qty:
        unit = _QTY_UNIT_WORD.get(qty.get("metric"), "мест")
        parts.append(f"на {qty['value']} {unit}")
    if renewal:
        parts.append("продление")

    filters: dict = {}
    if cond_dict.get("price_min") is not None:
        filters["price_min"] = cond_dict["price_min"]
    if cond_dict.get("price_max") is not None:
        filters["price_max"] = cond_dict["price_max"]
    if cond_dict.get("origin") == "russian":
        filters["origin"] = "russian"
    if cond_dict.get("registry"):
        filters["registry"] = True

    sort = cond_dict.get("sort") if cond_dict.get("sort") in ("price_asc", "price_desc") else None
    return _clean_spaces(" ".join(parts)), filters, sort


def _is_valid_context(result: dict, items: list) -> bool:
    u = result.get("understood") or {}
    zr = u.get("zero_reason")
    if zr in ("unknown_term", "off_topic"):
        return False
    if u.get("intent") == "broad" and not items:
        return False
    if not items and zr != "filters_too_strict":
        return False
    return True


def snapshot(engine, req, result: dict, items: list, *, overrides: dict | None = None) -> dict | None:
    """Сформировать компактный снимок предмета и условий для сохранения в Sessions."""
    if not req.session_id:
        return None
    main_items = [c for c in items if c.get("kind") != "upsell"]
    if not _is_valid_context(result, main_items):
        return None
    index = engine.catalog.feed
    u = result.get("understood") or {}
    filters = u.get("filters") or {}
    norm = normalize(req.q)
    if not req.verbatim:
        norm = index.recovery.clean_query(norm)

    c_dict, qty_parsed, renewal_parsed, rem_base, _ = _probe_conditions(engine, norm, req)
    root_q = rem_base or norm
    section = (filters.get("category") or [None])[0]
    vendor = (filters.get("vendor") or [None])[0]
    first_cid = main_items[0]["card_id"] if main_items else None
    first_section = index.card_sections.get(first_cid) if first_cid else section
    first_domain = (
        index.cat.cards[first_cid].offers[0].domain
        if first_cid and first_cid in index.cat.cards
        else None
    )
    domestic = bool(
        first_cid
        and first_cid in index.cat.cards
        and feed_conditions.is_domestic_card(index, engine.kb, engine, first_cid)
    )

    subject_core = root_q
    vendor_text = None
    edition_text = None
    if vendor and section:
        v_hit, sec_hit = vendor_class(index, root_q)
        if v_hit == vendor and sec_hit:
            parts = root_q.split()
            for length in range(min(len(parts) - 1, 4), 0, -1):
                for v_side, rest_side in ((parts[:length], parts[length:]), (parts[-length:], parts[:-length])):
                    alias = " ".join(v_side)
                    if index.vendor_names.get(alias) == vendor or index.vendor_names.get(" ".join(words(alias))) == vendor:
                        subject_core = " ".join(rest_side)
                        vendor_text = alias
                        break
                if vendor_text:
                    break
    elif not section and index.edition(root_q):
        # Отделить хвостовую редакцию («windows 11 pro» -> core «windows 11», edition «pro»),
        # чтобы следующее уточнение «а для дома» переключило редакцию, а не склеило «pro home».
        toks = root_q.split()
        end = len(toks)
        while end > 1 and toks[end - 1] in EDITION_LEVELS:
            end -= 1
        if end < len(toks):
            subject_core = " ".join(toks[:end])
            edition_text = " ".join(toks[end:])

    if filters.get("price_max") is not None and c_dict["price_max"] is None:
        c_dict["price_max"] = float(filters["price_max"])
    if filters.get("price_min") is not None and c_dict["price_min"] is None:
        c_dict["price_min"] = float(filters["price_min"])
    if filters.get("origin") == "russian":
        c_dict["origin"] = "russian"
    if filters.get("registry"):
        c_dict["registry"] = True
    if filters.get("sort") in ("price_asc", "price_desc"):
        c_dict["sort"] = filters["sort"]
    if filters.get("platform"):
        p = filters["platform"]
        c_dict["platform"] = p[0] if isinstance(p, list) and p else (p if isinstance(p, str) else c_dict["platform"])

    snap = {
        "valid": True,
        "display_q": req.q.strip(),
        "root_q": root_q,
        "subject_core": subject_core,
        "vendor_text": vendor_text,
        "edition_text": edition_text,
        "audience_text": None,
        "analog_for": None,
        "section": section,
        "first_section": first_section,
        "first_domain": first_domain,
        "vendor": vendor,
        "props": [],
        "cond": c_dict,
        "qty": u.get("qty") or qty_parsed,
        "renewal": renewal_parsed or filters.get("action") == "renewal",
        "intent": u.get("intent"),
        "domestic": domestic,
        "inherited": False,
        "parent": None,
    }
    if overrides:
        snap.update(overrides)
    return snap


def _render_section_result(
    engine,
    req,
    profile,
    trace,
    priorities,
    section: str,
    pool: list[str],
    props: list[str],
    cond_dict: dict,
    vendor: str | None,
    qty: dict | None,
    renewal: bool,
    display_subject: str,
) -> dict | None:
    """Собрать ответ для уточнения по свойству товара (или вендору внутри раздела)."""
    from .feed import display, finish, order, recommend

    index = engine.catalog.feed
    ids = _filter_by_props(index, pool, props) if props else list(pool)
    if not ids:
        return None

    preferred: dict = {}
    selections: dict = {}
    note = ""
    if qty or renewal:
        constraints = {"price_max": cond_dict["price_max"]} if cond_dict.get("price_max") is not None else {}
        selections = matching_variants(index, ids, profile, qty, renewal, constraints)
        if selections:
            ids = list(selections)

    cond = _cond_from_dict(display_subject, cond_dict)
    if ids and (cond.active or cond.price_min is not None or cond.price_max is not None):
        ids, section, note, _ = feed_conditions.apply_conditions(
            engine, req, profile, cond, ids, section, preferred, selections, qty, renewal, note
        )

    title = index.classes.get(section) or TITLES["category"]
    summary = f"{title} · {', '.join(props)}" if props else title
    trace.add("retrieve", "Уточнение в контексте", summary, candidates=len(ids))
    start = (req.page - 1) * req.page_size
    items = [display(engine, cid, profile, preferred.get(cid), selections.get(cid)) for cid in ids[start:start + req.page_size]]
    for i, c in enumerate(items, 1):
        c["position"] = i
    merch = order(engine, req, profile, trace, priorities, "category", section, items)
    if merch is None:
        return None
    items = merch["cards"]
    if cond.sort in ("price_asc", "price_desc") and items:
        rev = cond.sort == "price_desc"
        items.sort(
            key=lambda c: (
                c.get("price_from") is None,
                (-c["price_from"] if rev else c["price_from"]) if c.get("price_from") is not None else 0.0,
            )
        )
    main = [c["card_id"] for c in items]
    together, _ = recommend(engine, display_subject, items, profile, "category", complete=None, price_max=cond.price_max)
    for i, c in enumerate(items, 1):
        c["position"] = i
    blocks = [dict(type="products", title=title, category_id=section, total=len(ids), items=items)]
    if together:
        blocks.append(together)

    chips = [dict(key="property", label=p, removable=True) for p in props]
    if qty:
        chips.append(dict(key="quantity", label=f"Количество · {qty['value']}"))

    result = dict(
        search_id="s_" + uuid4().hex,
        engine="kuznitsa",
        engine_version="1.0",
        mode=req.mode,
        query=dict(raw=req.q, normalized=normalize(req.q), corrected=display_subject, corrections=[], did_you_mean=None),
        understood=dict(
            intent="category",
            intent_title=TITLES["category"],
            intent_conf=0.9,
            intent_source="rules",
            filters=dict(category=[section]) if section else {},
            exclude={},
            qty=qty,
            entities=[],
            chips=chips,
            zero_reason="filters_too_strict" if (cond.price_max is not None and not ids) else None,
            agent_note=note or summary,
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
    if vendor:
        result["understood"]["filters"]["vendor"] = [vendor]
    feed_conditions.populate_result(cond, result, chips)
    return finish(engine, req, trace, False, result, items, len(main), [], profile=profile)


def _visible_items(result: dict) -> list:
    for block in result.get("blocks") or []:
        if block.get("type") in ("products", "analogs"):
            items = block.get("items") or []
            return [i["card"] if isinstance(i.get("card"), dict) else i for i in items if i.get("kind") != "upsell"]
    return []


def _attach_inherited(
    engine,
    req,
    norm: str,
    trace,
    record: bool,
    result: dict,
    prev: dict,
    prev_feed: dict,
    fields: list[str],
    new_feed_overrides: dict,
    *,
    is_pagination: bool = False,
) -> dict:
    """Оформить поля наследования, значок контекста, запись в сессию и журнал."""
    from_q = prev_feed.get("display_q") or prev.get("q") or ""
    result["query"]["raw"] = req.q
    result["query"]["normalized"] = norm

    u = result["understood"]
    u["inherited"] = {
        "from_search_id": prev.get("id"),
        "from_q": from_q,
        "fields": sorted(set(fields)) or ["subject"],
    }
    chips = u.setdefault("chips", [])
    if not any(c.get("key") == "context" for c in chips):
        chips.insert(
            0,
            dict(
                key="context",
                label=f"В контексте · {from_q}",
                source="context",
                removable=True,
            ),
        )

    result["timing_ms"]["total"] = round(1000 * (engine.timer() - trace.start), 2)
    items = _visible_items(result)

    if record:
        compact_parent = {
            "id": prev.get("id"),
            "q": prev.get("q"),
            "filters": prev.get("filters") or {},
            "exclude": prev.get("exclude") or {},
            "qty": prev.get("qty"),
            "intent": prev.get("intent"),
            "feed": {k: v for k, v in prev_feed.items() if k != "parent"},
        }
        overrides = {
            **new_feed_overrides,
            "inherited": True,
            "parent": compact_parent,
        }
        if not is_pagination and engine.sessions:
            snap = snapshot(engine, req, result, items, overrides=overrides)
            if snap:
                engine.sessions.save(req, result, items, extra=snap)
        engine.journal.search(
            engine.clock(),
            req,
            result,
            len(items),
            u.get("zero_reason"),
            False,
        )
    if not req.explain:
        result["trace"] = []
    return result


def try_search(engine, req, profile, trace, priorities, record):
    """Проверить, является ли запрос уточнением в сессии, и выполнить поиск в контексте."""
    if (
        not engine.sessions
        or not req.session_id
        or req.context == "off"
        or "context" in req.ignore
        or req.verbatim
        or req.category
        or "\n" in req.q
    ):
        return None

    prev = engine.sessions.previous(req)
    if not prev:
        return None

    index = engine.catalog.feed
    norm = index.recovery.clean_query(normalize(req.q))
    if not norm:
        return None

    prev_feed = prev.get("feed")
    if not isinstance(prev_feed, dict) or not prev_feed.get("valid"):
        return None

    # Вторая страница того же запроса — не уточнение!
    is_pagination = False
    if norm == index.recovery.clean_query(normalize(prev.get("q") or "")):
        if prev_feed.get("inherited") and req.page > 1 and prev_feed.get("parent"):
            prev = prev_feed["parent"]
            prev_feed = prev.get("feed") or {}
            if not prev_feed.get("valid"):
                return None
            is_pagination = True
        else:
            return None

    if feed_noise.is_garbage_syntax(req.q, norm, index, engine.catalog):
        return None

    tail = _strip_discourse(norm)
    if not tail:
        return None

    # Случай «а на 50?» — голое число после запроса с количеством
    bare_num = re.fullmatch(r"(?:на\s+)?(\d{1,7})", tail)
    if bare_num and (prev_feed.get("qty") or (tail.startswith("на ") and prev_feed.get("first_domain") == "software")):
        prev_metric = (prev_feed.get("qty") or {}).get("metric") or "device"
        new_qty = {"value": int(bare_num.group(1)), "metric": prev_metric}
        c_dict = _merge_cond_dicts(prev_feed.get("cond"), {})
        return _execute_refined(
            engine, req, norm, profile, trace, priorities, record, prev, prev_feed,
            cond_dict=c_dict,
            qty=new_qty,
            renewal=bool(prev_feed.get("renewal")),
            vendor=prev_feed.get("vendor"),
            vendor_text=prev_feed.get("vendor_text"),
            edition_text=prev_feed.get("edition_text"),
            audience_text=prev_feed.get("audience_text"),
            section=prev_feed.get("section"),
            props=list(prev_feed.get("props") or []),
            analog_for=prev_feed.get("analog_for"),
            fields=_inherited_fields(prev_feed, added="qty"),
            is_pagination=is_pagination,
        )

    # 1. Разбор условий через feed_conditions.extract + split_conditions
    new_cond, new_qty, new_renewal, rem, has_cond = _probe_conditions(engine, tail, req)

    prev_root = prev_feed.get("root_q") or ""
    prev_core = prev_feed.get("subject_core") or prev_root
    prev_section = prev_feed.get("section")
    prev_first_section = prev_feed.get("first_section") or prev_section
    prev_vendor = prev_feed.get("vendor")
    prev_vendor_text = prev_feed.get("vendor_text")
    prev_edition = prev_feed.get("edition_text")
    prev_audience = prev_feed.get("audience_text")
    prev_props = list(prev_feed.get("props") or [])
    prev_analog_for = prev_feed.get("analog_for")

    merged_cond = _merge_cond_dicts(prev_feed.get("cond"), new_cond)
    merged_qty = new_qty or prev_feed.get("qty")
    merged_renewal = bool(new_renewal or prev_feed.get("renewal"))

    # Случай A: только условия (цена, сортировка, количество, продление, платформа, российское, исключение)
    if not rem and has_cond:
        wants_ru = bool(new_cond.get("origin") == "russian" or new_cond.get("registry"))
        if wants_ru and not prev_section and not prev_feed.get("domestic") and not prev_analog_for:
            return _execute_russian_analog(
                engine, req, norm, profile, trace, priorities, record, prev, prev_feed,
                cond_dict=merged_cond,
                qty=merged_qty,
                is_pagination=is_pagination,
            )

        return _execute_refined(
            engine, req, norm, profile, trace, priorities, record, prev, prev_feed,
            cond_dict=merged_cond,
            qty=merged_qty,
            renewal=merged_renewal,
            vendor=prev_vendor,
            vendor_text=prev_vendor_text,
            edition_text=prev_edition,
            audience_text=prev_audience,
            section=prev_section,
            props=prev_props,
            analog_for=prev_analog_for,
            fields=_inherited_fields(prev_feed),
            is_pagination=is_pagination,
        )

    # Случай B: явный запрос аналога предыдущего предмета («аналоги», «чем заменить», «другой производитель»)
    if _ANALOG_ONLY_RE.fullmatch(rem):
        return _execute_russian_analog(
            engine, req, norm, profile, trace, priorities, record, prev, prev_feed,
            cond_dict=merged_cond,
            qty=merged_qty,
            russian=bool(merged_cond.get("origin") == "russian" or merged_cond.get("registry")),
            is_pagination=is_pagination,
        )

    # Если в остатке явно новый предмет — НЕ наследуем!
    if _has_own_subject(engine, index, rem):
        return None

    # Случай C: аудитория («для дома», «а для дома», «домашняя», «для бизнеса», «для организаций», ...)
    if _AUDIENCE_ONLY_RE.fullmatch(rem):
        if HOME.search(rem) and not prev_section:
            ed_target = f"{prev_core} home"
            if index.edition(ed_target):
                return _execute_refined(
                    engine, req, norm, profile, trace, priorities, record, prev, prev_feed,
                    cond_dict=merged_cond,
                    qty=merged_qty,
                    renewal=merged_renewal,
                    vendor=None,
                    vendor_text=None,
                    edition_text="home",
                    audience_text=None,
                    section=None,
                    props=prev_props,
                    analog_for=None,
                    fields=_inherited_fields(prev_feed, added="edition"),
                    is_pagination=is_pagination,
                )
        return _execute_refined(
            engine, req, norm, profile, trace, priorities, record, prev, prev_feed,
            cond_dict=merged_cond,
            qty=merged_qty,
            renewal=merged_renewal,
            vendor=prev_vendor,
            vendor_text=prev_vendor_text,
            edition_text=prev_edition,
            audience_text=rem,
            section=prev_section,
            props=prev_props,
            analog_for=prev_analog_for,
            fields=_inherited_fields(prev_feed, added="audience"),
            is_pagination=is_pagination,
        )

    # Случай D: редакция («pro», «home», «standard», «enterprise», «plus», ...)
    if _is_edition_only(rem):
        ed_hit = index.edition(f"{prev_core} {rem}") or index.edition(f"{prev_root} {rem}")
        if ed_hit:
            return _execute_refined(
                engine, req, norm, profile, trace, priorities, record, prev, prev_feed,
                cond_dict=merged_cond,
                qty=merged_qty,
                renewal=merged_renewal,
                vendor=None,
                vendor_text=None,
                edition_text=rem,
                audience_text=None,
                section=None,
                props=prev_props,
                analog_for=None,
                fields=_inherited_fields(prev_feed, added="edition"),
                is_pagination=is_pagination,
            )

    # Случай E: производитель («lenovo», «samsung», «hp», «dr web», «от asus»)
    v_cand = _clean_spaces(_VENDOR_PREFIX.sub("", rem))
    v_resolved = feed_noise.resolve_vendor(index, engine, v_cand) if v_cand else None
    if v_resolved:
        vid, display_name = v_resolved
        compat_sec = _vendor_compatible_section(index, prev_section, prev_core, vid)
        if compat_sec:
            v_text = v_cand
            if not vendor_class(index, f"{prev_core} {v_text}")[0]:
                alt_v = normalize(display_name)
                if vendor_class(index, f"{prev_core} {alt_v}")[0]:
                    v_text = alt_v
            return _execute_refined(
                engine, req, norm, profile, trace, priorities, record, prev, prev_feed,
                cond_dict=merged_cond,
                qty=merged_qty,
                renewal=merged_renewal,
                vendor=vid,
                vendor_text=v_text,
                edition_text=prev_edition,
                audience_text=prev_audience,
                section=compat_sec,
                props=prev_props,
                analog_for=None,
                fields=_inherited_fields(prev_feed, added="vendor"),
                is_pagination=is_pagination,
            )
        return None

    # Случай F: свойство товара / характеристика («27 дюймов», «16 гб», «черный», «ips», «беспроводная», ...)
    if prev_section and prev_section in index.groups:
        pool = list(index.groups[prev_section])
        if prev_vendor:
            v_pool = [cid for cid in pool if index.card_vendors.get(cid) == prev_vendor]
            if v_pool:
                pool = v_pool
        if prev_feed.get("first_domain") == "hardware":
            pool = rank_hardware_section(index, prev_section, prev_core, pool)
        new_props = [*prev_props, rem]
        matched = _filter_by_props(index, pool, new_props)
        if matched:
            target_sec = prev_section
            display_subject = _clean_spaces(" ".join(filter(None, [prev_core, prev_vendor_text, *new_props])))
            res = _render_section_result(
                engine, req, profile, trace, priorities,
                target_sec, pool, new_props, merged_cond, prev_vendor, merged_qty, merged_renewal, display_subject,
            )
            if res is not None:
                return _attach_inherited(
                    engine, req, norm, trace, record, res, prev, prev_feed,
                    fields=_inherited_fields(prev_feed, added="property"),
                    new_feed_overrides={
                        "display_q": _chain_display(prev_feed, req.q),
                        "root_q": prev_root,
                        "subject_core": prev_core,
                        "vendor": prev_vendor,
                        "vendor_text": prev_vendor_text,
                        "edition_text": prev_edition,
                        "audience_text": prev_audience,
                        "section": target_sec,
                        "props": new_props,
                        "cond": merged_cond,
                        "qty": merged_qty,
                        "renewal": merged_renewal,
                    },
                    is_pagination=is_pagination,
                )

    # Общий запасной случай для конкретного продукта без раздела: составной запрос даёт совпадения того же продукта
    if not prev_section and prev_core and len(rem.split()) <= 3:
        combined = f"{prev_core} {rem}"
        ed_hit = index.edition(combined)
        if ed_hit:
            return _execute_refined(
                engine, req, norm, profile, trace, priorities, record, prev, prev_feed,
                cond_dict=merged_cond,
                qty=merged_qty,
                renewal=merged_renewal,
                vendor=prev_vendor,
                vendor_text=prev_vendor_text,
                edition_text=rem,
                audience_text=prev_audience,
                section=None,
                props=prev_props,
                analog_for=None,
                fields=_inherited_fields(prev_feed, added="property"),
                is_pagination=is_pagination,
            )
        base_hits = set(index.products(prev_core, fuzzy=False))
        comb_hits = [cid for cid in index.products(combined, fuzzy=False) if cid in base_hits]
        if comb_hits:
            return _execute_refined(
                engine, req, norm, profile, trace, priorities, record, prev, prev_feed,
                cond_dict=merged_cond,
                qty=merged_qty,
                renewal=merged_renewal,
                vendor=prev_vendor,
                vendor_text=prev_vendor_text,
                edition_text=rem,
                audience_text=prev_audience,
                section=None,
                props=prev_props,
                analog_for=None,
                fields=_inherited_fields(prev_feed, added="property"),
                is_pagination=is_pagination,
            )

    return None


def _inherited_fields(prev_feed: dict, added: str | None = None) -> list[str]:
    fields: list[str] = []
    if prev_feed.get("section"):
        fields.append("category")
    else:
        fields.append("subject")
    if prev_feed.get("vendor") and added != "vendor":
        fields.append("vendor")
    if prev_feed.get("props"):
        fields.append("property")
    prev_cond = prev_feed.get("cond") or {}
    for k in ("price_min", "price_max", "origin", "registry", "platform"):
        if prev_cond.get(k) is not None and prev_cond.get(k) is not False:
            fields.append(k)
    if prev_feed.get("qty") and added != "qty":
        fields.append("qty")
    return fields


def _chain_display(prev_feed: dict, new_q: str) -> str:
    prev_disp = (prev_feed.get("display_q") or "").strip()
    cur = (new_q or "").strip()
    if not prev_disp:
        return cur
    if cur.lower() in prev_disp.lower():
        return prev_disp
    return f"{prev_disp} {cur}"


def _execute_refined(
    engine,
    req,
    norm: str,
    profile,
    trace,
    priorities,
    record: bool,
    prev: dict,
    prev_feed: dict,
    *,
    cond_dict: dict,
    qty: dict | None,
    renewal: bool,
    vendor: str | None,
    vendor_text: str | None,
    edition_text: str | None,
    audience_text: str | None,
    section: str | None,
    props: list[str],
    analog_for: str | None,
    fields: list[str],
    is_pagination: bool,
) -> dict | None:
    """Выполнить составной поиск в контексте предыдущего запроса."""
    from . import feed

    index = engine.catalog.feed
    prev_root = prev_feed.get("root_q") or ""
    prev_core = prev_feed.get("subject_core") or prev_root

    if analog_for:
        return _execute_russian_analog(
            engine, req, norm, profile, trace, priorities, record, prev, prev_feed,
            cond_dict=cond_dict,
            qty=qty,
            russian=bool(cond_dict.get("origin") == "russian" or cond_dict.get("registry")),
            subject_override=analog_for,
            is_pagination=is_pagination,
        )

    base_subject = prev_core if (vendor_text or edition_text) else prev_root

    # Прямая сборка по разделу, если накоплены свойства товара ИЛИ вендор не разбирается через vendor_class
    direct_vendor = bool(
        vendor and section and section in index.groups
        and (not vendor_text or not vendor_class(index, f"{prev_core} {vendor_text}")[0])
    )
    if (props or direct_vendor) and section and section in index.groups:
        pool = list(index.groups[section])
        if vendor:
            v_pool = [cid for cid in pool if index.card_vendors.get(cid) == vendor]
            if v_pool:
                pool = v_pool
        if prev_feed.get("first_domain") == "hardware":
            pool = rank_hardware_section(index, section, prev_core, pool)
        display_subject = _clean_spaces(" ".join(filter(None, [prev_core, vendor_text, *props])))
        res = _render_section_result(
            engine, req, profile, trace, priorities,
            section, pool, props, cond_dict, vendor, qty, renewal, display_subject,
        )
        if res is not None:
            return _attach_inherited(
                engine, req, norm, trace, record, res, prev, prev_feed,
                fields=fields,
                new_feed_overrides={
                    "display_q": _chain_display(prev_feed, req.q),
                    "root_q": prev_root,
                    "subject_core": prev_core,
                    "vendor": vendor,
                    "vendor_text": vendor_text,
                    "edition_text": edition_text,
                    "audience_text": audience_text,
                    "section": section,
                    "props": props,
                    "cond": cond_dict,
                    "qty": qty,
                    "renewal": renewal,
                },
                is_pagination=is_pagination,
            )

    eff_q, eff_filters, eff_sort = _build_effective_query(
        base_subject, vendor_text, edition_text, audience_text, cond_dict, qty, renewal
    )
    merged_filters = {**eff_filters, **req.filters}
    merged_sort = req.sort or eff_sort

    child_req = req.model_copy(
        update={
            "q": eff_q,
            "context": "off",
            "filters": merged_filters,
            "sort": merged_sort,
        }
    )
    res = feed.search(engine, child_req, profile, trace, priorities, record=False)
    if res is None:
        return None

    res_section = (res.get("understood", {}).get("filters", {}).get("category") or [section])[0]
    res_vendor = (res.get("understood", {}).get("filters", {}).get("vendor") or [vendor])[0]

    return _attach_inherited(
        engine, req, norm, trace, record, res, prev, prev_feed,
        fields=fields,
        new_feed_overrides={
            "display_q": _chain_display(prev_feed, req.q),
            "root_q": prev_root,
            "subject_core": prev_core,
            "vendor": res_vendor,
            "vendor_text": vendor_text,
            "edition_text": edition_text,
            "audience_text": audience_text,
            "section": res_section,
            "props": props,
            "cond": cond_dict,
            "qty": qty,
            "renewal": renewal,
        },
        is_pagination=is_pagination,
    )


def _execute_russian_analog(
    engine,
    req,
    norm: str,
    profile,
    trace,
    priorities,
    record: bool,
    prev: dict,
    prev_feed: dict,
    *,
    cond_dict: dict,
    qty: dict | None,
    russian: bool = True,
    subject_override: str | None = None,
    is_pagination: bool = False,
) -> dict | None:
    """Подобрать (российские) аналоги к предыдущему продукту в контексте."""
    from . import feed

    target = subject_override or prev_feed.get("root_q") or prev.get("q") or ""
    if not target:
        return None

    prefix = "российский аналог" if russian else "аналог"
    parts = [prefix, target]
    if qty:
        unit = _QTY_UNIT_WORD.get(qty.get("metric"), "мест")
        parts.append(f"на {qty['value']} {unit}")
    eff_q = _clean_spaces(" ".join(parts))

    eff_filters = dict(req.filters)
    if cond_dict.get("price_max") is not None:
        eff_filters.setdefault("price_max", cond_dict["price_max"])
    if cond_dict.get("registry"):
        eff_filters.setdefault("registry", True)

    child_req = req.model_copy(
        update={
            "q": eff_q,
            "context": "off",
            "filters": eff_filters,
            "sort": req.sort or cond_dict.get("sort"),
        }
    )
    res = feed.search(engine, child_req, profile, trace, priorities, record=False)

    if res is None or len(_visible_items(res)) < 2:
        first_sec = prev_feed.get("first_section")
        index = engine.catalog.feed
        if first_sec and first_sec in index.classes:
            sec_req = req.model_copy(
                update={
                    "q": index.classes[first_sec],
                    "context": "off",
                    "filters": {**eff_filters, "origin": "russian"},
                    "sort": req.sort or cond_dict.get("sort"),
                }
            )
            alt = feed.search(engine, sec_req, profile, trace, priorities, record=False)
            if alt is not None and len(_visible_items(alt)) >= len(_visible_items(res or {})):
                res = alt

    if res is None:
        return None

    if cond_dict.get("sort") in ("price_asc", "price_desc"):
        rev = cond_dict["sort"] == "price_desc"
        for b in res.get("blocks") or []:
            if b.get("type") in ("products", "analogs") and b.get("items"):
                def _k(item):
                    c = item["card"] if isinstance(item.get("card"), dict) else item
                    p = c.get("price_from")
                    return (p is None, (-p if rev else p) if p is not None else 0.0)
                b["items"].sort(key=_k)

    return _attach_inherited(
        engine, req, norm, trace, record, res, prev, prev_feed,
        fields=_inherited_fields(prev_feed, added="origin"),
        new_feed_overrides={
            "display_q": _chain_display(prev_feed, req.q),
            "root_q": target,
            "subject_core": target,
            "analog_for": target,
            "cond": cond_dict,
            "qty": qty,
            "domestic": russian,
        },
        is_pagination=is_pagination,
    )
