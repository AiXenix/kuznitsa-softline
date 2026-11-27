"""Открытый набор «параметры запроса»: страницы, сортировка, фильтры, исключения, фасеты,
уточнение в сессии и устойчивость к оформлению ввода.

    python scripts/check_request.py --url http://127.0.0.1:8099 [--fails] [--group сортировка]

Наборы tests/audit/*.tsv проверяют названия товаров. Здесь проверяются свойства ответа,
которые обязаны выполняться на любом каталоге: цены идут по порядку, все карточки от выбранного
производителя, страницы не повторяют друг друга, короткое уточнение наследует предмет предыдущего
запроса той же сессии, смайлик или скобки не меняют ответ. Проверки идут через HTTP: так же,
как запросы приходят от витрины.
"""
import argparse
import collections
import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

URL = "http://127.0.0.1:8099"
CHECKS = []


def post(body):
    data = json.dumps(body).encode()
    request = urllib.request.Request(URL + "/api/search", data=data, headers={"content-type": "application/json"})
    try:
        answer = urllib.request.urlopen(request, timeout=120)
        code, raw = answer.status, answer.read()
    except urllib.error.HTTPError as error:
        code, raw = error.code, error.read()
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, {}


def ask(q, **extra):
    body = {"q": q, "mode": "fast", "source": "eval"}
    body.update(extra)
    return post(body)


def card(item):
    return item["card"] if isinstance(item.get("card"), dict) else item


def shown(answer, first=False):
    """Основные карточки ответа без допродаж. first — только главный список (первый блок товаров)."""
    out = []
    for block in answer.get("blocks") or []:
        if block.get("type") not in ("products", "analogs"):
            continue
        out += [card(i) for i in block.get("items") or [] if i.get("kind") != "upsell"]
        if first:
            break
    return out


def upsell(answer):
    return [card(i) for b in answer.get("blocks") or [] for i in b.get("items") or [] if i.get("kind") == "upsell"]


def total(answer):
    for block in answer.get("blocks") or []:
        if block.get("type") in ("products", "analogs"):
            return block.get("total")


def full(q, **extra):
    """Главный список целиком: все страницы по 100 карточек."""
    out, seen = [], set()
    for page in range(1, 8):
        code, answer = ask(q, page=page, page_size=100, **extra)
        rows = [c for c in shown(answer, True) if c.get("card_id") not in seen]
        if code != 200 or not rows:
            break
        seen.update(c.get("card_id") for c in rows)
        out += rows
    return out


def ids(rows):
    return [c.get("card_id") for c in rows]


def vendor(c):
    v = c.get("vendor")
    return (v.get("id") if isinstance(v, dict) else v) or ""


def vendor_name(c):
    v = c.get("vendor")
    return (v.get("name") if isinstance(v, dict) else v) or ""


def price(c):
    return c.get("price_from")


def titles(rows, n=4):
    return " | ".join((c.get("title") or "?")[:34] for c in rows[:n])


def check(group, name):
    def wrap(fn):
        CHECKS.append((group, name, fn))
        return fn
    return wrap


def intent(answer):
    return (answer.get("understood") or {}).get("intent")


# ---------- страницы
for _q in ["антивирус", "ноутбук", "монитор", "касперский", "мышь"]:
    def _pages(q=_q):
        code, answer = ask(q)
        n = total(answer) or 0
        seen, repeats, sizes = [], 0, []
        for page in range(1, min(6, -(-n // 20)) + 1):
            code, answer = ask(q, page=page, page_size=20)
            rows = ids(shown(answer, True))
            repeats += sum(1 for i in rows if i in seen)
            seen += rows
            sizes.append(len(rows))
        want = min(n, 120)
        return repeats == 0 and len(set(seen)) == want, "всего %s, страницы %s, повторов %d, разных %d из %d" % (n, sizes, repeats, len(set(seen)), want)
    check("страницы", "«%s»: страницы не повторяются и показывают весь список" % _q)(_pages)


@check("страницы", "«антивирус»: допродажи второй страницы не повторяют первую")
def _():
    a, b = ask("антивирус", page=1)[1], ask("антивирус", page=2)[1]
    same = set(ids(upsell(a))) & set(ids(upsell(b)))
    return not same, "совпало допродаж: %d" % len(same)


@check("страницы", "страница за концом списка: пустой ответ без ошибки")
def _():
    code, answer = ask("антивирус", page=9999)
    return code == 200 and not shown(answer), "код %d, карточек %d" % (code, len(shown(answer)))


@check("страницы", "«монитор», page_size=8: ровно восемь основных карточек")
def _():
    code, answer = ask("монитор", page_size=8)
    return len(shown(answer, True)) == 8, "карточек %d" % len(shown(answer, True))


# ---------- сортировка
def sort_check(q, direction):
    base = full(q)
    code, answer = ask(q, sort=direction)
    rows = shown(answer, True)
    prices = [price(c) for c in rows]
    known = [p for p in prices if isinstance(p, (int, float))]
    ordered = known == sorted(known, reverse=direction == "price_desc")
    tail = all(p is None for p in prices[len(known):]) if None in prices else True
    inside = set(ids(rows)) <= set(ids(base))
    base_prices = [price(c) for c in base if isinstance(price(c), (int, float))]
    edge = (min(base_prices) if direction == "price_asc" else max(base_prices)) if base_prices else None
    extreme = bool(known) and known[0] == edge
    mixed = [price(c) for c in upsell(answer)] and any(b.get("type") == "products" and any(i.get("kind") == "upsell" for i in b.get("items") or []) and b.get("total") for b in answer.get("blocks") or [])
    ok = code == 200 and len(rows) >= min(4, len(base)) and ordered and tail and inside and extreme and not mixed
    return ok, "карточек %d из %d, по порядку %s, из того же списка %s, первая цена %s при крайней %s, допродажи внутри списка %s | %s" % (
        len(rows), len(base), ordered and tail, inside, known[:1], edge, bool(mixed), titles(rows, 3))


for _q, _dirs in [("ноутбук", ("price_asc", "price_desc")), ("монитор 27", ("price_asc", "price_desc")), ("антивирус", ("price_asc", "price_desc")),
                  ("касперский", ("price_asc",)), ("windows 11", ("price_asc",)), ("мышь logitech", ("price_asc",)), ("microsoft office", ("price_desc",)), ("резервное копирование", ("price_asc",))]:
    for _d in _dirs:
        check("сортировка", "«%s», %s" % (_q, "сначала дешевле" if _d == "price_asc" else "сначала дороже"))(lambda q=_q, d=_d: sort_check(q, d))


@check("сортировка", "неизвестное значение sort: отказ 422, а не молчаливая подмена")
def _():
    code, answer = ask("ноутбук", sort="как-нибудь")
    return code == 422, "код %d" % code


# ---------- фильтры
def top_vendor(base):
    return collections.Counter(vendor(c) for c in base if vendor(c)).most_common(1)[0][0] if base else ""


for _q in ["ноутбук", "антивирус", "монитор", "мышь"]:
    def _vendor(q=_q):
        base = full(q)
        vid = top_vendor(base)
        rows = full(q, filters={"vendor": [vid]})
        want = sum(1 for c in base if vendor(c) == vid)
        alien = [c for c in rows if vendor(c) != vid]
        return bool(rows) and not alien and len(rows) == want, "производитель %s: карточек %d, ожидалось %d, чужих %d | %s" % (vid, len(rows), want, len(alien), titles(alien or rows, 3))
    check("фильтры", "«%s»: фильтр по производителю" % _q)(_vendor)


@check("фильтры", "«ноутбук»: производитель по названию в любом регистре")
def _():
    base = full("ноутбук")
    vid = top_vendor(base)
    name = next(vendor_name(c) for c in base if vendor(c) == vid)
    a, b = full("ноутбук", filters={"vendor": [vid]}), full("ноутбук", filters={"vendor": [name.lower()]})
    return bool(a) and ids(a) == ids(b), "по коду %d карточек, по названию «%s» %d" % (len(a), name.lower(), len(b))


def price_check(q, low, high):
    base = [c for c in full(q) if isinstance(price(c), (int, float))]
    values = sorted(price(c) for c in base)
    filters = {}
    if low is not None:
        filters["price_min"] = values[int(len(values) * low)]
    if high is not None:
        filters["price_max"] = values[int(len(values) * high)]
    rows = full(q, filters=filters)
    want = [c for c in base if filters.get("price_min", 0) <= price(c) <= filters.get("price_max", 1e18)]
    outside = [c for c in rows if not isinstance(price(c), (int, float)) or not filters.get("price_min", 0) <= price(c) <= filters.get("price_max", 1e18)]
    alien = set(ids(rows)) - set(ids(base))
    return bool(rows) and not outside and not alien and len(rows) == len(want), "%s: карточек %d, ожидалось %d, вне диапазона %d, не из списка %d | %s" % (
        json.dumps(filters), len(rows), len(want), len(outside), len(alien), titles(rows, 3))


for _q, _low, _high in [("ноутбук", None, .5), ("антивирус", None, .5), ("монитор", None, .3), ("ноутбук", .25, .75), ("монитор", .5, None), ("касперский", None, .5)]:
    check("фильтры", "«%s»: цена %s" % (_q, "от и до" if _low is not None and _high is not None else "до" if _high is not None else "от"))(lambda q=_q, a=_low, b=_high: price_check(q, a, b))


@check("фильтры", "«ноутбук»: производитель и цена вместе")
def _():
    base = full("ноутбук")
    vid = top_vendor(base)
    own = sorted(price(c) for c in base if vendor(c) == vid and isinstance(price(c), (int, float)))
    limit = own[len(own) // 2]
    rows = full("ноутбук", filters={"vendor": [vid], "price_max": limit})
    bad = [c for c in rows if vendor(c) != vid or not isinstance(price(c), (int, float)) or price(c) > limit]
    want = sum(1 for p in own if p <= limit)
    return bool(rows) and not bad and len(rows) == want, "%s до %s: карточек %d, ожидалось %d, лишних %d" % (vid, limit, len(rows), want, len(bad))


@check("фильтры", "«ноутбук»: производитель, которого нет в списке, — пусто, а не посторонние товары")
def _():
    code, answer = ask("ноутбук", filters={"vendor": ["нет-такого-производителя"]})
    return code == 200 and not shown(answer), "код %d, карточек %d | %s" % (code, len(shown(answer)), titles(shown(answer), 3))


@check("фильтры", "«антивирус» с фильтром: условие видно покупателю и снимается")
def _():
    base = full("антивирус")
    vid = top_vendor(base)
    code, answer = ask("антивирус", filters={"vendor": [vid]})
    chips = [c for c in (answer.get("understood") or {}).get("chips") or [] if c.get("key") == "vendor" and c.get("removable")]
    return bool(chips), "значков производителя со снятием: %d" % len(chips)


# ---------- исключения
for _q in ["ноутбук", "антивирус", "монитор"]:
    def _exclude(q=_q):
        base = full(q)
        vid = top_vendor(base)
        rows = full(q, exclude={"vendor": [vid]})
        want = sum(1 for c in base if vendor(c) != vid)
        bad = [c for c in rows if vendor(c) == vid]
        return bool(rows) and not bad and len(rows) == want, "без %s: карточек %d, ожидалось %d, исключённых в ответе %d" % (vid, len(rows), want, len(bad))
    check("исключения", "«%s»: исключить производителя параметром" % _q)(_exclude)

for _q, _rx in [("антивирус не касперский", "касперск|kaspersky"), ("антивирус кроме касперского", "касперск|kaspersky"), ("антивирус без dr.web", "dr.?web|доктор веб"),
                ("ноутбук не lenovo", "lenovo"), ("ноутбук кроме asus и acer", "asus|acer"), ("антивирус -касперский", "касперск|kaspersky"), ("монитор только не samsung", "samsung")]:
    def _text(q=_q, rx=_rx):
        code, answer = ask(q)
        rows = shown(answer)
        bad = [c for c in rows if re.search(rx, (c.get("title") or "") + " " + vendor_name(c), re.I)]
        return len(rows) >= 4 and not bad, "карточек %d, исключённых в ответе %d | %s" % (len(rows), len(bad), titles(bad or rows, 3))
    check("исключения", "«%s»" % _q)(_text)


# ---------- фасеты
def facet(answer, key):
    return next((f for f in answer.get("facets") or [] if f.get("key") == key), None)


for _q, _key in [("ноутбук", "vendor"), ("антивирус", "vendor"), ("монитор", "vendor"), ("касперский", "category"), ("lenovo", "category"), ("ноутбук", "price_max"), ("монитор", "price_max")]:
    def _facet(q=_q, key=_key):
        code, answer = ask(q)
        f = facet(answer, key)
        values = (f or {}).get("values") or []
        if len(values) < 2 or not all(v.get("id") not in (None, "") and v.get("label") and v.get("count", 0) > 0 for v in values):
            return False, "группа %s: значений %d" % (key, len(values))
        v = values[0]
        code, picked = ask(q, filters={key: v["id"] if key.startswith("price") else [v["id"]]})
        return total(picked) == v["count"], "группа «%s», значений %d; «%s» обещано %s, показано %s" % (f.get("title"), len(values), v["label"], v["count"], total(picked))
    check("фасеты", "«%s»: группа %s и честное число товаров" % (_q, _key))(_facet)


@check("фасеты", "«ноутбук» с выбранным производителем: остальные производители остаются в группе")
def _():
    code, answer = ask("ноутбук")
    f = facet(answer, "vendor")
    if not f or len(f.get("values") or []) < 2:
        return False, "группы производителей нет"
    code, picked = ask("ноутбук", filters={"vendor": [f["values"][0]["id"]]})
    g = facet(picked, "vendor")
    return bool(g) and len(g.get("values") or []) >= 2, "значений после выбора: %d" % len((g or {}).get("values") or [])


# ---------- уточнение в сессии
def chain(*steps, **last):
    session = str(uuid.uuid4())
    answer = {}
    for i, q in enumerate(steps):
        code, answer = ask(q, session_id=session, **(last if i == len(steps) - 1 else {}))
    return answer


def subject(first, answer, n=4):
    rows = shown(answer)[:n]
    return len(rows) >= min(n, 4) and set(ids(rows)) <= set(ids(full(first))), rows


def context(name, steps, test):
    def run():
        answer = chain(*steps)
        rows = shown(answer)[:4]
        ok, note = test(answer, rows)
        return ok, "%s%s| %s" % (note + " " if note else "", "[%s] " % intent(answer), titles(rows))
    check("контекст", " → ".join("«%s»" % s for s in steps) + ": " + name)(run)


def all_rows(rows, fn):
    return len(rows) >= 4 and all(fn(c) for c in rows)


context("остаётся Касперский", ["антивирус касперский", "на 5 пк"], lambda a, r: (all_rows(r, lambda c: re.search("kaspersky|касперск", c.get("title", "") + vendor_name(c), re.I)), ""))
context("ноутбуки Lenovo", ["ноутбук", "lenovo"], lambda a, r: (all_rows(r, lambda c: c.get("title", "").lower().startswith("ноутбук") and "lenovo" in vendor_name(c).lower()), ""))
context("ноутбуки не дороже", ["ноутбук", "до 60000"], lambda a, r: (all_rows(r, lambda c: c.get("title", "").lower().startswith("ноутбук") and (price(c) or 1e18) <= 60000), ""))
context("два уточнения подряд", ["ноутбук", "lenovo", "до 80000"], lambda a, r: (bool(r) and all(c.get("title", "").lower().startswith("ноутбук") and "lenovo" in vendor_name(c).lower() and (price(c) or 1e18) <= 80000 for c in r), ""))
context("первой Windows 11 Pro", ["windows 11", "pro"], lambda a, r: (bool(r) and bool(re.search(r"windows 11 pro", r[0].get("title", ""), re.I)), ""))
context("первой Windows 11 Home", ["windows 11", "а для дома"], lambda a, r: (bool(r) and bool(re.search(r"windows 11 home|домашн", r[0].get("title", ""), re.I)), ""))
context("остаются антивирусы", ["антивирус", "для linux"], lambda a, r: (subject("антивирус", a)[0], ""))
context("мониторы по возрастанию цены", ["монитор", "подешевле"], lambda a, r: (subject("монитор", a)[0] and [price(c) for c in r] == sorted(price(c) for c in r), "цены %s" % [price(c) for c in r]))
context("мониторы Samsung", ["монитор", "samsung"], lambda a, r: (all_rows(r, lambda c: c.get("title", "").lower().startswith("монитор") and "samsung" in vendor_name(c).lower()), ""))
context("мониторы 27 дюймов", ["монитор", "27 дюймов"], lambda a, r: (all_rows(r, lambda c: c.get("title", "").lower().startswith("монитор") and re.search(r"\b27", c.get("title", ""))), ""))
context("российские офисные пакеты", ["office 2021", "а что-нибудь российское"], lambda a, r: (len([c for c in r if re.search("р7|мойофис|myoffice|яндекс 360|алми|офис", c.get("title", ""), re.I) and not re.search("microsoft", c.get("title", ""), re.I)]) >= 2, ""))
context("антивирусы для дома", ["антивирус", "для дома"], lambda a, r: (subject("антивирус для дома", a)[0], ""))
context("новый предмет не наследует старый", ["касперский", "ноутбук"], lambda a, r: (all_rows(r, lambda c: c.get("title", "").lower().startswith("ноутбук")), ""))
context("новый предмет не наследует старый", ["ноутбук", "антивирус касперский"], lambda a, r: (all_rows(r, lambda c: re.search("kaspersky|касперск", c.get("title", "") + vendor_name(c), re.I)), ""))
context("новый товар не наследует цену", ["ноутбук", "до 60000", "принтер"], lambda a, r: (all_rows(r, lambda c: re.search("принтер|мфу", c.get("title", ""), re.I)) and any((price(c) or 0) > 0 for c in r), ""))


@check("контекст", "«ноутбук» → «до 60000»: наследование показано и снимается")
def _():
    answer = chain("ноутбук", "до 60000")
    u = answer.get("understood") or {}
    chips = [c for c in u.get("chips") or [] if c.get("key") == "context" and c.get("removable")]
    return (u.get("inherited") or {}).get("from_q") == "ноутбук" and bool(chips), "унаследовано от %r, значков %d" % ((u.get("inherited") or {}).get("from_q"), len(chips))


@check("контекст", "«ноутбук» → «lenovo» с context=off: как отдельный запрос")
def _():
    a = chain("ноутбук", "lenovo", context="off")
    b = ask("lenovo", session_id=str(uuid.uuid4()))[1]
    return bool(shown(a)) and ids(shown(a))[:4] == ids(shown(b))[:4], "%s || %s" % (titles(shown(a), 2), titles(shown(b), 2))


@check("контекст", "чужая сессия ничего не наследует")
def _():
    ask("ноутбук", session_id=str(uuid.uuid4()))
    answer = ask("до 60000", session_id=str(uuid.uuid4()))[1]
    return not (answer.get("understood") or {}).get("inherited"), "унаследовано: %s" % (answer.get("understood") or {}).get("inherited")


# ---------- оформление ввода
for _a, _b in [("антивирус", "антивирус 😀"), ("антивирус", "(антивирус)"), ("антивирус", "антивирус!!!"), ("антивирус", "  антивирус  "), ("антивирус", "АНТИВИРУС"), ("antivirus", "ａｎｔｉｖｉｒｕｓ"),
               ("касперский", "КАСПЕРСКИЙ"), ("касперский", "\"касперский\""), ("касперский", "«касперский»?"), ("windows 11", "[windows 11]"), ("windows 11", "windows  11."), ("dr web", "dr-web"),
               ("ноутбук lenovo", "ноутбук, lenovo"), ("ноутбук lenovo", "ноутбук LENOVO"), ("office 365", "office365"), ("антивирус касперский", "антивирус: касперский"), ("касперский", "ка​сперский"), ("касперский", "каспе́рский")]:
    def _same(a=_a, b=_b):
        x, y = ask(a)[1], ask(b)[1]
        return bool(shown(x)) and ids(shown(x))[:4] == ids(shown(y))[:4] and intent(x) == intent(y), "[%s] %s || [%s] %s" % (intent(x), titles(shown(x), 2), intent(y), titles(shown(y), 2))
    check("оформление", "«%s» и «%s» отвечают одинаково" % (_a, _b.replace("​", "<zwsp>").replace("́", "<ударение>")))(_same)

for _q in ["", "   ", "!!!", "???", "😀", ".", "*"]:
    def _blank(q=_q):
        code, answer = ask(q)
        blocks = [b for b in answer.get("blocks") or [] if b.get("type") in ("products", "analogs") and b.get("items") and not re.search("популярн|часто|хиты", b.get("title") or "", re.I)]
        return code in (200, 422) and not blocks, "код %d | %s" % (code, titles(shown(answer), 3))
    check("оформление", "пустой ввод %r: без случайных товаров" % _q)(_blank)


def main():
    global URL
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=URL)
    parser.add_argument("--group")
    parser.add_argument("--fails", action="store_true")
    parser.add_argument("--json")
    args = parser.parse_args()
    URL = args.url.rstrip("/")
    passed, rows, groups = 0, [], collections.OrderedDict()
    start = time.time()
    for group, name, fn in CHECKS:
        if args.group and group != args.group:
            continue
        try:
            ok, note = fn()
        except Exception as error:
            ok, note = False, "ошибка проверки: %r" % (error,)
        ok = bool(ok)
        passed += ok
        groups.setdefault(group, [0, 0])
        groups[group][0] += ok
        groups[group][1] += 1
        rows.append(dict(group=group, name=name, ok=ok, note=note))
        if not (args.fails and ok):
            print("%s  %-11s %s\n      %s" % ("сдан" if ok else "НЕТ ", group, name, str(note)[:300]))
    print()
    for group, (a, b) in groups.items():
        print("%-12s %d из %d" % (group, a, b))
    print("ИТОГО параметры запроса: %d из %d (%.1f %%), %.0f с" % (passed, len(rows), 100 * passed / max(1, len(rows)), time.time() - start))
    if args.json:
        json.dump(rows, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
