from collections import Counter, defaultdict
from statistics import median
from .failures import NOISE

RECOVERY = {
    "unknown_term":(.8,.55),"not_in_catalog":(.55,.3),"qty_out_of_range":(.7,.45),"no_available_offer":(.45,.25),
    "vocabulary_gap":(.8,.55),"typo_unfixed":(.8,.55),"ranking_issue":(.7,.45),"content_gap":(.7,.45),
    "filters_too_strict":(.7,.45),"sku_not_found":(.5,.3),"ambiguous":(.5,.3),"price_on_request_only":(.45,.25),
    "not_in_catalog_known":(.55,.3),"not_in_catalog_unknown":(.25,.1),"vendor_left":(.35,.2)}
FORMULA = ("Одна неудачная сессия без корзины, заказа и заявки × конверсия успешных сессий × "
           "медианный чек × коэффициент причины. База от 20 сессий по сегменту, категории и сценарию, "
           "затем по сегменту и категории, сегменту или всему журналу. Для ушедших вендоров используется положительная разница конверсий показов аналогов в категории; без обеих групп оценка равна нулю.")


FACT_SQL="""SELECT s.search_id,s.ts,coalesce(nullif(s.session_id,''),s.search_id) session_id,s.client_id,
        s.segment,s.source,s.engine,s.intent,s.category_ctx category,s.q_raw q,coalesce(s.fail_reason,case
        when min(case when e.type='click' then e.position end)>5 then 'ranking_issue' end) reason,s.zero,
        s.q_corrected normalized_query,s.q_corrected!=s.q_norm corrected,s.blocks_json,s.filters_json,s.top_cards_json,
        count(case when e.type='click' then 1 end) clicks,
        min(case when e.type='click' then e.position end) best_position,
        sum(case when e.type='click' then e.position else 0 end) positions,
        min(case when e.type='click' then e.ts-s.ts end) first_click_s,
        max(case when e.type='exit' then 1 else 0 end) exits,
        max(case when e.type='reformulate' and coalesce(e.payload_json,'{}')!='{"inherited":true}' then 1 else 0 end) reformulations,
        max(case when e.type='cart' then 1 else 0 end) carts,
        max(case when e.type='order' then 1 else 0 end) orders,
        max(case when e.type='lead' then 1 else 0 end) leads,
        max(case when e.type='suggest_click' then 1 else 0 end) suggested,
        max(case when e.type='correction_accept' then 1 else 0 end) accepted,
        sum(case when e.type='order' then coalesce(e.value,0) else 0 end) revenue,
        sum(case when e.type='order' then coalesce(e.margin_value,0) else 0 end) margin
        FROM active_history s LEFT JOIN events e USING(search_id)
        GROUP BY s.search_id"""


def facts(j):
    packed=j.rows("SELECT 1 FROM analytics_reports WHERE key='packed'")
    return j.read_report("SELECT * FROM analytics_detail" if packed else FACT_SQL)


def failed(r):
    return r["zero"] or (not r["clicks"] and (r["exits"] or r["reformulations"]))


def loss_by_search(rows):
    sessions=defaultdict(list)
    for r in rows:
        if r["source"]!="replay":
            sessions[r["session_id"]].append(r)
    return loss_by_session(sessions.values())


def loss_by_session(groups):
    bridge=defaultdict(lambda:[0,0,0,0])
    benchmarks=defaultdict(lambda:[0,[]])
    losses=[]
    excluded=0
    for group in groups:
        r=max(group,key=lambda x:x["ts"])
        key=(r["segment"],r["category"],r["intent"])
        if any('"analogs"' in (x["blocks_json"] or "") for x in group if "blocks_json" in x.keys()):
            index=2 if any(x["reason"]=="vendor_left" for x in group) else 0
            bridge[r["category"]][index]+=1
            bridge[r["category"]][index+1]+=int(any(x["orders"] for x in group))
        if any(x["reason"] in NOISE for x in group):
            excluded+=1
            continue
        converted=any(x["orders"] or x["carts"] or x["leads"] for x in group)
        if converted or any(x["clicks"] for x in group):
            revenue=sum(x["revenue"] for x in group)
            for n in range(4):
                bench=benchmarks[key[:n]]
                bench[0]+=1
                if revenue:
                    bench[1].append(revenue)
        failures=[x for x in group if failed(x)]
        if failures and not converted:
            r=max(failures,key=lambda x:x["ts"])
            losses.append((r["search_id"],(r["segment"],r["category"],r["intent"]),r["reason"] or "ambiguous"))
    rates={key:(n,len(checks)/n*(median(checks) if checks else 0)) for key,(n,checks) in benchmarks.items()}
    result={}
    for ident,key,reason in losses:
        rate=next((rates[key[:n]][1] for n in (3,2,1) if rates.get(key[:n],(0,))[0]>=20),rates.get((),(0,0))[1])
        factors=RECOVERY.get(reason,(0,0))
        if reason=="vendor_left":
            total,ordered,left,left_ordered=bridge[key[1]]
            checks=benchmarks[key[:1]][1]
            rate=max(0,ordered/total-left_ordered/left)*median(checks) if total and left and checks else 0
        result[ident]=tuple(rate*k for k in factors)
    return result,excluded


def report(j, **filters):
    import json
    from .cache import cached
    from .rollup import summarize,DIMENSIONS
    from .lineage import warning
    note=warning(j)
    if note:
        scope=dict(label="Сравнение ожидает согласованной сборки",start=None,end=None)
        return dict(data_status="incompatible",scope=scope,scope_text=scope["label"],note=note,coverage_notes=[note],
                    pairs=[],comparison=None,tiles=[],funnel=[],slices={k:[] for k in DIMENSIONS},totals={},
                    lost_orders=dict(available=False),order_amounts={})
    filters={k:v for k,v in filters.items() if v and k in DIMENSIONS}
    if filters.get("engine")=="legacy":
        del filters["engine"]
    return cached(j,"kpi-proof:"+json.dumps(filters,sort_keys=True),lambda:summarize(j,filters))


def queries(rows,kind,limit=50):
    end=max((r["ts"] for r in rows),default=0)
    groups=defaultdict(list)
    for r in rows:
        groups[r["q"]].append(r)
    items=[]
    for q,g in groups.items():
        recent=sum(r["ts"]>end-30*86400 for r in g)
        previous=sum(end-60*86400<r["ts"]<=end-30*86400 for r in g)
        vals=dict(q=q,count=len(g),zero=sum(r["zero"] for r in g),clicks=sum(bool(r["clicks"]) for r in g),
                  reformulated=sum(r["reformulations"] for r in g),recent=recent,previous=previous,
                  growth=(recent-previous)/max(1,previous),search_id=g[0]["search_id"])
        score={"top":len(g),"zero":vals["zero"],"low_ctr":1-vals["clicks"]/len(g),"reformulated":vals["reformulated"],"rising":recent-previous}[kind]
        if score>0:
            items.append((score,vals))
    return [v for _,v in sorted(items,key=lambda item:(-item[0],-item[1]["count"],item[1]["q"]))[:limit]]
