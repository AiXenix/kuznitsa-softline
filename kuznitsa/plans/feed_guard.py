"""Проверка правды о наличии, защита от разрушительных исправлений и чистые ответы на мусор."""
import re
from uuid import uuid4

from kuznitsa.index.feed import QUESTION, STOP, words
from kuznitsa.index.feed_analogs import key as analog_key
from kuznitsa.index.feed_language import sold_as
from kuznitsa.llm.recovery import cost_summary
from kuznitsa.plans.presentation import profile_info
from kuznitsa.plans.response_guard import COLLECTION
from kuznitsa.text import normalize, tokens
from kuznitsa.understand.intent import TITLES
from kuznitsa.understand.repair import LAYOUT
from kuznitsa.understand.spell_index import cyrillic, roman
from . import feed_analogs
from .feed_noise import (
    EDITION_ONLY_WORDS,
    FEED_COMPLEX,
    GARBAGE_NOTE,
    _clean_spaces,
    extract_conditions_and_noise,
    is_garbage_syntax,
    load_colloquial_kb,
    load_relax_synonyms,
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


def ensure_analog_bindings(index) -> None:
    """Чинит привязки feed_analogs, когда в снимке заголовок карточки без префикса вендора (например, Платформа nanoCAD)."""
    analogs = getattr(index, "analogs", None)
    if not analogs or getattr(analogs, "_n1_repaired", False):
        return
    titles = [
        (cid, analog_key(card.title), analog_key(card.offers[0].vendor or ""))
        for cid, card in index.cat.cards.items()
    ]
    changed_domestic = False
    for _ident, (_sections, targets) in analogs.bound.items():
        for i, (target, matches) in enumerate(targets):
            if matches:
                continue
            v_key = analog_key(target.get("vendor", ""))
            t_words = analog_key(target["title"]).split()
            if not v_key or len(t_words) < 2:
                continue
            v_words = set(v_key.split())
            new_matches: list[str] = []
            for drop in range(1, min(4, len(t_words))):
                dropped = t_words[:drop]
                # Снимаем ведущие слова только если они действительно относятся к имени вендора.
                if not all(
                    dw in v_words or any(vw.startswith(dw[:4]) or dw.startswith(vw[:4]) for vw in v_words if len(vw) >= 4 and len(dw) >= 4)
                    for dw in dropped
                ):
                    break
                sub = " ".join(t_words[drop:])
                if len(sub) < 3:
                    continue
                found = [cid for cid, name, brand in titles if sub in name and brand == v_key]
                if found:
                    new_matches = found
                    break
            if new_matches:
                targets[i] = (target, new_matches)
                if target.get("russian"):
                    analogs.declared_domestic.update(new_matches)
                    changed_domestic = True
    if changed_domestic:
        analogs.domestic = analogs.declared_domestic.union(analogs.registered)
    analogs._n1_repaired = True


def lookup_analog(index, text: str, *, fuzzy: bool = True) -> dict | None:
    """Поиск записи аналогов с починкой привязок, учётом разговорного словаря и уникального ядра названия."""
    ensure_analog_bindings(index)
    row = index.analogs.lookup(text, fuzzy=fuzzy)
    if row:
        return row
    spoken, _ = load_colloquial_kb()
    s = _clean_spaces(normalize(text))
    mapped = spoken.get(s)
    if mapped:
        row = index.analogs.lookup(mapped, fuzzy=fuzzy)
        if row:
            return row
    k = analog_key(text)
    if k and " " not in k and len(k) >= 5:
        hits = [
            r
            for r in index.analogs.rows.values()
            if any(k in analog_key(alias).split() for alias in r.get("names", ()))
        ]
        if len(hits) == 1:
            return hits[0]
    return None


def search_import_sub_analog(
    engine,
    req,
    profile,
    trace,
    priorities,
    record,
    norm: str,
    target: str,
    *,
    qty=None,
    budget=None,
) -> dict | None:
    """Маршрутизирует «импортозамещение <продукт>» в российские аналоги конкретного продукта."""
    index = engine.catalog.feed
    row = lookup_analog(index, target, fuzzy=True)
    if not row:
        return None
    req_ru = req.model_copy(update={"q": f"российский аналог {target}"})
    result = feed_analogs.search(
        engine, req_ru, profile, trace, priorities, record, target, row,
        explicit=True, qty=qty, budget=budget,
    )
    if result is not None:
        result["query"]["raw"] = req.q
        result["query"]["normalized"] = norm
    return result


def resolve_colloquial_product(engine, text: str, *, segment=None) -> tuple[list[str], str, str] | None:
    """Разрешает разговорное название продукта по словарю kb/feed_colloquial_n1.yaml с обязательной проверкой по FeedIndex."""
    index = engine.catalog.feed
    spoken, _ = load_colloquial_kb()
    s = _clean_spaces(normalize(text))
    if not s or s not in spoken:
        return None
    target_norm = _clean_spaces(normalize(spoken[s]))
    if not target_norm:
        return None
    cids = index.products(target_norm, fuzzy=False, segment=segment)
    target_words = set(words(target_norm))
    exact_title = [
        cid for cid in cids if target_words and target_words <= set(words(index.cat.cards[cid].title))
    ]
    if exact_title:
        confirmed = exact_title
    else:
        ed = index.edition(target_norm)
        if ed:
            return list(ed.cards), ed.query, ed.note
        confirmed = [cid for cid in cids if sold_as(index.cat.cards[cid], target_norm)]
    if not confirmed:
        return None

    def rank(cid: str):
        title = index.cat.cards[cid].title
        t_norm = normalize(title)
        is_kit = bool(re.match(r"^(?:комплект\w*|сертификат\w*|набор\w*)\b", t_norm))
        is_course = bool(re.search(r"\b(?:express\s+course|курс|обучен|тренинг)\b", t_norm))
        exact_prefix = t_norm.startswith(target_norm)
        return (not is_kit, not is_course, exact_prefix, index.quality.get(cid, (0,)), cid)

    ordered = sorted(dict.fromkeys(confirmed), key=rank, reverse=True)
    return ordered, target_norm, ""


_VENDOR_CONTEXT_RE = re.compile(
    r"\b(?:для|дома|дом|бизнес\w*|организац\w*|малого|linux|mac|macos|android|ios|сервер\w*|server)\b",
    re.I,
)


def _resolve_direct_vendor(index, text: str) -> str | None:
    """Находит вендора только по точному имени или однозначному префиксу в index.vendor_names (не по названиям продуктов)."""
    norm = _clean_spaces(normalize(text))
    if not norm:
        return None
    candidates = [norm, " ".join(words(norm))]
    if re.search("[а-я]", norm):
        candidates.append(roman(norm))
    if re.fullmatch("[a-z0-9 ]+", norm):
        candidates.append(" ".join(words(cyrillic(norm))))
    for key in candidates:
        if key and key in index.vendor_names:
            return index.vendor_names[key]
    for key in candidates:
        kw = words(key) if key else ()
        if not kw:
            continue
        pref_vids = {
            v
            for name, v in index.vendor_names.items()
            if words(name)[:len(kw)] == kw
        }
        if len(pref_vids) == 1:
            return next(iter(pref_vids))
    return None


def prefer_flagships_for_vendor(index, engine, q: str, ids: list[str], *, norm: str = "") -> list[str]:
    """Для запроса по имени вендора (например, «corel», «код безопасности») поднимает флагманские линейки выше вспомогательных."""
    if not ids or len(words(q)) > 2:
        return ids
    if norm and _VENDOR_CONTEXT_RE.search(norm):
        return ids
    vid = _resolve_direct_vendor(index, q)
    if not vid:
        return ids
    top = index.cat.cards[ids[0]]
    asked = set(words(q))
    # Запрос называет линейку («3ds max», «revit»), а не вендора: её карточки идут раньше прочих флагманов вендора.
    by_line = asked <= set(words(top.title)) and not asked <= set(words(top.vendor or ""))

    def named(cid):
        return by_line and asked <= set(words(index.cat.cards[cid].title))

    ranks = index.flagships.rank
    pool = list(ids)
    seen = set(pool)
    for cid in index.language.vendor_cards.get(vid, ()):
        if cid not in seen and ranks.get(cid, 0) > 0 and (not by_line or named(cid)):
            pool.append(cid)
            seen.add(cid)
    if not any(index.card_vendors.get(cid) == vid and ranks.get(cid, 0) > 0 for cid in pool):
        return ids
    return sorted(
        pool,
        key=lambda cid: (
            named(cid),
            index.card_vendors.get(cid) == vid and ranks.get(cid, 0) > 0,
            ranks.get(cid, 0) if index.card_vendors.get(cid) == vid else 0,
        ),
        reverse=True,
    )


_PUNCT_LAYOUT_KEEP = (frozenset(), frozenset({"."}), frozenset({","}), frozenset({".", ","}))
_RELAX_SKIP_QUERY_RE = re.compile(r"(?:^(?:софт|программ\w*|по)\s+для\s+|\b(?:обучени\w*|курс\w*|переход\w*|миграци\w*|услуг\w*|аудит\w*|техподдержк\w*)\b)", re.I)
_RELAX_GENERIC_WORDS = frozenset({
    "софт", "программа", "программы", "программ", "программное", "обеспечение",
    "приложение", "приложения", "система", "системы", "средство", "средства",
    "инструмент", "инструменты", "сервис", "сервисы", "решение", "решения",
    "лицензия", "лицензии", "версия", "версии", "пакет", "пакеты",
    "офис", "офиса", "офисный", "бизнес", "бизнеса", "малого", "малый",
    "компания", "компании", "организация", "организации", "работа", "работы",
    "отдел", "отдела", "юрист", "юриста", "кадры", "кадров", "бухгалтер", "бухгалтера",
    "купить", "цена", "нужен", "нужна", "нужны", "подобрать", "выбрать",
    "хороший", "лучший", "новый", "современный", "российский", "отечественный",
    "рабочих", "мест", "места", "место", "штук", "шт", "год", "года", "лет",
    "месяц", "месяцев", "пк", "компьютер", "компьютеров", "устройств", "пользователей",
    "гигабит", "гигабитный", "двухдиапазонный", "беспроводной", "проводной",
    "hdmi", "usb", "wifi", "wi", "fi", "ddr4", "ddr5", "ssd", "hdd",
    "гб", "gb", "тб", "tb", "мб", "mb", "см", "мм", "м", "вт", "w", "ггц", "ghz",
}) | STOP | EDITION_ONLY_WORDS


def _damerau_dist(a: str, b: str, max_d: int = 2) -> int:
    """Ограниченное расстояние Дамерау-Левенштейна (с транспозициями)."""
    la, lb = len(a), len(b)
    if abs(la - lb) > max_d:
        return max_d + 1
    if a == b:
        return 0
    prev2 = None
    prev1 = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        ai = a[i - 1]
        row_min = i
        for j in range(1, lb + 1):
            cost = 0 if ai == b[j - 1] else 1
            val = min(prev1[j] + 1, curr[j - 1] + 1, prev1[j - 1] + cost)
            if i > 1 and j > 1 and ai == b[j - 2] and a[i - 2] == b[j - 1]:
                val = min(val, prev2[j - 2] + 1)
            curr[j] = val
            if val < row_min:
                row_min = val
        if row_min > max_d:
            return max_d + 1
        prev2, prev1 = prev1, curr
    return prev1[lb]


def _feed_title_vocab(index) -> set[str]:
    vocab = getattr(index, "_n1_title_vocab", None)
    if vocab is None:
        vocab = set()
        for card in index.cat.cards.values():
            for w in words(card.title):
                if len(w) >= 3:
                    vocab.add(w)
        setattr(index, "_n1_title_vocab", vocab)
    return vocab


def _layout_variants_with_punct(raw_q: str) -> list[str]:
    """Варианты смены раскладки, пробуя '.' и ',' как буквы ('ю'/'б') и как буквальные знаки."""
    s = raw_q.strip().lower()
    if not s or not any(c in s for c in ".,"):
        return []
    if not re.search(r"[a-zа-яё]", s):
        return []
    out: list[str] = []
    seen = {s}
    for keep in _PUNCT_LAYOUT_KEEP:
        chars = [ch if ch in keep else ch.translate(LAYOUT) for ch in s]
        cand = "".join(chars)
        if cand not in seen and re.search(r"[a-zа-яё]", cand):
            seen.add(cand)
            out.append(cand)
    # Смешанные названия с точкой (например «fcghj.cloud» -> «аспро.cloud»): переводим только части вне раскладки.
    if "." in s:
        parts = s.split(".")
        if len(parts) == 2 and all(parts):
            for idx_p in (0, 1):
                alt = list(parts)
                alt[idx_p] = parts[idx_p].translate(LAYOUT)
                cand = ".".join(alt)
                if cand not in seen:
                    seen.add(cand)
                    out.append(cand)
    return out


def _repair_dotted_or_multiword_typo(index, text: str) -> tuple[list[str], str] | None:
    """Исправляет опечатки в названиях с точкой или из нескольких слов по реальному словарю заголовков фида."""
    raw = text.strip().lower()
    has_dot = "." in raw
    parts = [w for w in re.split(r"[.\s]+", normalize(raw)) if w]
    if len(parts) < 2 or len(parts) > 5:
        return None
    # Быстрая проверка прямого совпадения после разделения по точке.
    joined = " ".join(parts)
    direct = index.products(joined, fuzzy=False)
    if direct and all(w in set(words(index.cat.cards[direct[0]].title)) for w in parts):
        return list(direct), joined

    known_indices = [i for i, p in enumerate(parts) if p in index.postings]
    unknown_indices = [i for i, p in enumerate(parts) if p not in index.postings]
    if not unknown_indices:
        return None

    # Случай A: часть слов известна в фиде — ищем опечатку среди слов, реально встречающихся в тех же карточках.
    if known_indices:
        pool = None
        for i in known_indices:
            cids = set(index.postings.get(parts[i], ()))
            pool = cids if pool is None else (pool & cids)
        if not pool and len(known_indices) > 1:
            pool = set()
            for i in known_indices:
                pool.update(index.postings.get(parts[i], ()))
        if pool:
            co_words: set[str] = set()
            for cid in pool:
                for w in words(index.cat.cards[cid].title):
                    if len(w) >= 3:
                        co_words.add(w)
            fixed = list(parts)
            changed = False
            for i in unknown_indices:
                u = parts[i]
                if len(u) < 3:
                    continue
                max_d = 1 if len(u) <= 5 else 2
                best_w, best_d = None, max_d + 1
                for w in co_words:
                    if abs(len(w) - len(u)) > max_d:
                        continue
                    if not (u[0] == w[0] or (len(u) >= 2 and len(w) >= 2 and u[:2] == w[1] + w[0])):
                        continue
                    d = _damerau_dist(u, w, max_d)
                    if d < best_d:
                        best_d, best_w = d, w
                if best_w:
                    fixed[i] = best_w
                    changed = True
            if changed:
                repaired = " ".join(fixed)
                hits = index.products(repaired, fuzzy=False)
                if hits and all(w in set(words(index.cat.cards[hits[0]].title)) for w in fixed):
                    return list(hits), repaired

    # Случай B: точка внутри короткого 2-словного названия, где обе части с опечаткой (например «sprie.dco»).
    if has_dot and len(parts) == 2 and all(len(p) >= 3 for p in parts):
        vocab = _feed_title_vocab(index)
        cands_per_part: list[list[str]] = []
        for p in parts:
            opts = [p] if p in vocab else []
            if not opts:
                for w in vocab:
                    if abs(len(w) - len(p)) > 1:
                        continue
                    if not (p[0] == w[0] or (len(p) >= 2 and len(w) >= 2 and p[:2] == w[1] + w[0])):
                        continue
                    if _damerau_dist(p, w, 1) <= 1:
                        opts.append(w)
                        if len(opts) >= 8:
                            break
            if not opts:
                return None
            cands_per_part.append(opts)
        for w1 in cands_per_part[0]:
            for w2 in cands_per_part[1]:
                repaired = f"{w1} {w2}"
                hits = index.products(repaired, fuzzy=False)
                if hits and {w1, w2} <= set(words(index.cat.cards[hits[0]].title)):
                    return list(hits), repaired
    return None


def _build_recovered_products_result(
    engine, req, profile, trace, priorities, record, norm: str, cids: list[str], repaired_q: str, kind: str
) -> dict:
    from .feed import display, finish

    index = engine.catalog.feed
    cids = prefer_software_over_courses(index, repaired_q, prefer_suite_for_office_year(index, repaired_q, cids))
    start = (req.page - 1) * req.page_size
    items = [display(engine, cid, profile) for cid in cids[start:start + req.page_size]]
    for i, c in enumerate(items, 1):
        c["position"] = i
    title = TITLES["product"]
    trace.add("repair", "Восстановление написания", f"{req.q} -> {repaired_q} ({kind})")
    result = dict(
        search_id="s_" + uuid4().hex,
        engine="kuznitsa",
        engine_version="1.0",
        mode=req.mode,
        query=dict(
            raw=req.q,
            normalized=norm,
            corrected=repaired_q,
            corrections=[dict(original=req.q, corrected=repaired_q, kind=kind)],
            did_you_mean=repaired_q if repaired_q != norm else None,
        ),
        understood=dict(
            intent="product",
            intent_title=title,
            intent_conf=0.9,
            intent_source="rules",
            filters={},
            exclude={},
            qty=None,
            entities=[],
            chips=[],
            zero_reason=None,
            agent_note=title,
        ),
        blocks=[dict(type="products", title=title, category_id=None, total=len(cids), items=items)],
        facets=[],
        notes=[],
        banners=[],
        relax_hints=[],
        related_queries=[],
        profile=profile_info(profile),
        cost=cost_summary([], engine.usd_rub),
        trace=trace.steps,
        timing_ms={},
    )
    return finish(engine, req, trace, record, result, items, len(cids), [], profile=profile)


def recover_dotted_or_layout(
    engine, req, profile, trace, priorities, record, norm: str, base: str, *, qty=None, budget=None
) -> dict | None:
    """Перед объявлением товара отсутствующим проверяет раскладку с точкой/запятой и опечатки по словарю фида."""
    if req.verbatim or req.category or (req.filters.keys() - {"price_max"}):
        return None
    index = engine.catalog.feed
    # 1. Смена раскладки для названий с '.' или ',' внутри (пробуем знак и как букву, и как знак).
    for cand in _layout_variants_with_punct(req.q):
        cn = _clean_spaces(normalize(cand))
        if not cn:
            continue
        # Прямой поиск в фиде
        hits = index.products(cn, fuzzy=False, segment=profile.segment)
        cn_words = set(words(cn))
        if hits and cn_words and cn_words <= set(words(index.cat.cards[hits[0]].title)):
            return _build_recovered_products_result(engine, req, profile, trace, priorities, record, norm, list(hits), cn, "layout")
        # Разговорное название (например, «lh.dt,» -> «др.веб» -> Dr.Web)
        col = resolve_colloquial_product(engine, cn, segment=profile.segment)
        if col:
            cids, rq, _ = col
            return _build_recovered_products_result(engine, req, profile, trace, priorities, record, norm, cids, rq, "layout")
        # Известный отсутствующий бренд с точкой в другой раскладке (например, «rjyneh.lbfljr» -> «контур.диадок»)
        row = lookup_analog(index, cn, fuzzy=False)
        if row and not row.get("in_catalog"):
            return feed_analogs.search(
                engine, req, profile, trace, priorities, record, cn, row, explicit=False, qty=qty, budget=budget
            )
        # Раскладка + опечатка
        repaired = _repair_dotted_or_multiword_typo(index, cand)
        if repaired:
            cids, rq = repaired
            return _build_recovered_products_result(engine, req, profile, trace, priorities, record, norm, cids, rq, "layout")

    # 2. Название с точкой или несколькими словами + опечатка (например, «контур.тлок», «dr.web secruity space»).
    for candidate_src in (req.q, base):
        repaired = _repair_dotted_or_multiword_typo(index, candidate_src)
        if repaired:
            cids, rq = repaired
            return _build_recovered_products_result(engine, req, profile, trace, priorities, record, norm, cids, rq, "typo")
    return None


def prefer_requested_version(index, q: str, ids: list[str]) -> list[str]:
    """Если в запросе указано конкретное числовое поколение (windows 10, office 2019), поднимает карточки этой версии."""
    if not ids or len(ids) < 2:
        return ids
    norm = _clean_spaces(normalize(q))
    m = re.search(r"\b(10|11|201[69]|202[1-6])\b", norm)
    if not m:
        return ids
    ver = m[1]
    head = _clean_spaces(re.sub(r"\b" + re.escape(ver) + r"\b", " ", norm))
    if not head:
        return ids
    has_ver = [cid for cid in ids if ver in words(normalize(index.cat.cards[cid].title)) and sold_as(index.cat.cards[cid], head)]
    if not has_ver:
        return ids
    return sorted(
        ids,
        key=lambda cid: (
            ver in words(normalize(index.cat.cards[cid].title)) and sold_as(index.cat.cards[cid], head),
            ver in words(normalize(index.cat.cards[cid].title)),
        ),
        reverse=True,
    )


def _find_hardware_section(index, hw_name: str) -> str | None:
    device = index.hardware.get(hw_name)
    if device:
        sec = next((str(k) for k in device.get("hardware_feed_classes", ()) if str(k) in index.groups), None)
        if sec:
            return sec
    hw_words = set(words(hw_name))
    choices = [
        k
        for k, v in index.classes.items()
        if k in index.groups
        and (hw_words & set(words(v)))
        and index.cat.cards[index.groups[k][0]].offers[0].domain == "hardware"
    ]
    return min(choices, key=lambda k: len(index.classes[k])) if choices else None


def _boost_by_query_tokens(index, cids: list[str], extra_tokens: list[str]) -> list[str]:
    if not extra_tokens or len(cids) < 2:
        return cids

    def score(cid: str) -> int:
        t = normalize(index.cat.cards[cid].title)
        tw = set(words(t))
        hits = 0
        for tok in extra_tokens:
            if tok in tw or (len(tok) >= 2 and tok in t):
                hits += 1
        return hits

    if not any(score(cid) > 0 for cid in cids):
        return cids
    return sorted(cids, key=score, reverse=True)


def _try_relax_query(engine, index, norm: str, base: str, *, segment=None) -> tuple[list[str], str | None, str] | None:
    """Ослабление несовпавшего запроса: синоним класса -> самое длинное известное подвыражение -> класс/железо по слову."""
    from kuznitsa.index.hardware import hardware_head

    if _RELAX_SKIP_QUERY_RE.search(norm):
        return None
    base_clean = _clean_spaces(normalize(base))
    if not base_clean:
        return None
    bw = list(words(base_clean))
    if not bw:
        return None

    relax_syn = load_relax_synonyms()
    _SPEC_NUMS = frozenset({"16", "32", "64", "128", "256", "512", "1024", "2048", "4k", "8k"})
    extra_toks = [
        w for w in words(base_clean)
        if len(w) >= 2 and w not in STOP and (not w.isdigit() or w in _SPEC_NUMS)
    ]

    # 1. Точный синоним класса на всё выражение (например, «средства программирования» -> «программы для разработки по»).
    syn_target = relax_syn.get(base_clean)
    if syn_target:
        sec = index.class_by_name.get(syn_target) or index.class_match(syn_target)
        if sec and sec in index.groups:
            members = _boost_by_query_tokens(index, list(index.groups[sec]), extra_toks)
            return members, sec, base_clean

    if len(bw) < 2:
        return None

    # 2. Самое длинное известное подвыражение (от len-1 до 1): синоним класса -> железо -> класс -> разговорный продукт -> точный продукт.
    for length in range(len(bw) - 1, 0, -1):
        for i in range(len(bw) - length + 1):
            sub_words = bw[i:i + length]
            if all(w in _RELAX_GENERIC_WORDS or w.isdigit() for w in sub_words):
                continue
            sub = " ".join(sub_words)
            rem = [w for w in extra_toks if w not in sub_words]

            # 2a. Синоним класса/оборудования (например, «маршрутизатор», «кабель», «флешка», «роутер»)
            syn = relax_syn.get(sub)
            if syn:
                sec = index.class_by_name.get(syn) or index.class_match(syn)
                if sec and sec in index.groups:
                    sec_words = set(words(index.classes[sec]))
                    boost = [w for w in extra_toks if w not in sec_words]
                    members = _boost_by_query_tokens(index, list(index.groups[sec]), boost)
                    return members, sec, sub

            # 2b. Аппаратное слово (hardware_head)
            hw = hardware_head(index, sub)
            if hw:
                sec = _find_hardware_section(index, hw)
                if sec and sec in index.groups:
                    sec_words = set(words(index.classes[sec]))
                    boost = [w for w in extra_toks if w not in sec_words]
                    members = _boost_by_query_tokens(index, list(index.groups[sec]), boost)
                    return members, sec, sub

            # 2c. Класс/раздел фида
            sec = index.class_match(sub) or index.language.qualified_class(index, sub)
            if sec and sec in index.groups:
                members = _boost_by_query_tokens(index, list(index.groups[sec]), rem)
                return members, sec, sub

            # 2d. Разговорный продукт из словаря с проверкой по каталогу
            col = resolve_colloquial_product(engine, sub, segment=segment)
            if col:
                cids, _, _ = col
                return _boost_by_query_tokens(index, cids, rem), None, sub

            # 2e. Точный продукт в каталоге (для одиночного слова требуем длину >= 4 и не родовое слово)
            if length == 1 and (len(sub) < 4 or sub in _RELAX_GENERIC_WORDS):
                continue
            hits = index.products(sub, fuzzy=False, segment=segment)
            if hits:
                confirmed = [cid for cid in hits if sold_as(index.cat.cards[cid], sub)]
                if confirmed:
                    ordered = prefer_software_over_courses(index, sub, _boost_by_query_tokens(index, confirmed, rem))
                    return ordered, None, sub
    return None


def handle_unmatched_query(
    engine, req, profile, trace, record, norm: str, base: str, *, priorities=(), qty=None, budget=None
) -> dict | None:
    """Ослабляет несовпавший запрос по части выражения/классу/железу и закрывает уход оффтопа в старый конвейер."""
    from .feed import display, finish

    if (
        req.category
        or req.filters
        or req.exclude
        or req.sort
        or req.weights
        or req.verbatim
        or req.session_id
        or "\n" in req.q
    ):
        return None
    if FEED_COMPLEX.search(norm) or QUESTION.search(norm):
        return None
    index = engine.catalog.feed
    if norm in engine.catalog.source_codes or base in engine.catalog.source_codes:
        return None

    # 1. Пробуем ослабление по части запроса (самое длинное известное подвыражение / класс / hardware_head).
    relaxed = _try_relax_query(engine, index, norm, base, segment=profile.segment)
    if relaxed:
        cids, sec, matched_part = relaxed
        note = f"Показаны товары по части запроса: «{matched_part}»."
        trace.add("relax", "Ослабление запроса", note)
        start = (req.page - 1) * req.page_size
        items = [display(engine, cid, profile) for cid in cids[start:start + req.page_size]]
        for i, c in enumerate(items, 1):
            c["position"] = i
        intent = "category" if sec else "product"
        title = index.classes[sec] if sec else TITLES[intent]
        chips = []
        if sec:
            chips.append(dict(key="category", label=index.classes[sec], removable=False))
        if qty:
            chips.append(dict(key="quantity", label=f"Количество · {qty['value']}"))
        result = dict(
            search_id="s_" + uuid4().hex,
            engine="kuznitsa",
            engine_version="1.0",
            mode=req.mode,
            query=dict(raw=req.q, normalized=norm, corrected=norm, corrections=[], did_you_mean=None),
            understood=dict(
                intent=intent,
                intent_title=TITLES[intent],
                intent_conf=0.82,
                intent_source="rules",
                filters=dict(category=[sec]) if sec else {},
                exclude={},
                qty=qty,
                entities=[],
                chips=chips,
                zero_reason=None,
                relaxed_to=matched_part,
                agent_note=note,
            ),
            blocks=[dict(type="products", title=title, category_id=sec, total=len(cids), items=items)],
            facets=[],
            notes=[note],
            banners=[],
            relax_hints=[],
            related_queries=[],
            profile=profile_info(profile),
            cost=cost_summary([], engine.usd_rub),
            trace=trace.steps,
            timing_ms={},
        )
        return finish(engine, req, trace, record, result, items, len(cids), [], profile=profile)

    # 2. Если в запросе есть сущности KB (роль/услуга/миграция), уступаем соседним конвейерам; иначе чистый clarify без карточек.
    toks = tokens(norm)
    substantive_kinds = {"family", "vendor", "category", "role", "industry", "use_case", "compliance", "platform"}
    if toks and any(
        kind in substantive_kinds
        for _, _, matches in engine.lex.match(toks)
        for kind, _, _ in matches
    ):
        return None
    if index.products(base, fuzzy=False):
        return None
    result = build_garbage_result(engine, req, profile, trace, norm)
    return finish(engine, req, trace, record, result, [], 0, [], profile=profile)


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
            index.flagships.rank.get(cid, 0),
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
    # Если точное название с версией реально продаётся или поколение есть в заголовке — это не пропуск.
    direct = index.products(norm, fuzzy=False)
    if any(
        sold_as(index.cat.cards[cid], norm)
        or (ver in words(normalize(index.cat.cards[cid].title)) and sold_as(index.cat.cards[cid], head))
        for cid in direct
    ):
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
    """Единая лестница подтверждения товара в реальном фиде (редакция, словарь, аналоги in_catalog, КБ-алиасы, год, тир)."""
    if _depth > 5:
        return None
    index = engine.catalog.feed
    s = normalize_spoken_brands(" ".join(normalize(text).split()))
    if not s:
        return None

    # 0. Разговорное название продукта с проверкой по каталогу.
    colloquial = resolve_colloquial_product(engine, s, segment=segment)
    if colloquial:
        return colloquial

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
    row = lookup_analog(index, s, fuzzy=True)
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
    elif row and not row.get("in_catalog"):
        # Товар явно помечен как отсутствующий в каталоге — не подменяем его устаревшим алиасом KB (например, acronis -> cyber_backup).
        return None

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


def _prune_cross_section_fill(index, blocks: list[dict], understood: dict, page: int) -> None:
    """Убирает чужеродные fill-карточки из других разделов, когда в основном разделе продукта уже >= 3 карточек."""
    if page != 1 or understood.get("intent") != "product" or len(index.cat.cards) < 500:
        return
    for block in blocks:
        if block.get("type") != "products":
            continue
        items = block.get("items") or []
        real = [c for c in items if not c.get("fill") and c.get("kind") != "upsell"]
        if not real:
            continue
        anchor_sec = index.card_sections.get(real[0]["card_id"])
        if not anchor_sec:
            continue
        same_sec = [
            c
            for c in items
            if c.get("kind") != "upsell" and index.card_sections.get(c["card_id"]) == anchor_sec
        ]
        if len(same_sec) >= 3:
            pruned = [
                c
                for c in items
                if not (c.get("fill") and index.card_sections.get(c["card_id"]) != anchor_sec)
            ]
            if len(pruned) != len(items):
                for i, c in enumerate(pruned, 1):
                    c["position"] = i
                block["items"] = pruned
        break


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
    cids = prefer_flagships_for_vendor(
        index,
        engine,
        resolved_q,
        prefer_software_over_courses(index, resolved_q, prefer_suite_for_office_year(index, resolved_q, cids)),
    )
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

    # 0. Если линейка найдена в каталоге, но у предложений не размечен action=renewal (например, «продление криптопро»),
    # не объявляем товар отсутствующим в каталоге — показываем линейку с честным примечанием об уточнении продления.
    claims_absent = (
        any(b.get("type") == "not_in_catalog" for b in blocks)
        or understood.get("zero_reason") == "not_in_catalog"
        or understood.get("intent") == "out_of_catalog"
    )
    if (
        claims_absent
        and understood.get("filters", {}).get("action") == "renewal"
        and any(b.get("type") == "not_in_catalog" and b.get("reason") == "gap" for b in blocks)
    ):
        found_cards = [
            row["card"]
            for b in blocks
            if b.get("type") == "analogs"
            for row in (b.get("items") or ())
            if isinstance(row, dict) and row.get("card") and not row["card"].get("fill")
        ]
        if found_cards:
            for i, c in enumerate(found_cards, 1):
                c["position"] = i
            note = "Товары линейки найдены. Условия продления нужно уточнить у поставщика."
            other_blocks = [b for b in blocks if b.get("type") not in ("not_in_catalog", "analogs")]
            result["blocks"] = [
                dict(type="products", title=TITLES["renewal"], category_id=None, total=len(found_cards), items=found_cards),
                *other_blocks,
            ]
            understood.update(
                intent="renewal",
                intent_title=TITLES["renewal"],
                zero_reason=None,
                reason=None,
                agent_note=note,
            )
            _strip_empty_blocks(result["blocks"])
            return result

    # 1. Защита от ложного «нет в каталоге» (в том числе от старого vendor_left на реальном фиде).
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
        analog_row = lookup_analog(index, cleaned.subject, fuzzy=False)
        if analog_row and not analog_row.get("in_catalog"):
            # Товар явно отсутствует по карте аналогов: отменяем «нет» только если в фиде реально продаётся карточка с таким именем.
            direct = index.products(cleaned.subject, fuzzy=False, segment=profile.segment)
            confirmed = [cid for cid in direct if sold_as(index.cat.cards[cid], cleaned.subject)]
            resolved = (confirmed, cleaned.subject, "") if confirmed else None
        else:
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

        # 2.0. Отсутствующий бренд без известных аналогов из старого конвейера: убираем нерелевантные карточки-заполнители.
        if claims_absent and not any(b.get("type") == "analogs" for b in blocks):
            prod_cards = [
                c
                for b in blocks
                if b.get("type") == "products"
                for c in (b.get("items") or ())
            ]
            if prod_cards and not _has_lexical_grounding(engine, norm, prod_cards):
                blocks[:] = [b for b in blocks if b.get("type") not in ("products", "crosssell")]
                _strip_empty_blocks(blocks)
                return result

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

    _prune_cross_section_fill(index, blocks, understood, req.page)
    _strip_empty_blocks(blocks)
    return result
