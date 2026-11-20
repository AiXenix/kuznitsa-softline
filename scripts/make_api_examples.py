#!/usr/bin/env python3
"""Снимки реальных ответов из одного прохода по галерее."""
import json
from check_scenarios import gallery
from kuznitsa.config import ROOT
from kuznitsa.engine import Engine
from kuznitsa.schema import Request
from kuznitsa.understand.intent import TITLES


def main():
    engine=Engine.open()
    examples={}
    block_examples={}
    for check,response in gallery(engine,"fast",page_size=4):
        if response is None:
            continue
        intent=response["understood"]["intent"]
        if check["ok"]:
            examples.setdefault(intent,response)
        for block in response["blocks"]:
            block_examples.setdefault(block["type"],response)
    if "promo" not in block_examples:
        actual=engine.search(Request(q="акции",mode="fast",source="gallery",page_size=4))
        if any(b["type"]=="promo" and b["items"] for b in actual["blocks"]):
            examples["promo"]=actual
    if "sku" not in examples:
        offer=next(iter(engine.catalog.skus.values()))
        examples["sku"]=engine.search(Request(q=offer.sku,mode="fast",source="gallery"))
    missing=set(TITLES)-examples.keys()
    if missing:
        raise ValueError("Нет примеров сценариев: "+", ".join(sorted(missing)))
    covered={b["type"] for r in examples.values() for b in r["blocks"]}
    for kind,response in block_examples.items():
        if kind not in covered:
            examples["block_"+kind]=response
            covered.update(b["type"] for b in response["blocks"])
    expected=set("products kit analogs answer spec compare not_in_catalog categories vendors my_licenses clarify services promo lead".split())
    if engine.kb.rows.get("crosssell"):
        expected.add("crosssell")
    if expected-covered:
        raise ValueError("Нет снимка блоков: "+", ".join(sorted(expected-covered)))
    path=ROOT/"docs/api_examples"
    path.mkdir(parents=True,exist_ok=True)
    for name,response in sorted(examples.items()):
        (path/(name+".json")).write_text(json.dumps(response,ensure_ascii=False,indent=2)+"\n")
    print(f"Сохранено ответов · {len(examples)}. Блоки · "+", ".join(sorted(covered)))


if __name__=="__main__":
    main()
