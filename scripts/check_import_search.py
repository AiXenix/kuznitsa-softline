#!/usr/bin/env python3
"""Открытая репетиция поиска по прайсу E1. Ожидания читаются из строк поставщика."""
import argparse
from collections import defaultdict
from pathlib import Path
import random
import re
import sys

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kuznitsa.config import Config
from kuznitsa.engine import Engine
from kuznitsa.schema import Request
from kuznitsa.text import normalize
from kuznitsa.understand.repair import LAYOUT
from kuznitsa.understand.spell_index import cyrillic, roman


def observations(price):
    book = load_workbook(price, read_only=True, data_only=True)
    try:
        rows = iter(book.active.values)
        headers = next(row for row in rows if "Артикул изготовителя" in row and "Серия" in row)
        return [dict(zip(headers, row)) for row in rows]
    finally:
        book.close()


def queries(row, synonyms, tasks):
    series = str(row["Серия"])
    vendor = str(row["Производитель"])
    sku = str(row["Артикул изготовителя"])
    group = str(row["Путь группы"]).split("/")[-1].strip()
    count = int(row["От"] or 1)

    def family(offer):
        if offer.attrs.get("series"):
            return normalize(offer.attrs["series"]) == normalize(series) and offer.vendor == vendor
        return offer.vendor == vendor and normalize(series) in normalize(offer.name)

    def quantity(offer):
        return (offer.lic.qty_min or 1) <= count <= (offer.lic.qty_max or float("inf"))

    for alias in re.split("[;,|]",str(row.get("Также ищут") or "")):
        if alias.strip():
            yield "жаргон",alias.strip(),alias.strip(),lambda o: o.sku in synonyms[normalize(alias.strip())]
    task=str(row.get("Назначение") or "").strip()
    if task:
        yield "задача",task,"Нужно "+task,lambda o: o.sku in tasks[normalize(task)]
    source_id=str(row.get("Код УТ") or "").strip()
    if source_id:
        yield "код учёта",source_id,source_id,lambda o: o.sku==sku
    yield "полное название", sku, str(row["Номенклатура"]), lambda o: o.sku == sku
    yield "артикул", sku, sku, lambda o: o.sku == sku
    yield "класс", group, group, lambda o: group in o.category_path
    yield "класс + вендор", (group,vendor), group+" "+vendor, lambda o: group in o.category_path and o.vendor == vendor
    yield "класс + количество", group, f"{group} на {count} мест", lambda o: group in o.category_path and quantity(o)
    yield "семейство", series, series, family
    if row["Операция"]=="Продление":
        yield "продление", series, series+" продление", lambda o: family(o) and o.lic.action=="renewal"
    if len(series)>4 and re.match(r"^\w{4}",series):
        yield "опечатка", series, series[:1]+series[2]+series[1]+series[3:], family
        yield "раскладка", series, series.lower().translate(LAYOUT), family
        translit = roman(series) if re.search("[а-я]",series.lower()) else cyrillic(series.lower())
        if normalize(translit)!=normalize(series):
            yield "транслит", series, translit, family
    if row["Альтернатива"]:
        target = str(row["Альтернатива"])
        replaces = lambda o: normalize(target) in map(normalize,re.split("[;|]",o.attrs.get("analog_of","")))
        yield "аналог", target, "альтернатива "+target, replaces
    edition = str(row["Исполнение"] or "")
    operation = str(row["Операция"] or "")
    if edition and operation:
        def specified(o):
            name = normalize(o.name)
            return (family(o) and quantity(o) and
                    all(normalize(value) in normalize(o.attrs.get(key) or name)
                        for key,value in (("edition",edition),("operation",operation))))
        yield "строка спецификации", (series,operation), f"{vendor} / {series} / {edition} / {operation}, кол-во {count} ед.", specified


def check(engine, rows, limit):
    random.Random(2611).shuffle(rows)
    synonyms,tasks=defaultdict(set),defaultdict(set)
    for row in rows:
        for alias in re.split("[;,|]",str(row.get("Также ищут") or "")):
            if alias.strip():synonyms[normalize(alias.strip())].add(row["Артикул изготовителя"])
        if row.get("Назначение"):
            tasks[normalize(str(row["Назначение"]))].add(row["Артикул изготовителя"])
    tested = defaultdict(dict)
    for row in rows:
        if not all(row[k] for k in ("Производитель","Серия","Артикул изготовителя","Номенклатура")):
            continue
        for group,key,q,expected in queries(row,synonyms,tasks):
            scores = tested[group]
            if key in scores or len(scores)>=limit:
                continue
            result = engine.preview(Request(q=q,page_size=5),[])
            cards = []
            for block in result["blocks"]:
                if block["type"]=="products":
                    cards.extend(block["items"])
                if block["type"]=="spec":
                    cards.extend(line["card"] for line in block["lines"] if line["card"])
                if block["type"]=="analogs":
                    cards.extend(item["card"] for item in block["items"])
            window=1 if group in ("полное название","артикул","код учёта") else 5
            scores[key] = (group!="задача" or result["understood"]["intent"]=="task") and any(
                expected(engine.catalog.offers_by_id[c["offer"]["offer_id"]]) for c in cards[:window])
            if not scores[key]:
                print(f"Промах · {group} · {q}",flush=True)
    for group,scores in tested.items():
        print(f"{group}\t{sum(scores.values())}/{len(scores)}",flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("price",type=Path)
    parser.add_argument("--data",type=Path,required=True)
    parser.add_argument("--limit",type=int,default=28)
    args = parser.parse_args()
    engine = Engine.open(Config(data=args.data))
    try:
        check(engine,observations(args.price),args.limit)
    finally:
        engine.close()
