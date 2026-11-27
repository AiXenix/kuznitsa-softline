"""Сравнение двух продуктов или редакций по данным фида."""
from dataclasses import dataclass
import re
from uuid import uuid4

from kuznitsa.index.feed import words
from kuznitsa.index.feed_editions import LEVEL as EDITION_LEVELS
from kuznitsa.index.feed_language import edition_form, sold_as
from kuznitsa.llm.recovery import cost_summary
from kuznitsa.plans.presentation import profile_info
from kuznitsa.text import normalize
from kuznitsa.understand.intent import TITLES
from kuznitsa.understand.quantities import spoken_numbers

PREFIX_COMPARE_RE = re.compile(
    r"^(?:сравнить|сравнение|сравни|что\s+лучше(?:\s+выбрать)?|что\s+выбрать|"
    r"в\s+ч[её]м\s+разница\s+между|разница\s+между|отличи[яе]\s+между)\s+"
    r"(?P<a>.+?)\s+(?:и|или|vs\.?|против|от)\s+(?P<b>.+)$"
)

DIFF_RE = re.compile(
    r"^(?:чем|в\s+ч[её]м)\s+(?:(?P<a1>.+?)\s+отлича\w*|отлича\w*\s+(?P<a2>.+?))\s+от\s+(?P<b>.+)$"
)

VS_RE = re.compile(r"^(?P<a>.+?)\s+(?:vs\.?|против)\s+(?P<b>.+)$")
OR_RE = re.compile(r"^(?P<a>.+?)\s+или\s+(?P<b>.+)$")

CONDITION_TOKENS = frozenset({
    "год", "года", "лет", "мес", "месяц", "месяца", "месяцев",
    "пк", "pk", "мест", "места", "место", "пользователей", "пользователя", "пользователь",
    "устройств", "устройства", "устройство", "лицензий", "лицензии", "лицензия",
    "подписка", "бессрочная", "бессрочный", "коробка", "box", "oem", "esd", "электронная",
    "дома", "дом", "офиса", "офис", "бизнеса", "бизнес", "школы", "вуза", "облако", "локально",
    "руб", "рублей", "тыс",
})
PREPOSITIONS = frozenset({"на", "для", "в", "до", "от", "с", "по", "под", "при", "без"})
QUESTION_START = re.compile(r"^(?:что|как|какой|какая|какое|какие|где|сколько|можно\s+ли|нужен\s+ли|аналог|замена|чем\s+заменить)\b")

MODEL_LABELS = {
    "subscription": "Подписка",
    "perpetual": "Бессрочная лицензия",
}
METRIC_LABELS = {
    "device": "на устройство",
    "user": "на пользователя",
    "concurrent": "конкурентная",
    "server": "на сервер",
    "core": "на ядро",
    "cpu": "на процессор",
    "vm": "на ВМ",
    "mailbox": "на почтовый ящик",
    "company": "на организацию",
    "site": "на площадку",
}


@dataclass(frozen=True)
class SideMatch:
    raw: str
    query: str
    cards: tuple[str, ...]
    neighbors: tuple[str, ...]
    analog_row: dict | None = None


def parse_compare(norm):
    """Разобрать запрос на сравнение. Возвращает (left, right, explicit) или None."""
    cleaned = norm.strip(" ?!.,;:")
    if not cleaned or "\n" in cleaned:
        return None
    for rx in (PREFIX_COMPARE_RE, VS_RE):
        m = rx.match(cleaned)
        if m:
            a, b = m.group("a").strip(" ,;:?"), m.group("b").strip(" ,;:?")
            if a and b:
                return a, b, True
    m = DIFF_RE.match(cleaned)
    if m:
        a = (m.group("a1") or m.group("a2") or "").strip(" ,;:?")
        b = m.group("b").strip(" ,;:?")
        if a and b:
            # FAQ про упаковку/лицензирование («чем отличается oem от box и esd») не перехватываем
            a_words = set(words(a))
            b_words = set(words(b))
            if (a_words | b_words) <= CONDITION_TOKENS:
                return None
            return a, b, True
    m = OR_RE.match(cleaned)
    if m:
        a, b = m.group("a").strip(" ,;:?"), m.group("b").strip(" ,;:?")
        if not a or not b:
            return None
        if QUESTION_START.match(a):
            return None
        a_parts = a.split()
        b_parts = b.split()
        # «на 1 или 2 года», «для дома или офиса», «щит или подписка» — условия, не сравнение
        if a_parts[-1].isdigit() and b_parts[0].isdigit():
            return None
        if b_parts[0] in CONDITION_TOKENS or set(b_parts) <= CONDITION_TOKENS:
            return None
        if len(a_parts) >= 2 and a_parts[-2] in PREPOSITIONS and (a_parts[-1].isdigit() or a_parts[-1] in CONDITION_TOKENS):
            return None
        if a_parts[-1] in PREPOSITIONS:
            return None
        return a, b, False
    return None


def _clean_side(index, engine, text):
    mapped, _ = engine._phrases.apply(text)
    return edition_form(index, index.correct(spoken_numbers(mapped))).strip()


def _resolve_single(engine, raw_text, profile):
    index = engine.catalog.feed
    cleaned = _clean_side(index, engine, raw_text)
    if not cleaned:
        return SideMatch(raw_text, cleaned, (), ())

    # 1. Проверяем, не является ли сторона заведомо отсутствующим продуктом из справочника аналогов
    row = index.analogs.lookup(raw_text, fuzzy=False) or index.analogs.lookup(cleaned, fuzzy=False)

    # 2. Точная редакция («kaspersky standard», «kaspersky plus», «windows 11 home», «windows 11 pro»)
    ed = index.edition(cleaned) or index.edition(raw_text)
    if ed and ed.cards:
        return SideMatch(raw_text, ed.query, ed.cards, ed.neighbors, analog_row=row)

    # 3. Прямой поиск карточек в фиде (включая слитное написание «мой офис» → «мойофис»)
    variants = [cleaned, raw_text]
    if " " in cleaned and len(cleaned.split()) == 2:
        variants.append(cleaned.replace(" ", ""))
    if " " in raw_text and len(raw_text.split()) == 2:
        variants.append(raw_text.replace(" ", ""))
    variants = list(dict.fromkeys(v for v in variants if v))

    candidates = []
    for variant in variants:
        hits = index.products(variant, domain="software", fuzzy=False, segment=profile.segment)
        if not hits:
            hits = index.products(variant, fuzzy=False, segment=profile.segment)
        if hits:
            candidates = list(hits)
            cleaned = variant
            break

    # Проверка по slang / vendor_names / фонетике / recovery
    if not candidates:
        for variant in variants:
            sl = index.slang.get(variant)
            if sl and sl[1]:
                candidates = list(sl[1])
                break
            vid = index.vendor_names.get(variant) or index.vendor_names.get(" ".join(words(variant)))
            if vid:
                vcards = index.language.vendor_cards.get(vid, ())
                if vcards:
                    candidates = sorted(vcards, key=lambda c: index.browse_quality.get(c, ()), reverse=True)
                    break
    if not candidates:
        for variant in variants:
            sound_hits, sound_q = index.sound_products(variant)
            if sound_hits:
                candidates = list(sound_hits)
                cleaned = sound_q
                break
    if not candidates:
        rec_hits, rec_q, _ = index.recovery.lookup(engine, cleaned)
        if rec_hits:
            candidates = list(rec_hits)
            cleaned = rec_q

    # Если товар известен как отсутствующий (in_catalog=False), проверяем, действительно ли продаётся сам продукт
    if row and not row.get("in_catalog"):
        real = [cid for cid in candidates if sold_as(index.cat.cards[cid], cleaned) or sold_as(index.cat.cards[cid], raw_text)]
        if not real:
            return SideMatch(raw_text, cleaned, (), (), analog_row=row)
        candidates = real

    if not candidates:
        return SideMatch(raw_text, cleaned, (), (), analog_row=row)

    # Ранжирование: приоритет карточкам, продающимся под этим именем (sold_as), а не плагинам/надстройкам («ModPlus AutoCAD»)
    def rank_side(cid):
        card = index.cat.cards[cid]
        own = sold_as(card, cleaned) or sold_as(card, raw_text)
        bq = index.browse_quality.get(cid, (False, 0, False, 0, False))
        # Основная редакция выше редких/узкоспециализированных модулей
        niche = bool(re.search(r"виртуальн|систем\s+хранен|embedded|wingate|модуль|плагин|plugin|add-?on", card.title, re.I))
        title_norm = normalize(card.title)
        starts = title_norm.startswith(cleaned) or title_norm.startswith("autodesk " + cleaned) or title_norm.startswith("microsoft " + cleaned)
        return (own, starts, bq[0], not niche, card.offers[0].available, card.price_from is not None, bq[1], len(card.offers), -len(card.title))

    ordered = sorted(dict.fromkeys(candidates), key=rank_side, reverse=True)
    # Соседи из той же линейки / вендора / раздела
    anchor = index.cat.cards[ordered[0]]
    sec = index.card_sections[anchor.id]
    neighbors = [
        cid for cid in index.groups.get(sec, ())
        if cid != anchor.id and index.cat.cards[cid].vendor == anchor.vendor
    ]
    return SideMatch(raw_text, cleaned, tuple(ordered), tuple(neighbors), analog_row=row)


def _expand_right(engine, left_text, right_text, left_match, profile):
    """Унаследовать бренд и линейку первой стороны для сокращённой второй («kaspersky standard или plus», «windows 11 home vs pro»)."""
    right_tokens = right_text.split()
    left_tokens = left_text.split()
    if len(left_tokens) < 2 or len(right_tokens) > 2:
        return _resolve_single(engine, right_text, profile)
    # Если правая сторона — короткая редакция/версия или не нашлась сама по себе
    short_edition = all(t in EDITION_LEVELS or t.isdigit() for t in right_tokens)
    direct = _resolve_single(engine, right_text, profile)
    if direct.cards and not short_edition:
        # Проверим, не является ли прямое совпадение совсем посторонним для короткой редакции
        return direct
    if direct.analog_row and not direct.analog_row.get("in_catalog") and not short_edition:
        return direct

    left_first = left_match.cards[0] if left_match.cards else None
    # Пробуем подставить right_tokens вместо последних k токенов left_tokens
    k_order = list(dict.fromkeys([len(right_tokens), 1, 2]))
    for k in k_order:
        if k >= len(left_tokens):
            continue
        candidate_q = " ".join([*left_tokens[:-k], *right_tokens])
        cand = _resolve_single(engine, candidate_q, profile)
        if cand.cards and (cand.cards[0] != left_first or len(cand.cards) > 1):
            return cand
    # Также пробуем просто «первый токен левой + правая» (например бренд + редакция)
    candidate_q = " ".join([left_tokens[0], *right_tokens])
    cand = _resolve_single(engine, candidate_q, profile)
    if cand.cards and (cand.cards[0] != left_first or len(cand.cards) > 1):
        return cand
    return direct


def _fmt_rub(value):
    n = int(round(value)) if float(value).is_integer() else round(value, 2)
    return f"{n:,}".replace(",", " ") + " ₽"


def _fmt_term(offer):
    if offer.get("model") == "perpetual":
        return "Бессрочная"
    tm = offer.get("term_months")
    if tm:
        if tm % 12 == 0:
            years = tm // 12
            return f"{years} г." if years > 1 else "12 мес."
        return f"{tm} мес."
    return "Не указан"


def _fmt_license_type(offer):
    parts = []
    model = MODEL_LABELS.get(offer.get("model"))
    if model:
        parts.append(model)
    metric = METRIC_LABELS.get(offer.get("metric"))
    if metric:
        parts.append(metric)
    return ", ".join(parts) if parts else "Не указан"


def _card_fact_snippet(card):
    parts = []
    if card.get("price_from") is not None and card["price_from"] > 0:
        parts.append(f"от {_fmt_rub(card['price_from'])}")
    elif card.get("offer", {}).get("price"):
        parts.append(f"от {_fmt_rub(card['offer']['price'])}")
    offer = card.get("offer") or {}
    term = _fmt_term(offer)
    if term != "Не указан":
        parts.append(f"срок: {term.lower()}")
    lic = _fmt_license_type(offer)
    if lic != "Не указан":
        parts.append(lic.lower())
    return f"{card['title']} ({', '.join(parts)})" if parts else card["title"]


def _compare_rows(columns):
    rows = [
        dict(title="Производитель", values=[c["vendor"]["name"] or "Не указан" for c in columns]),
        dict(
            title="Цена от",
            values=[
                f"от {_fmt_rub(c['price_from'])}" if (c.get("price_from") or 0) > 0
                else (f"от {_fmt_rub(c['offer']['price'])}" if (c.get("offer", {}).get("price") or 0) > 0 else "Цена по запросу")
                for c in columns
            ],
        ),
        dict(title="Срок", values=[_fmt_term(c.get("offer") or {}) for c in columns]),
        dict(title="Тип лицензии", values=[_fmt_license_type(c.get("offer") or {}) for c in columns]),
    ]
    return rows


def search(engine, req, profile, trace, priorities, record, norm):
    """Обработать запрос на сравнение двух продуктов в фиде. Возвращает ответ или None."""
    if req.verbatim or req.category:
        return None
    parsed = parse_compare(norm)
    if not parsed:
        return None
    left_raw, right_raw, explicit = parsed
    index = engine.catalog.feed

    left = _resolve_single(engine, left_raw, profile)
    right = _expand_right(engine, left_raw, right_raw, left, profile)

    # Если это не явное сравнение (просто «или»), обе стороны должны быть осмысленными (в фиде или известные аналоги)
    left_known = bool(left.cards or left.analog_row)
    right_known = bool(right.cards or right.analog_row)
    if not explicit and not (left_known and right_known):
        return None
    if not left_known and not right_known:
        return None

    from .feed import display, finish
    from . import feed_analogs

    sid = "s_" + uuid4().hex

    # Случай 1: обе стороны есть в фиде
    if left.cards and right.cards:
        cid_a = left.cards[0]
        cid_b = next((c for c in right.cards if c != cid_a), None)
        if cid_b is None:
            cid_b = next((c for c in (*right.neighbors, *left.neighbors) if c != cid_a), None)
        if cid_b is None:
            return None

        card_a = display(engine, cid_a, profile)
        card_b = display(engine, cid_b, profile)
        columns = [card_a, card_b]

        # Первые две карточки — лучшие представители обеих сторон, далее соседние редакции тех же линеек (>= 4 шт.)
        seen = {cid_a, cid_b}
        extra_ids = []
        pool_a = [c for c in (*left.cards[1:], *left.neighbors) if c not in seen]
        pool_b = [c for c in (*right.cards[1:], *right.neighbors) if c not in seen]
        max_len = max(len(pool_a), len(pool_b), 0)
        for i in range(max_len):
            for pool in (pool_a, pool_b):
                if i < len(pool) and pool[i] not in seen:
                    seen.add(pool[i])
                    extra_ids.append(pool[i])
                if len(extra_ids) >= 6:
                    break
            if len(extra_ids) >= 6:
                break

        # Если всё ещё меньше 4 карточек, добираем из разделов сторон
        if len(seen) < 4:
            for anchor_cid in (cid_a, cid_b):
                sec = index.card_sections.get(anchor_cid)
                for cid in index.groups.get(sec, ()):
                    if cid not in seen:
                        seen.add(cid)
                        extra_ids.append(cid)
                    if len(seen) >= 4:
                        break
                if len(seen) >= 4:
                    break

        items = [card_a, card_b]
        for cid in extra_ids:
            card = display(engine, cid, profile)
            card.update(fill=True, label="Соседняя редакция линейки")
            items.append(card)
        for pos, card in enumerate(items, 1):
            card["position"] = pos

        note = (
            f"Сравниваем {card_a['title']} и {card_b['title']}. "
            f"{_card_fact_snippet(card_a)}; {_card_fact_snippet(card_b)}."
        )
        trace.add("intent", "Сравнение", f"{card_a['title']} vs {card_b['title']}")
        trace.add("retrieve", "Поиск по фиду", "Сравниваемые продукты", candidates=len(items))

        blocks = [
            dict(type="compare", title="Сравнение программ", columns=columns, rows=_compare_rows(columns)),
            dict(type="products", title="Сравниваемые продукты", items=items, total=len(items)),
        ]
        chips = [dict(key="compare", label=f"Сравнение: {card_a['title']} и {card_b['title']}", removable=False)]
        result = dict(
            search_id=sid, engine="kuznitsa", engine_version="1.0", mode=req.mode,
            query=dict(raw=req.q, normalized=norm, corrected=norm, corrections=[], did_you_mean=None),
            understood=dict(
                intent="compare", intent_title=TITLES["compare"], intent_conf=0.95, intent_source="rules",
                filters={}, exclude={}, qty=None, entities=[], chips=chips, zero_reason=None, agent_note=note,
            ),
            blocks=blocks, facets=[], notes=[], banners=[], relax_hints=[], related_queries=[],
            profile=profile_info(profile), cost=cost_summary([], engine.usd_rub), trace=trace.steps, timing_ms={},
        )
        return finish(engine, req, trace, record, result, items, len(items), [])

    # Случай 2: одна сторона есть в фиде, второй нет («сравнить dr.web и eset»)
    present = left if left.cards else right
    absent = right if left.cards else left
    absent_name = (absent.analog_row["names"][0] if absent.analog_row else absent.raw).strip()

    present_ids = list(present.cards[:3])
    seen = set(present_ids)
    present_items = []
    for cid in present_ids:
        card = display(engine, cid, profile)
        present_items.append(card)

    # Подбираем аналоги отсутствующей стороны
    analog_cids = []
    if absent.analog_row:
        sections, seeds = feed_analogs.row_candidates(index, absent.analog_row)
        choices = feed_analogs.choose(index, normalize(absent_name), absent.analog_row, sections, seeds, [], False)
        analog_cids = [cid for cid, _ in choices if cid not in seen][:4]
    if not analog_cids and present_ids:
        sec = index.card_sections.get(present_ids[0])
        present_vendor = index.cat.cards[present_ids[0]].vendor
        analog_cids = [
            cid for cid in index.groups.get(sec, ())
            if cid not in seen and index.cat.cards[cid].vendor != present_vendor
        ][:4]

    analog_items = []
    for cid in analog_cids:
        seen.add(cid)
        card = display(engine, cid, profile)
        reason = f"Аналог {absent_name}"
        card.update(fill=True, label=reason, reason=reason)
        analog_items.append(dict(card=card, reason=reason))

    # Если всего карточек меньше 4, добавим ещё карточек найденной стороны
    if len(present_items) + len(analog_items) < 4:
        for cid in (*present.cards[3:], *present.neighbors):
            if cid not in seen:
                seen.add(cid)
                present_items.append(display(engine, cid, profile))
            if len(present_items) + len(analog_items) >= 4:
                break

    for pos, card in enumerate(present_items, 1):
        card["position"] = pos

    present_title = present_items[0]["title"]
    note = (
        f"«{absent_name}» нет в каталоге — сравнение возможно только с доступными аналогами. "
        f"Ниже {_card_fact_snippet(present_items[0])} и аналоги {absent_name}."
    )
    trace.add("intent", "Сравнение", f"{present_title} и {absent_name} (нет в каталоге)")
    trace.add("retrieve", "Поиск по фиду", note, candidates=len(present_items) + len(analog_items))

    blocks = [
        dict(type="products", title=f"Продукты: {present.raw}", items=present_items, total=len(present_items)),
    ]
    if analog_items:
        blocks.append(dict(type="analogs", title=f"Аналоги {absent_name} в каталоге", items=analog_items))

    chips = [dict(key="compare", label=f"Сравнение: {present.raw} и {absent_name}", removable=False)]
    all_items = present_items + [x["card"] for x in analog_items]
    result = dict(
        search_id=sid, engine="kuznitsa", engine_version="1.0", mode=req.mode,
        query=dict(raw=req.q, normalized=norm, corrected=norm, corrections=[], did_you_mean=None),
        understood=dict(
            intent="compare", intent_title=TITLES["compare"], intent_conf=0.9, intent_source="rules",
            filters={}, exclude={}, qty=None, entities=[], chips=chips, zero_reason=None, agent_note=note,
        ),
        blocks=blocks, facets=[], notes=[], banners=[], relax_hints=[], related_queries=[],
        profile=profile_info(profile), cost=cost_summary([], engine.usd_rub), trace=trace.steps, timing_ms={},
    )
    return finish(engine, req, trace, record, result, all_items, len(all_items), [])
