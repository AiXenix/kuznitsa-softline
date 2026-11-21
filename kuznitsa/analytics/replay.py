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
    return dict(n_cards=engine.journal.detail(r["search_id"])["n_cards"],search_id=r["search_id"],cards=[dict(card_id=c["card_id"],title=c["title"],
                tier=c["score"]["tier"],position=c["position"]) for c in products(r)],banners=r["banners"])


def prepare(engine,mode,limit):
    if limit is not None and limit<1:
        raise ValueError("Укажите положительное число фраз")
    j=engine.journal
    data=Path(j.path).parent
    dataset=j.rows("SELECT value,updated FROM kv WHERE key='settings:history_source'")
    from .lineage import snapshot
    stamp,note=snapshot(j)
    if note:
        raise ValueError(note)
    labels={}
    path=data/"mock_truth.jsonl"
    if path.exists() and (not dataset or dataset[0]["value"]=="mock"):
        with path.open() as stream:
            for line in stream:
                t=json.loads(line)
                labels[t["search_id"]]=t
    if dataset and dataset[0]["value"]=="import":
        for event in j.rows("""SELECT e.search_id,e.type,e.card_id,e.offer_id,e.position FROM events e JOIN active_history s USING(search_id)
                               WHERE e.type IN ('click','order') ORDER BY e.type='order',e.ts"""):
            offer=engine.catalog.offers_by_id.get(event["offer_id"])
            card=offer.card_id if offer else event["card_id"]
            if card in engine.catalog.cards:
                previous=labels.get(event["search_id"],{})
                position=event["position"]
                if position is None and previous.get("target_card")==card:
                    position=previous.get("position")
                labels[event["search_id"]]=dict(target_card=card,position=position)
        if j.rows("SELECT 1 FROM sqlite_master WHERE name='analytics_targets'"):
            for r in j.rows("SELECT t.* FROM analytics_targets t JOIN active_history s ON s.search_id=t.id"):
                labels[r["id"]]=dict(target_card=r["card_id"],position=r["position"])
    from .kpi import facts,loss_by_search
    if j.rows("SELECT 1 FROM analytics_reports WHERE key='packed'"):
        losses={r["id"]:(0,r["low"]) for r in j.rows("SELECT search_id id,low FROM analytics_fact WHERE low>0")}
    else:
        losses,_=loss_by_search(facts(j))
    groups=defaultdict(list)
    digest=hashlib.sha256()
    for r in j.rows("SELECT search_id,q_raw,top_cards_json,n_cards FROM active_history ORDER BY search_id"):
        r["session_loss_low"]=round(losses.get(r["search_id"],(0,0))[1],4)
        groups[r["q_raw"]].append(r)
        digest.update(dump([r,labels.get(r["search_id"])]).encode())
    catalog=data/"catalog.jsonl"
    revision=engine.controls.version()
    digest.update(dump([stamp,mode,limit,revision,catalog.stat().st_mtime_ns if catalog.exists() else 0]).encode())
    ident=digest.hexdigest()[:24]
    selected=sorted(groups,key=lambda q:(-len(groups[q]),q))[:limit]
    with j.transaction() as db:
        db.execute("""INSERT OR IGNORE INTO kv SELECT 'settings:active_replay',coalesce((SELECT id FROM replays ORDER BY created DESC LIMIT 1),''),?""",(time(),))
        db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",("settings:paired_build:"+ident,dump(stamp),time()))
        db.execute("INSERT OR IGNORE INTO replays VALUES (?,?,?,?,?)",(ident,mode,digest.hexdigest(),len(selected),time()))
    return ident,selected,groups,labels,revision,dataset


def execute(engine,mode,plan):
    engine=experiment_engine(engine)
    j=engine.journal
    ident,selected,groups,labels,revision,dataset=plan
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
            cases={}
            for r in rows:
                target=labels.get(r["search_id"],{})
                family=target.get("target_family")
                category=target.get("target_category")
                if not (family or category or target.get("target_card")):
                    continue
                wanted=engine.catalog.by["family"].get(family,set()) if family else engine.catalog.by["category"].get(category,set())
                if target.get("target_card"):
                    wanted={target["target_card"]}
                labeled+=1
                before=json.loads(r["top_cards_json"] or "[]")
                def correct(ids,offer_ids):
                    if not target.get("retail"):
                        return bool(wanted.intersection(ids))
                    for oid in offer_ids:
                        o=engine.catalog.offers_by_id.get(oid)
                        if o and o.available and not o.price_on_request and o.price and o.card_id in wanted and o.lic.action=="new" and o.lic.audience=="business" and o.lic.term_months in (12,None):
                            return True
                    return False
                old=correct(before[:5],target.get("legacy_offers",[]))
                if target.get("position") and target.get("target_card"):
                    old=1<=target["position"]<=5
                new=correct(cards[:5],[c.get("offer",{}).get("offer_id") for c in products(response)[:5]])
                cases[r["search_id"]]=[old,new]
                before5+=old
                after5+=new
                hit3+=int(not correct(before[:3],target.get("legacy_offers",[])[:3]) and correct(cards[:3],[c.get("offer",{}).get("offer_id") for c in products(response)[:3]]))
            result=dict(q=q,cases=cases,recovered_rub=sum(r["session_loss_low"] for r in rows if r["n_cards"]==0 and cards),analogs=any(b["type"]=="analogs" and b.get("items") for b in response["blocks"]),frequency=len(rows),before_zero=oldzero,after_zero=0 if cards else len(rows),
                        recovered=oldzero if cards else 0,improved_top3=hit3,before_top5=before5,after_top5=after5,
                        labeled=labeled,search_id=response["search_id"],first=cards[:3])
            db.execute("INSERT INTO replay_results VALUES (?,?,?)",(ident,q,dump(result)))


    with j.transaction() as db:
        from .lineage import warning
        if warning(j,ident) or dataset!=j.rows("SELECT value,updated FROM kv WHERE key='settings:history_source'") or engine.controls.version()!=revision:
            db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",("settings:replay:"+ident,
                       "Во время прогона изменилась история или правила. Запустите сравнение для нового снимка.",time()))
            return
        db.execute("DELETE FROM kv WHERE key=?",("settings:replay:"+ident,))
        active=db.execute("SELECT value FROM kv WHERE key='settings:active_replay'").fetchone()
        if not active or active[0]!=ident:
            db.execute("INSERT OR REPLACE INTO kv VALUES ('settings:active_replay',?,?)",(ident,time()))
            db.execute("DELETE FROM analytics_reports")
            db.execute("UPDATE analytics_revision SET revision=revision+1")


def run(engine,mode="fast",limit=None):
    plan=prepare(engine,mode,limit)
    execute(engine,mode,plan)
    return summary(engine.journal,plan[0])


def summary(j,ident):
    from .cache import cached
    from .lineage import warning
    runs=j.rows("SELECT mode,limit_n FROM replays WHERE id=?",(ident,))
    if not runs:
        raise KeyError(ident)
    note=warning(j,ident)
    if note:
        return dict(id=ident,status="incompatible",note=note,mode=runs[0]["mode"],total=runs[0]["limit_n"],examples=[])
    return cached(j,"summary:" + ident,lambda:_summary(j,ident))


def _summary(j,ident):
    runs=j.rows("SELECT * FROM replays WHERE id=?",(ident,))
    if not runs:
        raise KeyError(ident)
    rows=[json.loads(x["result"]) for x in j.rows("SELECT result FROM replay_results WHERE run_id=? ORDER BY q",(ident,))]
    totals={k:sum(r[k] for r in rows) for k in ("frequency","before_zero","after_zero","improved_top3","recovered","before_top5","after_top5","labeled")}
    if all("recovered_rub" in r for r in rows):
        recovered_rub=sum(r["recovered_rub"] for r in rows)
    else:
        from .kpi import facts,loss_by_search
        history=facts(j)
        loss,_=loss_by_search(history)
        phrases={r["q"] for r in rows if r["recovered"]}
        recovered_rub=sum(loss.get(r["search_id"],(0,0))[1] for r in history if r["zero"] and r["q"] in phrases)
    note=j.rows("SELECT value FROM kv WHERE key=?",("settings:replay:"+ident,))
    return dict(id=ident,note=note[0]["value"] if note else None,status="completed" if len(rows)==runs[0]["limit_n"] and not note else "partial",processed=len(rows),total=runs[0]["limit_n"],mode=runs[0]["mode"],**totals,
                estimated_rub=round(recovered_rub,2),
                formula="Осторожная оценка потерь по KPI для сессий, в которых последний неудачный поиск был пуст и при повторе нашлись карточки. Прогноз, фактических заказов после повтора нет.",
                examples=sorted(({k:v for k,v in r.items() if k!="cases"} for r in rows if r["recovered"]),key=lambda r:-r["frequency"])[:12])
