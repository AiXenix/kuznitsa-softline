"""Поля публичного понимания, которые можно отобразить или снять на витрине."""
from collections import Counter


def chips_for(words,entities,names,exclude,filters,qty):
    chips=[]
    seen=set()
    counts=Counter((e["type"],tuple(e["span"])) for e in entities)
    for entity in entities:
        kind=entity["type"]
        ident=entity["id"]
        start,end=entity["span"]
        if (kind,start,end) in seen:
            continue
        seen.add((kind,start,end))
        if kind=="edition" and ident not in filters.get("edition",[]):
            continue
        if kind=="metric" and qty:
            continue
        neg=start>0 and words[start-1] in ("без","кроме","не")
        if neg:
            start-=1
        if kind=="metric" and start and words[start-1].isdigit():
            start-=1
        replacement=" ".join(words[:start]+words[end:])
        label=names.get(kind,{}).get(ident,entity["text"])
        if counts[(kind,(entity["span"][0],end))]>1:
            label=entity["text"]+" · несколько вариантов"
        if kind in ("role","industry"):
            prefix="Комплект: " if kind=="role" and ident.startswith("kit_") else "Роль: " if kind=="role" else "Отрасль: "
            label=prefix+str(label).lower()
        chips.append(dict(key="exclude" if neg else kind,label=("Кроме " if neg else "")+label,source="query",removable=bool(replacement),remove_q=replacement))
    if qty:
        units={"device":"устройств","user":"пользователей","server":"серверов","core":"ядер","cpu":"процессоров","vm":"виртуальных машин"}
        label="Количество "+units.get(qty.get("metric"),"лицензий")
        n=qty["value"]
        role=any(e["type"] in ("role","industry") for e in entities)
        noun="рабочих мест" if 11<=n%100<=14 or n%10 not in (1,2,3,4) else "рабочее место" if n%10==1 else "рабочих места"
        chips.append(dict(key="qty",label=f"{n} {noun}" if role else f"{label} · {n}",source="query",removable=False))
    for key,title,unit in [("price_max","Цена до","₽"),("price_min","Цена от","₽"),("term_months","Срок","мес.")]:
        if key in filters:
            chips.append(dict(key="term" if key=="term_months" else "price",label=f"{title} {filters[key]:g} {unit}",source="query",removable=False))
    distinct={}
    for chip in chips:
        distinct.setdefault((chip["key"],chip["label"]),chip)
    return list(distinct.values())


def ignore_conditions(keys, words, filters, exclude, entities, qty):
    dropped = set(keys)
    if "term" in dropped:
        dropped.add("term_months")
    if "price" in dropped:
        dropped.update(("price_min", "price_max"))
    if "qty" in dropped:
        dropped.add("metric")
        qty = None
    for key in dropped:
        filters.pop(key, None)
    if "exclude" in dropped:
        exclude.clear()
    kept = []
    for e in entities:
        start = e["span"][0]
        negative = start > 0 and words[start-1] in {"без", "кроме", "не"}
        key = "exclude" if negative else e["type"]
        if key not in dropped:
            kept.append(e)
    return kept, qty
