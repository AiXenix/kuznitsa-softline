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
        chips.append(dict(key=kind,label=("Кроме " if neg else "")+label,source="query",removable=bool(replacement),remove_q=replacement))
    if qty:
        units={"device":"устройств","user":"пользователей","server":"серверов","core":"ядер","cpu":"процессоров","vm":"виртуальных машин"}
        label="Количество "+units.get(qty.get("metric"),"лицензий")
        chips.append(dict(key="qty",label=f"{label} · {qty['value']}",source="query",removable=False))
    for key,title,unit in [("price_max","Цена до","₽"),("price_min","Цена от","₽"),("term_months","Срок","мес.")]:
        if key in filters:
            chips.append(dict(key=key,label=f"{title} {filters[key]:g} {unit}",source="query",removable=False))
    return chips
