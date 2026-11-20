#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
from uuid import uuid4
import yaml
from kuznitsa.config import Config,ROOT
from kuznitsa.engine import Engine
from kuznitsa.schema import Request
from kuznitsa.suggest.index import suggest

EXPECTED=dict(product="products",vendor="products",category="products",sku="products",task="products",analog="analogs",industry="kit",
              role_kit="kit",compliance="products answer",renewal="products my_licenses",license_ops="products answer",spec_list="spec",compare="compare",
              question="answer",broad="clarify",out_of_catalog="not_in_catalog",off_topic="categories answer",account="my_licenses",service="services lead",promo="promo products")


def gallery(engine,mode,page_size=20):
    run_id=uuid4().hex
    for row in yaml.load((ROOT/"docs/scenarios.yaml").read_text(),Loader=yaml.CSafeLoader):
        demo=row["demo"]
        intent=row.get("intent")
        record=dict(id=row["id"],expected=intent,surface=row["surface"])
        if row["surface"]=="admin":
            yield {**record,"ok":False,"reason":"Проверяется административный интерфейс потока B"},None
            continue
        profile=demo.get("profile") or "guest"
        if row["surface"]=="suggest":
            groups=suggest(engine,demo["q"],profile)["groups"]
            yield {**record,"ok":bool(groups),"q":demo["q"],"reason":"" if groups else "Нет подсказок"},None
            continue
        chain=demo.get("chain") or [demo.get("q") or row["examples"][0]]
        for q in chain:
            r=engine.search(Request(q=q,profile_id=profile,session_id=run_id+row["id"] if demo.get("chain") else "",category=demo.get("category_ctx") or demo.get("category"),mode=mode,source="gallery",page_size=page_size))
        nonempty=[b["type"] for b in r["blocks"] if
                  (any(s.get("card") for s in b["slots"]) if b["type"]=="kit" else
                   len(b["columns"])>=2 if b["type"]=="compare" else
                   any(b.get(k) for k in ("items","lines","text","options")))]
        actual=r["understood"]["intent"]
        ok=actual==intent and bool(set(nonempty)&set(EXPECTED.get(intent,"").split()))
        yield {**record,"q":q,"actual":actual,"blocks":nonempty,"ms":r["timing_ms"]["total"],"ok":ok,"reason":"" if ok else f"Получено {actual}: {', '.join(nonempty)}"},r


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",default="fast",choices=["fast","smart"])
    args=parser.parse_args()
    results=[row for row,_ in gallery(Engine.open(),args.mode)]
    (Config().data/"gallery-check.json").write_text(json.dumps(results,ensure_ascii=False,indent=2))
    for r in results:
        if not r["ok"]:
            print(r["id"],r["reason"])
    print(f"Пройдено {sum(r['ok'] for r in results)} из {len(results)}")


if __name__=="__main__":
    main()
