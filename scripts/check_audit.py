"""Открытый набор аудита поиска: живые запросы покупателей с ожиданиями по настоящему фиду.

Запуск из корня репозитория:
    python scripts/check_audit.py [fast|smart] [--cases tests/audit/cases.tsv] [--url http://127.0.0.1:8099]
                                  [--group задача] [--fails] [--json out.json] [--strict]
Без --url движок открывается в этом процессе на снимке KZ_DATA_DIR. Журнал пишется в каталог данных,
поэтому передавайте копию снимка. С --url запросы идут на работающий стенд.

Строка набора: «группа<TAB>запрос<TAB>проверки». Проверки разделяются «;», все должны выполниться:
    top=RX      среди первых четырёх основных карточек есть название, подходящее под RX (topN — среди первых N)
    first=RX    первая основная карточка подходит под RX
    not=RX      среди первых шести основных карточек нет названия под RX (notN — среди первых N)
    present     ответ не заявляет, что товара нет в каталоге
    absent      ответ честно сообщает, что товара нет
    min=N max=N число основных карточек не меньше и не больше N
    pricemax=N pricemin=N  цены первых четырёх основных карточек укладываются в границу
    asc desc    цены первых четырёх основных карточек идут по возрастанию или убыванию
    fix=RX      исправленный запрос подходит под RX; nofix — запрос не исправлялся
    note=RX notnote=RX     пояснение к ответу подходит или не подходит под RX
    sec=RX      заголовок блока или пояснение подходит под RX
    intent=RX   распознанный тип запроса
    filter=K nofilter=K    условие K распознано или не распознано
    block=T noblock=T      блок типа T есть или отсутствует
Основные карточки: товары блоков products, analogs, kit, spec и compare без пометки «Вам может пригодиться».
Регулярные выражения сравниваются без учёта регистра, «ё» приравнивается к «е».
"""
import argparse
import collections
import json
import os
import re
import sys
import time
import urllib.request

MAIN = {"products", "analogs", "kit", "spec", "compare"}
ABSENT_BLOCKS = {"not_in_catalog", "vendor_left", "out_of_stock"}
ABSENT_NOTE = re.compile(r"нет в каталоге|в каталоге нет|нет в продаже|не поставля|не прода[её]тся|уш[её]л с рынка")


def fold(text):
    return str(text or "").lower().replace("ё", "е")


def rx(pattern):
    return re.compile(fold(pattern))


def price_of(card):
    for key in ("price", "price_from", "price_min", "min_price"):
        value = card.get(key)
        if isinstance(value, dict):
            value = value.get("value") or value.get("min") or value.get("from")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


class Answer:
    def __init__(self, data):
        self.understood = data.get("understood") or {}
        self.query = data.get("query") or {}
        self.blocks = data.get("blocks") or []
        self.cards = []
        for block in self.blocks:
            if block.get("type") not in MAIN:
                continue
            for item in block.get("items") or []:
                if not isinstance(item, dict):
                    continue
                card = item.get("card") if isinstance(item.get("card"), dict) else item
                if card.get("kind") != "upsell" and (card.get("title") or card.get("name")):
                    self.cards.append(card)
        self.titles = [fold(c.get("title") or c.get("name")) for c in self.cards]
        self.note = fold(self.understood.get("agent_note"))
        self.types = {b.get("type") for b in self.blocks}

    def absent(self):
        return bool(self.understood.get("zero_reason") or self.understood.get("intent") == "out_of_catalog"
                    or self.types & ABSENT_BLOCKS or ABSENT_NOTE.search(self.note))

    def fixed(self):
        # corrected меняется и при вынесении условий (цена, срок), поэтому смотрим только сами исправления слов.
        return " ".join(fold(c.get("to")) for c in self.query.get("corrections") or [] if isinstance(c, dict))

    def prices(self, n=4):
        return [p for p in map(price_of, self.cards[:n]) if p is not None]

    def check(self, check):
        key, _, value = check.partition("=")
        head = re.fullmatch(r"(top|not)(\d*)", key)
        if head and head[1] == "top":
            return any(rx(value).search(t) for t in self.titles[:int(head[2] or 4)])
        if head:
            return not any(rx(value).search(t) for t in self.titles[:int(head[2] or 6)])
        if key == "first":
            return bool(self.titles and rx(value).search(self.titles[0]))
        if key in ("present", "absent"):
            return self.absent() == (key == "absent")
        if key == "min":
            return len(self.cards) >= int(value)
        if key == "max":
            return len(self.cards) <= int(value)
        if key in ("pricemax", "pricemin"):
            prices = self.prices()
            return bool(prices) and all(p <= float(value) if key == "pricemax" else p >= float(value) for p in prices)
        if key in ("asc", "desc"):
            prices = self.prices()
            return len(prices) > 1 and prices == sorted(prices, reverse=key == "desc")
        if key == "fix":
            return bool(rx(value).search(self.fixed()))
        if key == "nofix":
            return not self.fixed()
        if key in ("note", "notnote"):
            return bool(rx(value).search(self.note)) == (key == "note")
        if key == "sec":
            return any(rx(value).search(fold(b.get("title"))) for b in self.blocks) or bool(rx(value).search(self.note))
        if key == "intent":
            return bool(rx(value).search(fold(self.understood.get("intent"))))
        if key in ("filter", "nofilter"):
            return (value in (self.understood.get("filters") or {})) == (key == "filter")
        if key in ("block", "noblock"):
            return (value in self.types) == (key == "block")
        raise ValueError("неизвестная проверка: " + check)


def read_cases(path, group):
    cases = []
    for number, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            raise SystemExit("%s:%d: нужны три поля через табуляцию" % (path, number))
        if not group or parts[0] == group:
            cases.append((parts[0], parts[1], [c.strip() for c in parts[2].split(";") if c.strip()]))
    return cases


def http_search(url, mode):
    def search(q):
        body = json.dumps({"q": q, "profile_id": "guest", "mode": mode, "explain": False,
                           "source": "eval" if mode == "fast" else "api"}).encode()
        request = urllib.request.Request(url.rstrip("/") + "/api/search", data=body, headers={"content-type": "application/json"})
        return json.load(urllib.request.urlopen(request, timeout=90))
    return search


def local_search(mode):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    if mode == "fast":
        os.environ["KZ_LLM"] = "off"
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from kuznitsa.config import Config
    from kuznitsa.engine import Engine
    from kuznitsa.schema import Request
    started = time.time()
    engine = Engine.open(Config())
    if mode == "smart" and getattr(engine, "decisions", None):
        engine.decisions.run_budget = float(os.environ.get("KZ_AUDIT_BUDGET", "0.3"))
    print("движок открыт за %.0f с, карточек %d" % (time.time() - started, len(engine.catalog.cards)), flush=True)
    return lambda q: engine.search(Request(q=q, mode=mode, source="eval", explain=False, page_size=20))


def main():
    parser = argparse.ArgumentParser(description="Открытый набор аудита поиска")
    parser.add_argument("mode", nargs="?", default="fast", choices=["fast", "smart"])
    parser.add_argument("--cases", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "audit", "cases.tsv"))
    parser.add_argument("--url")
    parser.add_argument("--group")
    parser.add_argument("--fails", action="store_true", help="печатать только несданные запросы")
    parser.add_argument("--json")
    parser.add_argument("--strict", action="store_true", help="код возврата 1, если есть несданные запросы")
    args = parser.parse_args()
    cases = read_cases(args.cases, args.group)
    search = http_search(args.url, args.mode) if args.url else local_search(args.mode)
    passed, total, times, rows = collections.Counter(), collections.Counter(), [], []
    for group, q, checks in cases:
        started = time.perf_counter()
        try:
            answer = Answer(search(q))
            failed = [c for c in checks if not answer.check(c)]
            titles = answer.titles[:4]
        except ValueError:
            raise
        except Exception as error:
            failed, titles = ["ошибка: %s %s" % (type(error).__name__, str(error)[:80])], []
        times.append((time.perf_counter() - started) * 1000)
        total[group] += 1
        passed[group] += not failed
        rows.append(dict(group=group, q=q, ok=not failed, failed=failed, titles=titles, ms=round(times[-1])))
        if failed or not args.fails:
            print("%s %-10s %s | %s | %s" % ("ok  " if not failed else "FAIL", group, q[:60], "; ".join(failed)[:110], " / ".join(t[:34] for t in titles)), flush=True)
    print("---")
    for group in total:
        print("%-12s %3d из %3d" % (group, passed[group], total[group]))
    times.sort()
    print("ИТОГО %s: %d из %d (%.1f %%), p50 %.0f мс, p95 %.0f мс" % (
        args.mode, sum(passed.values()), len(cases), 100 * sum(passed.values()) / max(1, len(cases)),
        times[len(times) // 2] if times else 0, times[int(len(times) * .95)] if times else 0))
    if args.json:
        json.dump(rows, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if args.strict and sum(passed.values()) < len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
