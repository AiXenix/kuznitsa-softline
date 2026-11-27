"""Обработка параметров запроса (sort, filters, exclude, ignore, page) и групп уточнения (facets) на фиде."""
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from uuid import uuid4

from kuznitsa.index.feed import words
from kuznitsa.llm.recovery import cost_summary
from kuznitsa.plans.presentation import profile_info
from kuznitsa.text import normalize
from kuznitsa.understand.intent import TITLES
from . import feed_conditions, feed_guard

SUPPORTED_FILTERS = frozenset({"vendor", "category", "price_min", "price_max", "origin", "registry", "platform"})
SUPPORTED_EXCLUDE = frozenset({"vendor", "category"})
SUPPORTED_IGNORE = frozenset({
    "vendor", "category", "price_min", "price_max", "price", "sort",
    "exclude", "exclude_vendor", "exclude_category",
    "origin", "registry", "platform", "action", "profile", "refined", "context", "specs",
})

FILTER_LABELS = {
    "vendor": "Производитель",
    "category": "Раздел",
    "price_min": "Минимальная цена",
    "price_max": "Максимальная цена",
    "origin": "Российское ПО",
    "registry": "Из реестра ПО",
    "platform": "Платформа",
    "exclude_vendor": "Исключение производителя",
    "exclude_category": "Исключение раздела",
}


@dataclass(frozen=True)
class RequestPlan:
    text_cond: feed_conditions.Conditions
    cond: feed_conditions.Conditions
    vendors: tuple[str, ...] = ()
    vendor_ids: frozenset[str] | None = None
    categories: tuple[str, ...] = ()
    price_min: float | None = None
    price_max: float | None = None
    origin: str | None = None
    registry: bool = False
    platforms: tuple[str, ...] = ()
    exclude_vendors_raw: tuple[str, ...] = ()
    exclude_vendor_ids: frozenset[str] = frozenset()
    exclude_categories: tuple[str, ...] = ()
    sort: str | None = None
    explicit_sort: bool = False
    has_filters: bool = False
    ignore: frozenset[str] = frozenset()


def unsupported(req) -> bool:
    """Вернуть True, если запрос содержит параметры, не поддерживаемые планом фида."""
    if req.sort and req.sort not in ("price_asc", "price_desc"):
        return True
    if req.weights:
        return True
    if req.filters.keys() - SUPPORTED_FILTERS:
        return True
    if req.exclude.keys() - SUPPORTED_EXCLUDE:
        return True
    if {key for key in req.ignore if key not in SUPPORTED_IGNORE and not key.startswith("spec:")}:
        return True
    return False


def for_solution(req):
    """Копия запроса без параметров N7, чтобы resolve_solution находил ту же задачу."""
    if unsupported(req):
        return req
    if not (req.sort or req.filters or req.exclude or req.ignore):
        return req
    return req.model_copy(update={"sort": None, "filters": {}, "exclude": {}, "ignore": []})


def _vendor_lookup(index):
    cache = getattr(index, "_n7_vendor_lookup", None)
    if cache is not None:
        return cache
    id_exact: dict[str, str] = {}
    id_lower: dict[str, str] = {}
    name_lower: dict[str, set[str]] = defaultdict(set)
    name_norm: dict[str, set[str]] = defaultdict(set)
    name_words: dict[str, set[str]] = defaultdict(set)
    display_counts: dict[str, Counter] = defaultdict(Counter)
    for cid, card in index.cat.cards.items():
        vid = index.card_vendors.get(cid)
        if not vid:
            continue
        id_exact[vid] = vid
        id_lower[vid.casefold()] = vid
        if card.vendor:
            id_exact[card.vendor] = vid
            id_lower[card.vendor.casefold()] = vid
        raw_name = (card.offers[0].vendor or "").strip()
        if raw_name:
            name_lower[raw_name.casefold()].add(vid)
            norm_name = normalize(raw_name)
            if norm_name:
                name_norm[norm_name].add(vid)
            w_name = " ".join(words(raw_name))
            if w_name:
                name_words[w_name].add(vid)
            display_counts[vid][raw_name] += 1
    display_name = {
        vid: counts.most_common(1)[0][0]
        for vid, counts in display_counts.items()
    }
    cache = dict(
        id_exact=id_exact,
        id_lower=id_lower,
        name_lower=dict(name_lower),
        name_norm=dict(name_norm),
        name_words=dict(name_words),
        display_name=display_name,
    )
    index._n7_vendor_lookup = cache
    return cache


def resolve_vendors(index, engine, raw_values) -> frozenset[str]:
    """Привести коды или названия производителей (в любом регистре) к ключам index.card_vendors."""
    if not raw_values:
        return frozenset()
    lk = _vendor_lookup(index)
    resolved: set[str] = set()
    for raw in raw_values:
        s = str(raw).strip()
        if not s:
            continue
        exact = lk["id_exact"].get(s)
        if exact:
            resolved.add(exact)
            continue
        low = s.casefold()
        ci = lk["id_lower"].get(low)
        if ci:
            resolved.add(ci)
            continue
        by_name = lk["name_lower"].get(low)
        if by_name:
            resolved.update(by_name)
            continue
        norm_s = normalize(s)
        by_norm = lk["name_norm"].get(norm_s)
        if by_norm:
            resolved.update(by_norm)
            continue
        w_s = " ".join(words(s))
        by_words = lk["name_words"].get(w_s)
        if by_words:
            resolved.update(by_words)
            continue
        vn = index.vendor_names.get(norm_s) or (index.vendor_names.get(w_s) if w_s else None)
        if vn:
            resolved.add(vn)
            continue
        vids, _terms, _label = feed_conditions._resolve_exclude(index, engine, s)
        if vids:
            resolved.update(vids)
    return frozenset(resolved)


def _vendor_display(index, vid: str) -> str:
    lk = _vendor_lookup(index)
    return lk["display_name"].get(vid, vid)


def _vendor_labels(index, engine, raw_values) -> list[str]:
    lk = _vendor_lookup(index)
    labels = []
    for raw in raw_values:
        s = str(raw).strip()
        if not s:
            continue
        vids = resolve_vendors(index, engine, (s,))
        if len(vids) == 1:
            labels.append(lk["display_name"].get(next(iter(vids)), s))
        else:
            labels.append(s)
    return list(dict.fromkeys(labels))


def extract(engine, norm: str, req) -> RequestPlan:
    """Разобрать текстовые условия через feed_conditions.extract и сложить с параметрами Request."""
    index = engine.catalog.feed
    ignore = frozenset(req.ignore)
    text_only_req = req.model_copy(update={"filters": {}, "exclude": {}, "sort": None})
    text_cond = feed_conditions.extract(engine, norm, text_only_req)

    # Параметры фильтров с учётом ignore
    vendors: tuple[str, ...] = ()
    vendor_ids: frozenset[str] | None = None
    if req.filters.get("vendor") and "vendor" not in ignore:
        raw_v = req.filters["vendor"]
        vendors = tuple(raw_v if isinstance(raw_v, list) else [raw_v])
        vendor_ids = resolve_vendors(index, engine, vendors)

    categories: tuple[str, ...] = ()
    if req.filters.get("category") and "category" not in ignore:
        raw_c = req.filters["category"]
        categories = tuple(raw_c if isinstance(raw_c, list) else [raw_c])

    price_min: float | None = None
    if req.filters.get("price_min") is not None and "price_min" not in ignore and "price" not in ignore:
        price_min = float(req.filters["price_min"])

    price_max: float | None = None
    if req.filters.get("price_max") is not None and "price_max" not in ignore and "price" not in ignore:
        price_max = float(req.filters["price_max"])

    origin: str | None = None
    if req.filters.get("origin") and "origin" not in ignore:
        origin = str(req.filters["origin"])

    registry = bool(req.filters.get("registry") is True and "registry" not in ignore)
    if registry and not origin and "origin" not in ignore:
        origin = "russian"

    platforms: tuple[str, ...] = ()
    if req.filters.get("platform") and "platform" not in ignore:
        raw_p = req.filters["platform"]
        raw_p = raw_p if isinstance(raw_p, list) else [raw_p]
        platforms = tuple(
            dict.fromkeys(feed_conditions._canonical_platform(str(p)) or str(p).casefold().strip() for p in raw_p if str(p).strip())
        )

    exclude_vendors_raw: tuple[str, ...] = ()
    exclude_vendor_ids: frozenset[str] = frozenset()
    if req.exclude.get("vendor") and "exclude" not in ignore and "exclude_vendor" not in ignore:
        raw_ev = req.exclude["vendor"]
        exclude_vendors_raw = tuple(raw_ev if isinstance(raw_ev, list) else [raw_ev])
        exclude_vendor_ids = resolve_vendors(index, engine, exclude_vendors_raw)

    exclude_categories: tuple[str, ...] = ()
    if req.exclude.get("category") and "exclude" not in ignore and "exclude_category" not in ignore:
        raw_ec = req.exclude["category"]
        exclude_categories = tuple(raw_ec if isinstance(raw_ec, list) else [raw_ec])

    explicit_sort = bool(req.sort in ("price_asc", "price_desc") and "sort" not in ignore)
    eff_sort = req.sort if explicit_sort else text_cond.sort

    # Складываем условия текста и параметров в единый Conditions для совместимости с планом
    eff_pmin = text_cond.price_min
    if price_min is not None:
        eff_pmin = max(eff_pmin, price_min) if eff_pmin is not None else price_min
    eff_pmax = text_cond.price_max
    if price_max is not None:
        eff_pmax = min(eff_pmax, price_max) if eff_pmax is not None else price_max
    eff_origin = origin or text_cond.origin
    eff_registry = bool(registry or text_cond.registry)
    eff_platform = platforms[0] if len(platforms) == 1 else text_cond.platform

    has_filters = bool(
        vendors or categories or price_min is not None or price_max is not None
        or origin or registry or platforms or exclude_vendors_raw or exclude_categories
    )
    merged_cond = replace(
        text_cond,
        price_min=eff_pmin,
        price_max=eff_pmax,
        sort=eff_sort,
        origin=eff_origin,
        registry=eff_registry,
        platform=eff_platform,
        active=bool(text_cond.active or has_filters or explicit_sort),
    )

    return RequestPlan(
        text_cond=text_cond,
        cond=merged_cond,
        vendors=vendors,
        vendor_ids=vendor_ids,
        categories=categories,
        price_min=price_min,
        price_max=price_max,
        origin=origin,
        registry=registry,
        platforms=platforms,
        exclude_vendors_raw=exclude_vendors_raw,
        exclude_vendor_ids=exclude_vendor_ids,
        exclude_categories=exclude_categories,
        sort=eff_sort,
        explicit_sort=explicit_sort,
        has_filters=has_filters,
        ignore=ignore,
    )


def _match_categories(index, cid: str, cats_set: set[str], cats_norm: set[str]) -> bool:
    sec = index.card_sections.get(cid)
    if sec and sec in cats_set:
        return True
    card = index.cat.cards[cid]
    if card.category and card.category in cats_set:
        return True
    if sec and index.class_names.get(sec) in cats_norm:
        return True
    return False


def _filter_ids(index, engine, plan: RequestPlan, ids: list[str], *, skip_filter: str | None = None) -> list[str]:
    """Применить явные фильтры и исключения RequestPlan к списку карточек.

    skip_filter исключает один ключ фильтра (для расчёта фасетов без собственного фильтра).
    """
    if not ids:
        return []
    use_vendor = plan.vendor_ids is not None and skip_filter != "vendor"
    use_cat = bool(plan.categories) and skip_filter != "category"
    use_pmin = plan.price_min is not None and skip_filter != "price_min"
    use_pmax = plan.price_max is not None and skip_filter != "price_max"
    use_origin = bool(plan.origin) and skip_filter != "origin"
    use_registry = plan.registry and skip_filter != "registry"
    use_platform = bool(plan.platforms) and skip_filter != "platform"
    use_ex_vendor = bool(plan.exclude_vendors_raw) and skip_filter != "exclude_vendor"
    use_ex_cat = bool(plan.exclude_categories) and skip_filter != "exclude_category"

    if not (use_vendor or use_cat or use_pmin or use_pmax or use_origin or use_registry
            or use_platform or use_ex_vendor or use_ex_cat):
        return list(ids)

    eff_pmin = None
    if use_pmin:
        eff_pmin = plan.price_min
        if plan.text_cond.price_min is not None:
            eff_pmin = max(eff_pmin, plan.text_cond.price_min)
    eff_pmax = None
    if use_pmax:
        eff_pmax = plan.price_max
        if plan.text_cond.price_max is not None:
            eff_pmax = min(eff_pmax, plan.text_cond.price_max)

    if use_vendor and not plan.vendor_ids:
        return []
    if eff_pmin is not None and eff_pmax is not None and eff_pmin > eff_pmax:
        return []

    cats_set = set(plan.categories) if use_cat else set()
    cats_norm = {normalize(c) for c in plan.categories} if use_cat else set()
    ex_cats_set = set(plan.exclude_categories) if use_ex_cat else set()
    ex_cats_norm = {normalize(c) for c in plan.exclude_categories} if use_ex_cat else set()
    ex_vids = plan.exclude_vendor_ids if use_ex_vendor else frozenset()
    vids = plan.vendor_ids if use_vendor else None

    cards = index.cat.cards
    card_vendors = index.card_vendors
    out = []
    for cid in ids:
        if vids is not None:
            if card_vendors.get(cid) not in vids:
                continue
        if ex_vids:
            if card_vendors.get(cid) in ex_vids:
                continue
        if use_cat and not _match_categories(index, cid, cats_set, cats_norm):
            continue
        if use_ex_cat and _match_categories(index, cid, ex_cats_set, ex_cats_norm):
            continue
        card = cards[cid]
        if eff_pmin is not None or eff_pmax is not None:
            pf = card.price_from
            if pf is None:
                continue
            if eff_pmin is not None and pf < eff_pmin:
                continue
            if eff_pmax is not None and pf > eff_pmax:
                continue
        if use_registry:
            if cid not in index.analogs.registered and not any(o.registry for o in card.offers):
                continue
        if use_origin:
            is_dom = feed_conditions.is_domestic_card(index, engine.kb, engine, cid)
            if plan.origin == "russian" and not is_dom:
                continue
            if plan.origin == "foreign" and is_dom:
                continue
        if use_platform:
            if not any(feed_conditions._match_platform_offer(index, cid, p) is not None for p in plan.platforms):
                continue
        out.append(cid)
    return out


def _build_relax_hints(index, engine, req, plan: RequestPlan, base_ids: list[str]) -> list[dict]:
    active_keys = []
    if plan.vendors:
        active_keys.append(("vendor", "vendor"))
    if plan.categories:
        active_keys.append(("category", "category"))
    if plan.price_max is not None:
        active_keys.append(("price_max", "price_max"))
    if plan.price_min is not None:
        active_keys.append(("price_min", "price_min"))
    if plan.origin:
        active_keys.append(("origin", "origin"))
    if plan.registry:
        active_keys.append(("registry", "registry"))
    if plan.platforms:
        active_keys.append(("platform", "platform"))
    if plan.exclude_vendors_raw:
        active_keys.append(("exclude_vendor", "exclude"))
    if plan.exclude_categories:
        active_keys.append(("exclude_category", "exclude"))

    hints = []
    seen_drops = set()
    for internal_key, drop in active_keys:
        if drop in seen_drops:
            continue
        count = len(_filter_ids(index, engine, plan, base_ids, skip_filter=internal_key))
        if count > 0:
            seen_drops.add(drop)
            title = FILTER_LABELS.get(internal_key, internal_key)
            hints.append(dict(
                drop=drop,
                label=f"Снять условие «{title}»",
                count=count,
                apply=dict(ignore=list(dict.fromkeys([*req.ignore, drop]))),
            ))
    if not hints and active_keys and base_ids:
        all_drops = list(dict.fromkeys(drop for _, drop in active_keys))
        hints.append(dict(
            drop=all_drops[0],
            label="Снять все фильтры",
            count=len(base_ids),
            apply=dict(ignore=list(dict.fromkeys([*req.ignore, *all_drops]))),
        ))
    return hints


def sort_ids(index, ids: list[str], sort_dir: str | None) -> list[str]:
    """Отсортировать весь список карточек по price_from; карточки без цены в конце."""
    if sort_dir not in ("price_asc", "price_desc") or not ids:
        return list(ids)
    reverse = sort_dir == "price_desc"
    cards = index.cat.cards

    def key(cid):
        pf = cards[cid].price_from
        if pf is None:
            return (1, 0.0)
        return (0, -float(pf) if reverse else float(pf))

    return sorted(ids, key=key)


def prepare_page_offers(index, page_ids: list[str], plan: RequestPlan, profile, preferred: dict, selections: dict, qty, renewal):
    """Подобрать подходящее предложение внутри карточки для текущей страницы (цена / сортировка)."""
    cards = index.cat.cards
    has_price_filter = plan.price_min is not None or plan.price_max is not None
    if has_price_filter:
        pmin = plan.cond.price_min
        pmax = plan.cond.price_max
        for cid in page_ids:
            if cid in selections:
                continue
            sel = feed_conditions._pick_offer_in_range(cards[cid], profile, pmin, pmax, qty, renewal, plan.sort)
            if sel:
                selections[cid] = sel
    if plan.sort == "price_asc":
        for cid in page_ids:
            if cid in selections or cid in preferred:
                continue
            priced = [o for o in cards[cid].offers if o.price is not None]
            if priced:
                preferred[cid] = min(priced, key=lambda o: (not o.available, o.price))


def finish_items_sort(items: list[dict], sort_dir: str | None):
    """Сохранить строгий порядок по price_from после бизнес-правил мерчандайзинга."""
    if sort_dir not in ("price_asc", "price_desc") or not items:
        return
    rev = sort_dir == "price_desc"
    items.sort(key=lambda c: (
        c.get("price_from") is None,
        (-float(c["price_from"]) if rev else float(c["price_from"])) if c.get("price_from") is not None else 0.0,
    ))


def allow_upsell(req, plan: RequestPlan, items: list[dict]) -> bool:
    """Допродажи показываются только на первой странице, не при явной сортировке и не на пустом ответе."""
    return req.page == 1 and plan.sort not in ("price_asc", "price_desc") and bool(items)


def allow_fill(req, plan: RequestPlan) -> bool:
    """Добор похожих товаров отключён при фильтрах, исключениях, сортировке и на страницах > 1."""
    return req.page == 1 and not plan.has_filters and plan.sort not in ("price_asc", "price_desc")


def apply(engine, req, profile, plan: RequestPlan, ids, section, preferred, selections, qty, renewal, note):
    """Применить текстовые условия, фильтры/исключения параметров и сортировку по всему списку.

    Возвращает (ids, base_ids, section, note, relax_hints, price_relaxed).
    """
    index = engine.catalog.feed
    ids = list(ids)
    price_relaxed = False
    relax_hints: list[dict] = []

    # 1. Текстовые условия через существующий feed_conditions.apply_conditions (без сортировки — её делаем в конце).
    # Если цена задана явным параметром filters, цену применяем строго на шаге 2 (без мягкого фоллбэка).
    tc = plan.text_cond
    has_text_price = (tc.price_min is not None and plan.price_min is None) or (tc.price_max is not None and plan.price_max is None)
    text_for_apply = replace(
        tc,
        sort=None,
        price_min=tc.price_min if plan.price_min is None else None,
        price_max=tc.price_max if plan.price_max is None else None,
    )
    need_text_apply = bool(
        text_for_apply.exclude_vendors or text_for_apply.exclude_terms
        or text_for_apply.origin or text_for_apply.registry
        or text_for_apply.service or text_for_apply.platform
        or has_text_price
    )
    if ids and need_text_apply:
        ids, section, note, price_relaxed = feed_conditions.apply_conditions(
            engine, req, profile, text_for_apply, ids, section, preferred, selections, qty, renewal, note
        )

    # Базовый список до явных параметров filters/exclude (для расчёта фасетов и relax_hints).
    base_ids = list(ids)

    # 2. Фильтры и исключения из параметров запроса.
    if plan.has_filters and ids:
        filtered = _filter_ids(index, engine, plan, base_ids)
        if not filtered:
            relax_hints = _build_relax_hints(index, engine, req, plan, base_ids)
            hint_text = f" Попробуйте: {relax_hints[0]['label'].lower()}." if relax_hints else ""
            note = f"С заданными фильтрами подходящих товаров нет.{hint_text}"
            return [], base_ids, section, note, relax_hints, False
        ids = filtered
        if len(plan.categories) == 1 and plan.categories[0] in index.classes:
            section = plan.categories[0]

    # 3. Сортировка по всему подходящему списку (до нарезки страницы).
    if plan.sort in ("price_asc", "price_desc") and ids:
        ids = sort_ids(index, ids, plan.sort)

    return ids, base_ids, section, note, relax_hints, price_relaxed


def _fmt_int(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def _round_nice(val: float, fine: bool = False) -> int:
    if val <= 0:
        return 0
    if val < 100:
        step = 5 if fine else 10
    elif val < 1_000:
        step = 50 if fine else 100
    elif val < 5_000:
        step = 250 if fine else 500
    elif val < 20_000:
        step = 500 if fine else 1_000
    elif val < 100_000:
        step = 2_500 if fine else 5_000
    elif val < 500_000:
        step = 5_000 if fine else 10_000
    elif val < 2_000_000:
        step = 25_000 if fine else 50_000
    else:
        step = 50_000 if fine else 100_000
    return int(round(val / step) * step)


def _price_thresholds(prices: list[float]) -> list[tuple[int, int]]:
    """Подобрать 3–5 округлённых порогов цены с точным числом товаров <= порога."""
    n = len(prices)
    if n < 2 or prices[0] == prices[-1]:
        return []

    def collect(quantiles, fine=False, allow_full=False):
        by_count: dict[int, int] = {}
        for q in quantiles:
            raw = prices[int((n - 1) * q)]
            t = _round_nice(raw, fine=fine)
            if t <= 0:
                continue
            cnt = bisect_right(prices, t)
            if cnt <= 0 or (not allow_full and cnt >= n):
                continue
            if cnt not in by_count or t < by_count[cnt]:
                by_count[cnt] = t
        return sorted(((t, cnt) for cnt, t in by_count.items()), key=lambda pair: pair[0])

    pairs = collect((0.2, 0.4, 0.6, 0.8), fine=False)
    if len(pairs) < 3:
        pairs = collect((0.15, 0.30, 0.45, 0.60, 0.75, 0.88), fine=False)
    if len(pairs) < 3:
        pairs = collect((0.15, 0.30, 0.45, 0.60, 0.75, 0.88), fine=True)
    if len(pairs) < 2:
        pairs = collect((0.25, 0.5, 0.75, 1.0), fine=True, allow_full=True)
    if len(pairs) > 5:
        idxs = [int(round(i * (len(pairs) - 1) / 4)) for i in range(5)]
        pairs = [pairs[i] for i in dict.fromkeys(idxs)]
    return pairs


def build_facets(index, engine, plan: RequestPlan, base_ids: list[str], filtered_ids: list[str], *, disabled: bool = False) -> list[dict]:
    """Построить группы уточнения (vendor, category, price_max) с учётом остальных фильтров, без своего."""
    if disabled or not filtered_ids or not base_ids:
        return []
    cards = index.cat.cards
    card_vendors = index.card_vendors
    facets: list[dict] = []

    def pool_for(key: str) -> list[str]:
        if not plan.has_filters:
            return filtered_ids
        return _filter_ids(index, engine, plan, base_ids, skip_filter=key)

    # 1. Производитель (до 12 значений по числу товаров)
    v_pool = pool_for("vendor")
    v_counts: Counter = Counter()
    for cid in v_pool:
        vid = cards[cid].vendor or card_vendors.get(cid)
        if vid:
            v_counts[vid] += 1
    if len(v_counts) >= 2:
        lk = _vendor_lookup(index)
        ordered_v = sorted(
            v_counts.items(),
            key=lambda kv: (-kv[1], lk["display_name"].get(kv[0], kv[0]).casefold()),
        )[:12]
        facets.append(dict(
            key="vendor",
            title="Производитель",
            values=[
                dict(id=vid, label=lk["display_name"].get(vid, vid), count=cnt)
                for vid, cnt in ordered_v
            ],
        ))

    # 2. Раздел (если в списке два раздела и больше)
    c_pool = pool_for("category")
    c_counts: Counter = Counter()
    for cid in c_pool:
        sec = index.card_sections.get(cid)
        if sec:
            c_counts[sec] += 1
    if len(c_counts) >= 2:
        ordered_c = sorted(
            c_counts.items(),
            key=lambda kv: (-kv[1], index.classes.get(kv[0], kv[0]).casefold()),
        )[:12]
        facets.append(dict(
            key="category",
            title="Раздел",
            values=[
                dict(id=sec, label=index.classes.get(sec, sec), count=cnt)
                for sec, cnt in ordered_c
            ],
        ))

    # 3. Цена (3–5 округлённых порогов «до N ₽»)
    p_pool = pool_for("price_max")
    prices = sorted(float(cards[cid].price_from) for cid in p_pool if cards[cid].price_from is not None)
    thresholds = _price_thresholds(prices)
    if len(thresholds) >= 2:
        facets.append(dict(
            key="price_max",
            title="Цена",
            values=[
                dict(id=t, label=f"до {_fmt_int(t)} ₽", count=cnt)
                for t, cnt in thresholds
            ],
        ))

    return facets


def populate_result(index, engine, plan: RequestPlan, result: dict, chips: list[dict], relax_hints: list[dict] = ()):
    """Заполнить understood.filters, understood.exclude, removable chips и relax_hints."""
    feed_conditions.populate_result(plan.cond, result, chips)
    filters = result["understood"]["filters"]
    exclude = result["understood"]["exclude"]

    if plan.vendors:
        canonical = sorted(plan.vendor_ids) if plan.vendor_ids else list(plan.vendors)
        filters["vendor"] = canonical
        labels = _vendor_labels(index, engine, plan.vendors)
        chips[:] = [c for c in chips if c.get("key") != "vendor"]
        chips.append(dict(key="vendor", label=f"Производитель: {', '.join(labels)}", removable=True))

    if plan.categories:
        filters["category"] = list(plan.categories)
        labels = [index.classes.get(c, c) for c in plan.categories]
        chips[:] = [c for c in chips if c.get("key") != "category"]
        chips.append(dict(key="category", label=f"Раздел: {', '.join(labels)}", removable=True))

    if plan.platforms:
        filters["platform"] = list(plan.platforms)
        if not any(c.get("key") == "platform" for c in chips):
            labels = [feed_conditions.PLATFORM_LABELS.get(p, p) for p in plan.platforms]
            chips.append(dict(key="platform", label=f"Для {', '.join(labels)}", removable=True))

    if plan.exclude_vendors_raw:
        existing_ev = list(exclude.get("vendor") or ())
        added_ev = sorted(plan.exclude_vendor_ids) if plan.exclude_vendor_ids else list(plan.exclude_vendors_raw)
        exclude["vendor"] = list(dict.fromkeys([*existing_ev, *added_ev]))
        labels = _vendor_labels(index, engine, plan.exclude_vendors_raw)
        if not any(c.get("key") == "exclude" and ", ".join(labels) in (c.get("label") or "") for c in chips):
            chips.append(dict(key="exclude", label=f"Кроме {', '.join(labels)}", removable=True))

    if plan.exclude_categories:
        exclude["category"] = list(plan.exclude_categories)
        labels = [index.classes.get(c, c) for c in plan.exclude_categories]
        chips.append(dict(key="exclude", label=f"Кроме раздела: {', '.join(labels)}", removable=True))

    if relax_hints:
        result["relax_hints"] = list(relax_hints)
        result["understood"]["zero_reason"] = "filters_too_strict"
        blocks = result["blocks"]
        if not any(b.get("type") == "clarify" and b.get("options") for b in blocks):
            blocks.append(dict(
                type="clarify",
                title="Слишком строгие фильтры",
                question=result["understood"].get("agent_note") or "С заданными условиями подходящих товаров нет.",
                options=[dict(label=h["label"], apply=h["apply"]) for h in relax_hints],
            ))


def build_vendor_result(engine, req, profile, trace, priorities, record, norm: str, vid: str, display_name: str) -> dict | None:
    """Каталог производителя («всё от X / продукты X») с поддержкой фильтров, исключений, сортировки и фасетов."""
    from .feed import display, finish, order, recommend

    index = engine.catalog.feed
    raw_cids = list(index.language.vendor_cards.get(vid, ())) or list(index.tags["vendors"].get(vid, ()))
    if not raw_cids:
        return None
    plan = extract(engine, norm, req)
    ids = feed_guard.rank_vendor_cards(index, raw_cids)
    preferred: dict = {}
    selections: dict = {}
    title = f"Продукты {display_name}"
    note = f"Предложения производителя {display_name} в каталоге."
    ids, base_ids, section, note, relax_hints, _ = apply(
        engine, req, profile, plan, ids, None, preferred, selections, None, False, note
    )
    trace.add("retrieve", "Каталог производителя", title, candidates=len(ids))
    start = (req.page - 1) * req.page_size
    page_ids = ids[start:start + req.page_size]
    prepare_page_offers(index, page_ids, plan, profile, preferred, selections, None, False)
    items = [display(engine, cid, profile, preferred.get(cid), selections.get(cid)) for cid in page_ids]
    for i, c in enumerate(items, 1):
        c["position"] = i
    merch = order(engine, req, profile, trace, priorities, "category", section, items)
    if merch is None:
        return None
    items = merch["cards"]
    finish_items_sort(items, plan.sort)
    main = [c["card_id"] for c in items]
    together = None
    if allow_upsell(req, plan, items):
        together, _ = recommend(engine, norm, items, profile, "category")
    for i, c in enumerate(items, 1):
        c["position"] = i
    blocks = [dict(type="products", title=title, category_id=section, total=len(ids), items=items)]
    if together:
        blocks.append(together)
    chips = [dict(key="vendor", label=display_name, removable=False)]
    facets = build_facets(index, engine, plan, base_ids, ids)
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
            chips=chips,
            zero_reason=None,
            agent_note=note,
        ),
        blocks=blocks,
        facets=facets,
        notes=[],
        banners=merch["banners"],
        relax_hints=[],
        related_queries=[],
        profile=profile_info(profile),
        cost=cost_summary([], engine.usd_rub),
        trace=trace.steps,
        timing_ms={},
    )
    populate_result(index, engine, plan, result, chips, relax_hints)
    return finish(engine, req, trace, record, result, items, len(main), [], profile=profile)
