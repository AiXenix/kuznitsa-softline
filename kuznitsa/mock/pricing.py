from math import log


def price(f, edition_index, band_index, pack, term, action, audience, default):
    data = f.get("price_rub") or {}
    typical = data.get("typical") or default
    low = data.get("low") or typical * .8
    high = max(data.get("high") or typical * 1.3, low * 1.05)
    lic = f.get("license", {})
    editions = len(f.get("editions", []))
    sizes = sorted(set(lic.get("packs") or [1]))
    if f.get("max_seats"):
        sizes = [size for size in sizes if size <= f["max_seats"]] or sizes
    span = high / max(low, 1)
    position = edition_index / max(1, editions - 1)
    pack_year = data.get("unit") == "pack_year"
    cores = "core" in lic.get("metrics", []) and len(sizes) > 1
    if pack and pack_year and len(sizes) > 1:
        # Часть разброса резервируется для редакций. Сумма за пакет возрастает
        # медленнее его вместимости, поэтому удельная цена снижается.
        spread = min(span ** (.70 if editions > 1 else 1), (sizes[-1] / sizes[0]) ** .90)
        exponent = log(spread) / log(sizes[-1] / sizes[0])
        base = low * (pack / sizes[0]) ** exponent * (span / spread) ** position
    else:
        steps = max(0, len(lic.get("bands") or []) - 1)
        first = min(high, max(low, .8 * low / .96 ** steps))
        base = first * (high / first) ** position if editions > 1 else typical
        base *= .96 ** band_index
        if pack and cores:
            base *= (pack / sizes[-1]) ** .94
        elif pack and not pack_year:
            base *= pack ** .94
    base *= {12: 1, 24: 1.8, 36: 2.5}.get(term, (term or 12) / 12)
    base *= dict(renewal=.7, upgrade=.6, crossgrade=.6, support=.5).get(action, 1)
    base *= dict(edu=.4, gov=.9).get(audience, 1)
    step = 100 if base >= 20000 else 10 if base >= 200 else 1
    return max(1, round(base / step) * step)


def edition_ranks(editions):
    """Reorder comparable tiers only. Unclassified editions retain their slots."""
    import re
    tiers = (r"home|basic|base|базов\w*|домашн\w*", r"standard|std|стандарт\w*",
             r"plus|плюс", r"pro|prof|professional|advanced|проф\w*|расширенн\w*",
             r"enterprise|total|datacenter|корп|корпоративн\w*|универсальн\w*")
    known = {}
    for i, ed in enumerate(editions):
        words = " ".join(str(x) for x in [ed.get("title", ""), ed.get("name", ""), *ed.get("aliases", [])])
        for tier, pattern in reversed(list(enumerate(tiers))):
            if re.search(r"\b(?:" + pattern + r")\b", words, re.I):
                known[i] = tier
                break
    ranks = list(range(len(editions)))
    for slot, i in zip(known, sorted(known, key=known.get)):
        ranks[i] = slot
    return ranks
