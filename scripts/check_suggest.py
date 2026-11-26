"""Открытый набор аудита подсказок: что покупатель видит, пока набирает запрос.

Запуск из корня репозитория:
    python scripts/check_suggest.py [--cases tests/audit/suggest.tsv] [--url http://127.0.0.1:8099] [--fails] [--json out.json] [--strict]
    python scripts/check_suggest.py [--url …] --show "касп" "антив"      # все группы подсказок для указанных вводов
Без --url движок открывается в этом процессе на снимке KZ_DATA_DIR. С --url запросы идут на работающий стенд.

Строка набора: «ввод<TAB>проверки». Проверки разделяются «;», все должны выполниться:
    top=RX      среди первых четырёх подсказок-товаров есть подходящая под RX (topN — среди первых N)
    first=RX    первая подсказка-товар подходит под RX
    not=RX      среди первых шести подсказок-товаров нет подходящей под RX (notN — среди первых N)
    cat=RX      среди подсказок-разделов есть подходящая под RX
    any=RX      подходит любая подсказка любой группы
    fix=RX      исправленный ввод подходит под RX; nofix — ввод не исправлялся
    min=N max=N число подсказок-товаров не меньше и не больше N
    empty       подсказок нет вовсе
    uniq        ни один товар не повторяется ни внутри группы, ни между группами
Регулярные выражения сравниваются без учёта регистра, «ё» приравнивается к «е».
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request


def fold(text):
    return str(text or "").lower().replace("ё", "е")


def rx(pattern):
    return re.compile(fold(pattern))


class Answer:
    def __init__(self, data):
        self.groups = data.get("groups") or []
        self.fixed = fold(data.get("corrected"))
        self.products, self.categories, self.everything, self.cards = [], [], [], []
        for group in self.groups:
            texts = [fold(i.get("text")) for i in group.get("items") or [] if isinstance(i, dict)]
            self.everything += texts
            self.cards += [i["card_id"] for i in group.get("items") or [] if isinstance(i, dict) and i.get("card_id")]
            if group.get("type") == "products":
                self.products += texts
            elif group.get("type") == "categories":
                self.categories += texts
            elif group.get("type") == "corrections" and not self.fixed:
                self.fixed = " ".join(texts)

    def check(self, check):
        key, _, value = check.partition("=")
        head = re.fullmatch(r"(top|not)(\d*)", key)
        if head and head[1] == "top":
            return any(rx(value).search(t) for t in self.products[:int(head[2] or 4)])
        if head:
            return not any(rx(value).search(t) for t in self.products[:int(head[2] or 6)])
        if key == "first":
            return bool(self.products and rx(value).search(self.products[0]))
        if key == "cat":
            return any(rx(value).search(t) for t in self.categories)
        if key == "any":
            return any(rx(value).search(t) for t in self.everything)
        if key == "fix":
            return bool(rx(value).search(self.fixed))
        if key == "nofix":
            return not self.fixed
        if key == "min":
            return len(self.products) >= int(value)
        if key == "max":
            return len(self.products) <= int(value)
        if key == "empty":
            return not self.everything
        if key == "uniq":
            return len(self.cards) == len(set(self.cards))
        raise ValueError("неизвестная проверка: " + check)


def read_cases(path):
    cases = []
    for number, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise SystemExit("%s:%d: нужны два поля через табуляцию" % (path, number))
        cases.append((parts[0], [c.strip() for c in parts[1].split(";") if c.strip()]))
    return cases


def http_suggest(url):
    def call(q):
        return json.load(urllib.request.urlopen(url.rstrip("/") + "/api/suggest?q=" + urllib.parse.quote(q), timeout=30))
    return call


def local_suggest():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ["KZ_LLM"] = "off"
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from kuznitsa.config import Config
    from kuznitsa.engine import Engine
    from kuznitsa.suggest.index import suggest
    started = time.time()
    engine = Engine.open(Config())
    print("движок открыт за %.0f с" % (time.time() - started), flush=True)
    return lambda q: suggest(engine, q)


def main():
    parser = argparse.ArgumentParser(description="Открытый набор аудита подсказок")
    parser.add_argument("--cases", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "audit", "suggest.tsv"))
    parser.add_argument("--url")
    parser.add_argument("--fails", action="store_true", help="печатать только несданные строки")
    parser.add_argument("--json")
    parser.add_argument("--strict", action="store_true", help="код возврата 1, если есть несданные строки")
    parser.add_argument("--show", nargs="+", metavar="ВВОД", help="вместо набора напечатать все группы подсказок для указанных вводов")
    args = parser.parse_args()
    cases = read_cases(args.cases)
    call = http_suggest(args.url) if args.url else local_suggest()
    if args.show:
        for q in args.show:
            data = call(q)
            print("%s → исправлено: %s, %s мс" % (q, data.get("corrected"), data.get("ms")))
            for group in data.get("groups") or []:
                print("  [%s] %s" % (group.get("type"), " | ".join(str(i.get("text"))[:60] for i in group.get("items") or [])))
        return
    passed, times, rows = 0, [], []
    for q, checks in cases:
        started = time.perf_counter()
        try:
            answer = Answer(call(q))
            failed = [c for c in checks if not answer.check(c)]
            shown = answer.products[:4]
        except ValueError:
            raise
        except Exception as error:
            failed, shown = ["ошибка: %s %s" % (type(error).__name__, str(error)[:80])], []
        times.append((time.perf_counter() - started) * 1000)
        passed += not failed
        rows.append(dict(q=q, ok=not failed, failed=failed, products=shown, ms=round(times[-1])))
        if failed or not args.fails:
            print("%s %-18s | %s | %s" % ("ok  " if not failed else "FAIL", q[:18], "; ".join(failed)[:100], " / ".join(t[:32] for t in shown)), flush=True)
    times.sort()
    print("---")
    print("ИТОГО подсказки: %d из %d (%.1f %%), p50 %.0f мс, p95 %.0f мс" % (
        passed, len(cases), 100 * passed / max(1, len(cases)),
        times[len(times) // 2] if times else 0, times[int(len(times) * .95)] if times else 0))
    if args.json:
        json.dump(rows, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if args.strict and passed < len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
