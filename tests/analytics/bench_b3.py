"""Офлайн-замеры B3. Аргумент csv создаёт потоковый вход для import-history."""
import csv
from datetime import date,timedelta
import json
from pathlib import Path
import sys
from time import perf_counter


def fixture(path):
    from kuznitsa.analytics.store import Journal
    from kuznitsa.config import Config
    j=Journal(Config().data/"kuznitsa.sqlite")
    phrases=j.rows("SELECT q_raw q,category_ctx category FROM active_history GROUP BY q_raw ORDER BY count(*) DESC,q_raw LIMIT 200")
    if not phrases:
        raise ValueError("Для распределения фраз нужна сгенерированная история.")
    days=[str(date(2026,11,20)-timedelta(days=n)) for n in range(90)]
    with Path(path).open("w",newline="") as stream:
        writer=csv.writer(stream,delimiter=";")
        writer.writerow(["Search date","Search query","Results count","Click count","Transactions","Order value","Visit ID","Segment"])
        for i in range(1_000_000):
            empty=i%11<3
            click=not empty and i%3==0
            order=click and i%17==0
            writer.writerow([days[(i//2)%90],phrases[(i//90)%200]["q"],0 if empty else 1+i%20,
                             int(click),int(order),80000+i%160001 if order else 0,"v"+str(i//2),("smb","mid","gov")[(i//2)%3]])


def naive_latency():
    import os
    from fastapi.testclient import TestClient
    from kuznitsa.app import create_app
    from kuznitsa.config import Config
    os.environ["KZ_ADMIN_OPEN"]="1"
    with TestClient(create_app(cfg=Config(rate_limit=1000))) as api:
        e=api.app.state.engine
        ranked=e.journal.rows("SELECT q_raw q FROM active_history GROUP BY q_raw ORDER BY count(*) DESC,q_raw LIMIT 200")
        queries=["антивирус для сервера","антивирус","1с","a"*1500]+[r["q"] for r in ranked]
        values=[]
        first=None
        for q in queries:
            t=perf_counter()
            resp=api.post("/api/search",json=dict(q=q,mode="naive",source="eval"))
            resp.raise_for_status()
            elapsed=(perf_counter()-t)*1000
            values.append(elapsed)
            if first is None:
                first=elapsed
        return dict(n=len(values),first_ms=round(first,2),p95_ms=round(sorted(values)[int(.95*len(values))],2),max_ms=round(max(values),2))


if __name__=="__main__":
    if len(sys.argv)>1:
        fixture(sys.argv[1])
    else:
        print(json.dumps(naive_latency()))
