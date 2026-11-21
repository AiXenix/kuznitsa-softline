"""Подготовка представлений консоли после загрузки данных."""
from collections import Counter,defaultdict
from . import kpi,gaps,replay
from .cache import cached
from .failures import CANONICAL,LABELS

LIVE="'ui','api','gallery','compare'"


def query_rows(j,kind):
    return cached(j,"queries:"+kind,lambda:kpi.queries(kpi.facts(j),kind,500))


def recent(j,limit,rate):
    return j.rows(f"""SELECT ts,q_raw q,search_id,client_id profile_id,segment,mode,engine,intent,n_cards,ms,
        coalesce(llm_cost_usd,0)*? cost_rub,llm_cost_usd,case when zero then fail_reason end zero_reason,source FROM searches WHERE source IN ({LIVE})
        ORDER BY ts DESC LIMIT ?""",(rate,limit))


def failure_rows(j):
    def history():
        if j.rows("SELECT 1 FROM analytics_reports WHERE key='packed'"):
            sql="""SELECT engine,coalesce(reason,case when zero then 'unknown_term' else 'ambiguous' end) key,
                count(*) n,q,min(search_id) search_id FROM analytics_detail WHERE reason IS NOT NULL OR zero
                OR (NOT clicks AND (exits OR reformulations)) GROUP BY engine,key"""
            counts=Counter()
            examples={}
            for row in j.rows(sql):
                key=(row["engine"],CANONICAL.get(row["key"],row["key"]))
                counts[key]+=row["n"]
                examples[key]=dict(q=row["q"],search_id=row["search_id"])
            return [dict(engine=e,reason=k,label=LABELS.get(k,k),count=n,example=examples[e,k]["q"],
                         search_id=examples[e,k]["search_id"],examples=[examples[e,k]],scope="history") for (e,k),n in counts.most_common()]
        rows=kpi.facts(j)
        grouped=defaultdict(Counter)
        examples={}
        for r in rows:
            if not (r["reason"] or kpi.failed(r)):
                continue
            raw=r["reason"]
            reason=CANONICAL.get(raw,raw) if raw else "unknown_term" if r["zero"] else "ambiguous"
            grouped[r["engine"]][reason]+=1
            examples.setdefault((r["engine"],reason),dict(q=r["q"],search_id=r["search_id"]))
        return [dict(engine=engine,reason=k,label=LABELS.get(k,k),count=v,example=examples[(engine,k)]["q"],
                     search_id=examples[(engine,k)]["search_id"],examples=[examples[(engine,k)]],scope="history")
                for engine,c in grouped.items() for k,v in c.most_common()]
    items=cached(j,"failures:b2-history",history)
    # Показы текущего движка в парном прогоне взвешены исходной частотой.
    def paired():
        counts=Counter()
        examples={}
        for r in j.rows("""SELECT s.q_raw q,s.search_id,s.fail_reason,json_extract(rr.result,'$.frequency') n
            FROM replay_results rr JOIN searches s ON s.search_id=json_extract(rr.result,'$.search_id')
            WHERE rr.run_id=(SELECT id FROM active_replay) AND s.zero=1"""):
            understood=j.detail(r["search_id"]).get("understood",{})
            k=understood.get("zero_reason") or CANONICAL.get(r["fail_reason"],r["fail_reason"]) or "unknown_term"
            counts[k]+=r["n"]
            examples.setdefault(k,dict(q=r["q"],search_id=r["search_id"]))
        return [dict(engine="kuznitsa",reason=k,label=LABELS.get(k,k),count=v,example=examples[k]["q"],
                     search_id=examples[k]["search_id"],examples=[examples[k]],scope="paired") for k,v in counts.most_common()]
    other=cached(j,"failures:b2.1-paired",paired)
    return dict(items=items,by_engine=dict(legacy=items,kuznitsa=other),reasons=sorted((set(LABELS)-set(CANONICAL))|{"ambiguous"}),
                zero_reasons=sorted(("off_topic","unknown_term","not_in_catalog","vendor_left","filters_too_strict","qty_out_of_range","no_available_offer")),
                note="История охватывает все поиски. Для Кузницы причины вычислены на парной выборке с учётом частот. Уход без установленной причины учитывается отдельно.")


def warm(e):
    j=e.journal
    if kpi.report(j).get("data_status")=="incompatible":
        return
    packed=bool(j.rows("SELECT 1 FROM analytics_reports WHERE key='packed'"))
    # Редкие срезы обслуживаются индексом, крупные готовим до открытия консоли.
    from itertools import combinations
    table="analytics_pack" if packed else "analytics_fact"
    axes=("day","segment","category","intent") if packed else ("segment","category","intent")
    for size in range(1,len(axes)+1):
        for keys in combinations(axes,size):
            cols=",".join(keys)
            for group in j.rows(f"SELECT {cols} FROM {table} GROUP BY {cols} HAVING count(*)>=2000"):
                if all(group.values()):
                    kpi.report(j,**group)
    if packed:
        end=j.rows("SELECT max(end_ts) t FROM analytics_pack")[0]["t"] or 0
        query_stats=j.rows("""SELECT q,count(*) count,sum(zero) zero,sum(clicks>0) clicks,sum(reformulations) reformulated,
            sum(ts>?) recent,sum(ts>? AND ts<=?) previous,min(search_id) search_id FROM analytics_detail GROUP BY q""",
            (end-30*86400,end-60*86400,end-30*86400))
        for r in query_stats:
            r["growth"]=(r["recent"]-r["previous"])/max(1,r["previous"])
        for kind,rank in (("top",lambda r:r["count"]),("zero",lambda r:r["zero"]),("low_ctr",lambda r:1-r["clicks"]/r["count"]),
                         ("rising",lambda r:r["recent"]-r["previous"]),("reformulated",lambda r:r["reformulated"])):
            ordered=sorted((r for r in query_stats if rank(r)>0),key=lambda r:(-rank(r),-r["count"],r["q"]))
            cached(j,"queries:"+kind,lambda:ordered[:500])
        failure_rows(j)
        gaps.report(e)
        for r in j.rows("SELECT id FROM active_replay"):
            replay.summary(j,r["id"])
        return
    rows=kpi.facts(j)
    for kind in ("top","zero","low_ctr","rising","reformulated"):
        cached(j,"queries:"+kind,lambda:kpi.queries(rows,kind,500))
    failure_rows(j)
    gaps.report(e)
    for r in j.rows("SELECT id FROM active_replay"):
        replay.summary(j,r["id"])


def search_reference(engine,q):
    """Последний разбор фразы и канонические карточки для сравнения режимов."""
    import json
    from .store import result_cards
    journal=engine.journal
    rows=journal.rows("SELECT search_id FROM searches WHERE q_raw=? ORDER BY ts DESC,search_id DESC LIMIT 1",(q,))
    if not rows:
        return None
    result=journal.detail(rows[0]["search_id"])
    def canonical(key):
        offer=engine.catalog.offers_by_id.get(key.removeprefix("sku:"))
        return offer.card_id if offer else key
    if result.get("archived_summary"):
        items=[dict(card_id=canonical(key),position=i) for i,key in enumerate(json.loads(result["top_cards_json"] or "[]"),1)]
    else:
        items=[dict(card_id=c.get("card_ref") or canonical(c["card_id"]),position=c["position"],
                    offer_id=(c.get("offer") or {}).get("offer_id")) for c in result_cards(result)]
    return dict(search_id=result["search_id"],items=items)


def history_days(journal):
    snapshot=kpi.report(journal)
    days=[{key:r[key] for key in ("key","searches","zero_rate")} for r in snapshot["slices"]["day"]]
    return dict(items=days,period=dict(start=days[0]["key"] if days else None,end=days[-1]["key"] if days else None))
