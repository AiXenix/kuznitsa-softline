#!/usr/bin/env python3
"""Открытый контроль комплектов по правилу зачёта из §27.9."""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median,quantiles

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kuznitsa.config import ROOT
from kuznitsa.engine import Engine
from kuznitsa.schema import Request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode",choices=("fast","smart"),default="fast")
    parser.add_argument("--budget-usd",type=float,default=0.)
    args=parser.parse_args()
    engine=Engine.open()
    if engine.decisions:
        engine.decisions.run_budget=args.budget_usd
    groups=defaultdict(list)
    elapsed=[]
    try:
        with (ROOT/"design/proposals/neon4/probes-kits-r3.jsonl").open() as src:
            for line in src:
                row=json.loads(line)
                result=engine.search(Request(q=row["q"],mode=args.mode,source="eval",page_size=3))
                entities=result["understood"]["entities"]
                correct=any(e["type"] in ("role","industry") and e["id"]==row["expect"] for e in entities)
                kit=any(b["type"]=="kit" for b in result["blocks"])
                groups[row["kind"],row["seen"]].append(kit and correct)
                elapsed.append(result["timing_ms"]["total"])
    finally:
        engine.close()
    for (kind,seen),checks in sorted(groups.items()):
        print(kind,"знакомые" if seen else "новые",f"{sum(checks)}/{len(checks)}")
    print(f"p50 {median(elapsed):.1f} мс, p95 {quantiles(elapsed,n=100)[94]:.1f} мс")
    if engine.decisions:
        print(f"Расход за прогон {engine.decisions.run_spent:.6f} USD")


if __name__=="__main__":
    main()
