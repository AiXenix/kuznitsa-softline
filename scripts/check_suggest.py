"""Проверка типа подсказки, написания результата и признака исправления."""
from pathlib import Path
import json
import sys
from statistics import quantiles
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kuznitsa.config import ROOT
from kuznitsa.engine import Engine
from kuznitsa.suggest.index import suggest,key


def main():
    engine=Engine.open()
    times=[]
    hits=0
    for line in (ROOT/"eval/suggest.dev.jsonl").read_text().splitlines():
        row=json.loads(line)
        r=suggest(engine,row["prefix"],row["profile"])
        times.append(r["ms"])
        labels=[key(i["text"]) for g in r["groups"] if g["type"]==({"my":"licenses"}.get(row["group"],row["group"])) for i in g["items"]]
        ok=bool(r["corrected"])==row["corrected"] and any(key(want) in label for label in labels for want in row["expect_any"])
        hits+=ok
        if not ok:
            print(row["id"],row["prefix"],r["corrected"],labels[:3])
    print(f"Попаданий {hits}/{len(times)} ({hits/len(times):.1%}), p95 {quantiles(times,n=100)[94]:.2f} мс")
    engine.close()

if __name__=="__main__":
    main()
