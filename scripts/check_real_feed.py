"""Контроль 30.3 и время полного ответа на открытом снимке магазина."""
import argparse
import json
import resource
import sys
from pathlib import Path
from time import perf_counter

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kuznitsa.config import Config
from kuznitsa.engine import Engine
from kuznitsa.evaluation import cards_from
from kuznitsa.schema import Request
from kuznitsa.suggest.index import suggest


CONTROL = [
    ("astra linux", "astra linux special edition"),
    ("Microsoft Office для дома и бизнеса", "2024"),
    ("kaspersky small office security", "kaspersky small office security"),
    ("крипто про csp 5.0", "криптопро csp"),
    ("anydesk", "anydesk"),
    ("кибер бэкап", "кибер бэкап"),
    ("сканер-вс", "сканер-вс"),
    ("мтс", "мтс линк"),
    ("max patrol", "maxpatrol endpoint protection"),
    ("365", "для семьи"),
]
ADDITIONAL = ["сервер", "ноутбук", "коммутатор", "моноблок", "монитор", "принтер",
              "Windows server", "сервер 1с", "антивирус для сервера", "антивирь", "винда",
              "мдаемон", "офис", "что использовать против вирусов?", "чем защитить почту",
              "программа для чертежей", "как проверить контрагента", "астра линукс", "qqxwzz"]


def measure(engine, mode):
    elapsed, suggestions, checks, examples = [], [], [], []
    usd = 0.
    companions = []
    for q, expected in [*CONTROL, *((s, "") for s in ADDITIONAL)]:
        start = perf_counter()
        response = engine.search(Request(q=q, mode=mode, source="eval"))
        elapsed.append(1000 * (perf_counter()-start))
        usd += response["cost"]["usd"]
        blocks = response["blocks"]
        cards = cards_from(blocks)
        title = cards[0]["title"] if cards else ""
        if q == "astra linux":
            companions = [(i["card"]["title"], i["reason"]) for b in blocks if b["type"]=="crosssell" for i in b["items"]]
        if expected:
            ok = expected in title.lower()
            if q=="кибер бэкап":
                ok = ok and "резервного копирования" in blocks[0]["title"].lower()
            checks.append(ok)
        examples.append([q, title, blocks[0]["title"], len(cards), response["cost"]["llm_calls"],round(elapsed[-1],1)])
        start = perf_counter()
        suggest(engine, q[:4])
        suggestions.append(1000 * (perf_counter()-start))
    return dict(mode=mode, passed=sum(checks), total=len(checks), usd=usd,
                p50_ms=round(float(np.median(elapsed)),1),p95_ms=round(float(np.percentile(elapsed,95)),1),
                suggest_p95_ms=round(float(np.percentile(suggestions,95)),1),examples=examples,companions=companions)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot",type=Path)
    parser.add_argument("--mode",choices=["fast","smart","both"],default="fast")
    args=parser.parse_args()
    start=perf_counter()
    engine=Engine.open(Config(data=args.snapshot))
    try:
        if not engine.catalog.is_feed:parser.error("Для проверки нужен снимок с доменами фида")
        engine.decisions.run_budget=.08
        metrics=dict(open_seconds=round(perf_counter()-start,1),offers=len(engine.catalog.offers_by_id),cards=len(engine.catalog.cards))
        # Прогрев модели и правила магазина без запросов к шлюзу.
        engine.search(Request(q="поиск раздела магазина",mode="fast",source="eval"))
        metrics["results"]=[measure(engine,m) for m in (["fast","smart"] if args.mode=="both" else [args.mode])]
        metrics["peak_rss_mib"]=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)
        print(json.dumps(metrics,ensure_ascii=False,indent=2))
    finally:
        engine.close()
