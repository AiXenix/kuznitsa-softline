"""Проверка утверждений dev-набора по фактическому ответу."""
from collections import Counter
from pathlib import Path
import json
from uuid import uuid4
from .schema import Request


def checks(row,r):
    u=r["understood"]
    cards=[i.get("card",i) for b in r["blocks"] if b["type"] in ("products","analogs") for i in b["items"]]
    info={**u["filters"],"intent":u["intent"],"qty":(u["qty"] or {}).get("value"),"metric":(u["qty"] or {}).get("metric") or u["filters"].get("metric"),
          "corrected_to":r["query"]["corrected"],"exclude_vendor":u["exclude"].get("vendor",[]),
          "family_any":u["filters"].get("family",[]),"block_any":[b["type"] for b in r["blocks"]]}
    def strings(v):
        return [str(x).casefold() for x in (v if isinstance(v,list) else [v])]
    results={}
    for key,want in row.get("assert",{}).items():
        needles=strings(want)
        if key in ("top5_any","top1_any","must_not"):
            titles=" ".join(c["title"].lower()+" "+c["card_id"] for c in (cards[:1] if key=="top1_any" else cards[:5] if key=="top5_any" else cards))
            matched=any(n in titles for n in needles)
            results[key]=not matched if key=="must_not" else matched
        elif key=="zero_ok":
            results[key]=bool(cards) or want is True
        elif key in info:
            results[key]=any(n in strings(info[key]) for n in needles)
        else:
            results[key]=False
    return results


def evaluate(engine,file,mode,data):
    if not file.is_file():
        raise SystemExit(f"Отсутствует набор проверок {file}")
    totals,passed=Counter(),Counter()
    path=data/"eval"/(uuid4().hex+".jsonl")
    path.parent.mkdir(parents=True,exist_ok=True)
    with file.open() as src,path.open("w") as dest:
        for line in src:
            if not line.strip():
                continue
            row=json.loads(line)
            r=engine.search(Request(q=row["q"],profile_id=row.get("profile") or "guest",category=row.get("category_ctx"),
                                    mode=mode,source="eval"))
            results=checks(row,r)
            scenario=row.get("scenario","other")
            totals[scenario]+=1
            passed[scenario]+=int(bool(results) and all(results.values()))
            dest.write(json.dumps(dict(id=row.get("id"),checks=results,search_id=r["search_id"]),ensure_ascii=False)+"\n")
    return dict(file=str(path),scenarios={s:dict(passed=passed[s],total=n) for s,n in totals.items()})
