"""Открытый контроль назначения, раздела и доступности по §29.8."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kuznitsa.config import ROOT
from kuznitsa.engine import Engine
from kuznitsa.schema import Request


def check(engine,row,mode):
    result=engine.search(Request(q=row["q"],mode=mode,profile_id=row.get("profile","guest"),source="eval"))
    u=result["understood"]
    blocks=result["blocks"]
    cards=[c.get("card",c) for b in blocks if b["type"] in ("products","analogs") for c in b["items"]]
    f=u["filters"]
    refined=u.get("refined") or {}
    first=engine.catalog.cards[cards[0]["card_id"]] if cards else None
    actual=dict(audience=[refined.get("audience")],line=[refined.get("line"),*(f.get("family") or []),first.family if first else None],
                vendor=[*(f.get("vendor") or []),first.vendor if first else None],category=[*(f.get("category") or []),first.category if first else None],
                platform=f.get("platform",[]),not_sold=[any(b["type"]=="not_in_catalog" for b in blocks)])
    if row["expect"].get("not_sold"):
        alternatives=[engine.catalog.cards[i["card"]["card_id"]] for b in blocks if b["type"]=="analogs"
                      for i in b["items"] if i["card"]["offer"]["available"]]
        actual["not_sold"]=[actual["not_sold"][0] and bool(alternatives)]
        actual["line"]=[c.family for c in alternatives[:1]]
        actual["category"]=[c.category for c in alternatives[:1]]
        actual["vendor"]+= [engine.kb.rows["families"].get(fid,{}).get("vendor") for fid in f.get("family",[])]
    return {k:(v,actual.get(k)) for k,v in row["expect"].items() if not any(x in actual.get(k,[]) for x in (v if isinstance(v,list) else [v]))}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file",nargs="?",type=Path,default=ROOT/"design/proposals/neon4/probes-audience-r6.jsonl")
    parser.add_argument("--mode",choices=("fast","smart"),default="fast")
    parser.add_argument("--budget-usd",type=float,default=0)
    args=parser.parse_args()
    engine=Engine.open()
    try:
        if engine.decisions:engine.decisions.run_budget=args.budget_usd
        total=passed=0
        for line in args.file.read_text().splitlines():
            if not line.strip():continue
            row=json.loads(line)
            failures=check(engine,row,args.mode)
            if failures:print(row["q"],failures)
            total+=1
            passed+=not failures
        print(f"{args.mode}: {passed}/{total} ({passed/total:.1%})" if total else "Нет строк")
    finally:engine.close()
