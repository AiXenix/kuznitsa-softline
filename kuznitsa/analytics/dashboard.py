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
    kpi.report(j)
    # Для крупных срезов заранее сохраняем также пересечения фильтров.
    # Московские дни укладываются в короткий запрос к индексированной витрине.
    from itertools import combinations
    for size in range(1,4):
        for keys in combinations(("segment","category","intent"),size):
            cols=",".join(keys)
            for group in j.rows(f"SELECT {cols} FROM analytics_fact GROUP BY {cols} HAVING count(*)>=2500"):
                if all(group.values()):
                    kpi.report(j,**group)
    rows=kpi.facts(j)
    for kind in ("top","zero","low_ctr","rising","reformulated"):
        cached(j,"queries:"+kind,lambda:kpi.queries(rows,kind,500))
    failure_rows(j)
    gaps.report(e)
    for r in j.rows("SELECT id FROM active_replay"):
        replay.summary(j,r["id"])
