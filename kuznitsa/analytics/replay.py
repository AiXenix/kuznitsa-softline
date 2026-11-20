"""Парный эксперимент на одинаковых фразах. Веса — исторические частоты."""
from collections import defaultdict
from copy import copy
from threading import Lock
import hashlib
import json
from pathlib import Path
from time import time
from kuznitsa.schema import Request
from .store import dump,result_cards


def experiment_engine(engine):
    # Прогон держит транзакцию журнала. Отдельная блокировка лексикона
    # исключает встречный порядок захвата блокировок с поиском покупателя.
    isolated=copy(engine)
    isolated._rules_lock=Lock()
    return isolated


def products(response):
    return result_cards(response)


def compare(engine, q, **kwargs):
    r=engine.search(Request(q=q,mode="fast",source="eval",**kwargs))
    return dict(search_id=r["search_id"],cards=[dict(card_id=c["card_id"],title=c["title"],
                tier=c["score"]["tier"],position=c["position"]) for c in products(r)],banners=r["banners"])


def prepare(engine,mode,limit):
    if not 1<=limit<=3000:
        raise ValueError("Размер прогона от 1 до 3000 фраз")
    j=engine.journal
    data=Path(j.path).parent
    labels={}
    path=data/"mock_truth.jsonl"
    if path.exists():
        with path.open() as stream:
            for line in stream:
                t=json.loads(line)
                labels[t["search_id"]]=t
    groups=defaultdict(list)
    digest=hashlib.sha256()
    for r in j.rows("SELECT search_id,q_raw,top_cards_json,n_cards FROM searches WHERE source='history' ORDER BY search_id"):
        groups[r["q_raw"]].append(r)
        digest.update(dump([r,labels.get(r["search_id"])]).encode())
    catalog=data/"catalog.jsonl"
    revision=engine.controls.version()
    digest.update(dump(["paired-v2",mode,limit,revision,catalog.stat().st_mtime_ns if catalog.exists() else 0]).encode())
    ident=digest.hexdigest()[:24]
    selected=sorted(groups,key=lambda q:(-len(groups[q]),q))[:limit]
    with j.transaction() as db:
        db.execute("INSERT OR IGNORE INTO replays VALUES (?,?,?,?,?)",(ident,mode,digest.hexdigest(),len(selected),time()))
    return ident,selected,groups,labels,revision


def execute(engine,mode,plan):
    engine=experiment_engine(engine)
    j=engine.journal
    ident,selected,groups,labels,revision=plan
    done={r["q"] for r in j.rows("SELECT q FROM replay_results WHERE run_id=?",(ident,))}
    for q in selected:
        if q in done:
            continue
        with j.transaction() as db:
            if engine.controls.version()!=revision:
                db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",("settings:replay:"+ident,
                           "Правила изменились во время сравнения. Запустите новый прогон с текущей версией.",time()))
                return
            if db.execute("SELECT 1 FROM replay_results WHERE run_id=? AND q=?",(ident,q)).fetchone():
                continue
            response=engine.search(Request(q=q,source="replay",mode=mode,page_size=10))
            cards=[c["card_id"] for c in products(response)]
            rows=groups[q]
            oldzero=sum(r["n_cards"]==0 for r in rows)
            hit3=before5=after5=labeled=0
            for r in rows:
                target=labels.get(r["search_id"],{})
                family=target.get("target_family")
                category=target.get("target_category")
                if not (family or category):
                    continue
                wanted=engine.catalog.by["family"].get(family,set()) if family else engine.catalog.by["category"].get(category,set())
                labeled+=1
                before=json.loads(r["top_cards_json"] or "[]")
                before5+=bool(wanted.intersection(before[:5]))
                after5+=bool(wanted.intersection(cards[:5]))
                hit3+=bool(not wanted.intersection(before[:3]) and wanted.intersection(cards[:3]))
            result=dict(q=q,frequency=len(rows),before_zero=oldzero,after_zero=0 if cards else len(rows),
                        recovered=oldzero if cards else 0,improved_top3=hit3,before_top5=before5,after_top5=after5,
                        labeled=labeled,search_id=response["search_id"],first=cards[:3])
            db.execute("INSERT INTO replay_results VALUES (?,?,?)",(ident,q,dump(result)))


def run(engine,mode="fast",limit=3000):
    plan=prepare(engine,mode,limit)
    execute(engine,mode,plan)
    return summary(engine.journal,plan[0])


def summary(j,ident):
    runs=j.rows("SELECT * FROM replays WHERE id=?",(ident,))
    if not runs:
        raise KeyError(ident)
    rows=[json.loads(x["result"]) for x in j.rows("SELECT result FROM replay_results WHERE run_id=? ORDER BY q",(ident,))]
    totals={k:sum(r[k] for r in rows) for k in ("frequency","before_zero","after_zero","improved_top3","recovered","before_top5","after_top5","labeled")}
    from .kpi import facts, loss_by_search
    history=[r for r in facts(j) if r["source"]=="history"]
    loss,_=loss_by_search(history)
    recovered_queries={r["q"] for r in rows if r["recovered"]}
    recovered_rub=sum(loss.get(r["search_id"],(0,0))[1] for r in history
                      if r["zero"] and r["q"] in recovered_queries)
    note=j.rows("SELECT value FROM kv WHERE key=?",("settings:replay:"+ident,))
    return dict(id=ident,note=note[0]["value"] if note else None,status="completed" if len(rows)==runs[0]["limit_n"] else "partial",processed=len(rows),total=runs[0]["limit_n"],mode=runs[0]["mode"],**totals,
                estimated_rub=round(recovered_rub,2),
                formula="Осторожная оценка потерь по KPI для сессий, в которых последний неудачный поиск был пуст и при повторе нашлись карточки. Прогноз, фактических заказов после повтора нет.",
                examples=sorted((r for r in rows if r["recovered"]),key=lambda r:-r["frequency"])[:12])
