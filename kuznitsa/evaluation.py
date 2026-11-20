"""Проверка dev-запросов по идентификаторам KB и фактическим блокам ответа."""
from collections import Counter,defaultdict
from contextlib import closing
import json
import sqlite3
from time import time
from uuid import uuid4
from .schema import Request
from .text import normalize,tokens,lemma


def values(x):
    return x if isinstance(x,list) else [] if x is None else [x]


def cards_from(blocks):
    result=[]
    for b in blocks:
        if b["type"] in ("products","analogs","services","promo"):
            result.extend(c.get("card",c) for c in b["items"])
        elif b["type"]=="kit":
            result.extend(s["card"] for s in b["slots"] if s.get("card"))
        elif b["type"]=="spec":
            result.extend(s["card"] for s in b["lines"] if s.get("card"))
        elif b["type"]=="compare":
            result.extend(b["columns"])
    return list({c["card_id"]:c for c in result}.values())


def resolve(engine,label,kind):
    if not isinstance(label,str):
        return set()
    if label in engine.names[kind]:
        return {label}
    target=tuple(map(lemma,tokens(label)))
    exact={i for k,i,_ in engine.lex.entries.get(target,[]) if k==kind}
    if exact or not target:
        return exact
    return {ident for ident,title in engine.names[kind].items() if tuple(map(lemma,tokens(title)))[:len(target)]==target}


def inspect(engine,row,r):
    u=r["understood"]
    cards=cards_from(r["blocks"])
    first=cards[0] if cards else {}
    offer=engine.catalog.offers_by_id.get(first.get("offer",{}).get("offer_id"))
    def matches(label,card):
        family=engine.catalog.cards.get(card["card_id"])
        resolved=False
        for kind,actual in (("family",family.family if family else None),("vendor",card["vendor"]["id"])):
            ids=resolve(engine,label,kind)
            if ids:
                resolved=True
                if actual in ids:
                    return True
        if resolved:
            return False
        return normalize(str(label)) in normalize(card["title"])
    fields={**(offer.lic.model_dump() if offer else {}),**({"registry":offer.registry,"certs":offer.certs,"platform":offer.platforms} if offer else {}),
            "category":first.get("category",{}).get("id"),"vendor":first.get("vendor",{}).get("id"),**u["filters"],
            "intent":u["intent"],"qty":(u["qty"] or {}).get("value"),"corrected_to":r["query"]["corrected"],
            "family_any":u["filters"].get("family",[]),"exclude_vendor":u["exclude"].get("vendor",[]),
            "block_any":[b["type"] for b in r["blocks"]],"lines":next((len(b["lines"]) for b in r["blocks"] if b["type"]=="spec"),0)}
    checked={}
    failures={}
    gap=False
    for key,want in row.get("assert",{}).items():
        labels=values(want)
        got=fields.get(key)
        if key in ("top1_any","top5_any","must_not"):
            window=cards[:1] if key=="top1_any" else cards[:5] if key=="top5_any" else cards
            ok=any(matches(label,c) for c in window for label in labels)
            ok=not ok if key=="must_not" else ok
            got=[c["title"] for c in window[:5]]
            if not ok and key!="must_not" and labels:
                resolved=[resolve(engine,x,"family") for x in labels]
                gap |= all(resolved) and all(not engine.catalog.by["family"].get(i) for ids in resolved for i in ids)
        elif key=="zero_ok":
            got=bool(cards or any(b["type"]=="answer" and b.get("text") or b["type"]=="my_licenses" and b["items"] for b in r["blocks"]))
            ok=want is True or got
        elif key in ("vendor","exclude_vendor","family_any","category"):
            kind={"exclude_vendor":"vendor","family_any":"family"}.get(key,key)
            ok=any(set(values(got)).intersection(resolve(engine,label,kind) or {label}) for label in labels)
        elif key=="corrected_to":
            ok=any(normalize(str(v)) in normalize(got) for v in labels)
        else:
            ok=any((w==v or str(w).lower()==str(v).lower()) for w in labels for v in values(got))
        checked[key]=bool(ok)
        if not ok:
            why={"top1_any":"Первая карточка не совпала","top5_any":"В первых пяти карточках нет ожидаемого продукта",
                 "must_not":"В выдаче есть исключённый продукт","block_any":"Отсутствует ожидаемый блок",
                 "zero_ok":"Поиск не дал содержательного ответа","intent":"Выбран другой сценарий"}
            failures[key]=dict(expected=want,actual=got,message=why.get(key,"Условие поиска не совпало с ожиданием"))
    return checked,failures,gap


def evaluate(engine,file,mode,data):
    if not file.is_file():
        raise SystemExit(f"Отсутствует набор проверок {file}")
    ident=uuid4().hex
    path=data/"eval"/(ident+".jsonl")
    path.parent.mkdir(parents=True,exist_ok=True)
    scenarios=defaultdict(Counter)
    keys=defaultdict(Counter)
    totals=Counter()
    failures=[]
    with file.open() as src,path.open("w") as dest:
        for line in src:
            if not line.strip():
                continue
            row=json.loads(line)
            r=engine.search(Request(q=row["q"],profile_id=row.get("profile") or "guest",category=row.get("category_ctx"),mode=mode,source="eval"))
            checks,reasons,gap=inspect(engine,row,r)
            status="passed" if checks and all(checks.values()) else "data_gap" if gap else "failed"
            totals[status]+=1
            bucket=scenarios[row.get("scenario","other")]
            bucket["total"]+=1
            bucket[status]+=1
            for k,ok in checks.items():
                keys[k]["passed" if ok else "failed"]+=1
            record=dict(id=row["id"],q=row["q"],status=status,checks=checks,reasons=reasons,search_id=r["search_id"],ms=r["timing_ms"]["total"])
            if reasons:
                failures.append(dict(id=row["id"],q=row["q"],reasons=reasons))
            dest.write(json.dumps(record,ensure_ascii=False)+"\n")
    denominator=totals["passed"]+totals["failed"]
    for bucket in scenarios.values():
        eligible=bucket["total"]-bucket["data_gap"]
        bucket["pass_rate"]=round(bucket["passed"]/eligible,4) if eligible else None
    for bucket in keys.values():
        bucket["pass_rate"]=round(bucket["passed"]/(bucket["passed"]+bucket["failed"]),4)
    report=dict(summary=f"Пройдено: {totals['passed']} / не пройдено: {totals['failed']} / нет в данных: {totals['data_gap']}",
                pass_rate=round(totals["passed"]/denominator,4) if denominator else None,file=str(path),totals=dict(totals),scenarios=dict(scenarios),keys=dict(keys),failures=failures)
    with closing(sqlite3.connect(data/"kuznitsa.sqlite")) as db,db:
        db.execute("CREATE TABLE IF NOT EXISTS eval_runs(id TEXT PRIMARY KEY,ts REAL,mode TEXT,dataset TEXT,result_json TEXT)")
        db.execute("INSERT INTO eval_runs VALUES(?,?,?,?,?)",(ident,time(),mode,file.name,json.dumps(report,ensure_ascii=False)))
    return report
