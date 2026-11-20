from collections import Counter, defaultdict
from datetime import datetime
from statistics import median
from zoneinfo import ZoneInfo
from .failures import NOISE

RECOVERY = {
    "vocabulary_gap":(.8,.55),"typo_unfixed":(.8,.55),"ranking_issue":(.7,.45),"content_gap":(.7,.45),
    "filters_too_strict":(.7,.45),"sku_not_found":(.5,.3),"ambiguous":(.5,.3),"price_on_request_only":(.45,.25),
    "not_in_catalog_known":(.55,.3),"not_in_catalog_unknown":(.25,.1),"vendor_left":(.35,.2)}
FORMULA = ("Одна неудачная сессия без корзины, заказа и заявки × конверсия успешных сессий × "
           "медианный чек × коэффициент причины. База от 20 сессий по сегменту, категории и сценарию, "
           "затем по сегменту и категории, сегменту или всему журналу. Для ушедших вендоров используется положительная разница конверсий показов аналогов в категории; без обеих групп оценка равна нулю.")


def facts(j):
    return j.read_report("""SELECT s.search_id,s.ts,coalesce(nullif(s.session_id,''),s.search_id) session_id,s.client_id,
        s.segment,s.source,s.engine,s.intent,s.category_ctx category,s.q_raw q,coalesce(s.fail_reason,case
        when min(case when e.type='click' then e.position end)>5 then 'ranking_issue' end) reason,s.zero,
        s.q_corrected!=s.q_norm corrected,s.blocks_json,s.filters_json,s.top_cards_json,
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
        FROM searches s LEFT JOIN events e USING(search_id)
        WHERE source IN ('history','ui','replay') GROUP BY s.search_id""")


def failed(r):
    return r["zero"] or (not r["clicks"] and (r["exits"] or r["reformulations"]))


def loss_by_search(rows):
    sessions=defaultdict(list)
    for r in rows:
        if r["source"]!="replay":
            sessions[r["session_id"]].append(r)
    bridge=defaultdict(lambda:[0,0,0,0])
    benchmarks=defaultdict(lambda:[0,[]])
    losses=[]
    excluded=0
    for group in sessions.values():
        r=max(group,key=lambda x:x["ts"])
        key=(r["segment"],r["category"],r["intent"])
        if any('"analogs"' in (x["blocks_json"] or "") for x in group if "blocks_json" in x):
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
            losses.append(r)
    rates={key:(n,len(checks)/n*(median(checks) if checks else 0)) for key,(n,checks) in benchmarks.items()}
    result={}
    for r in losses:
        key=(r["segment"],r["category"],r["intent"])
        rate=next((rates[key[:n]][1] for n in (3,2,1) if rates.get(key[:n],(0,))[0]>=20),rates.get((),(0,0))[1])
        reason=r["reason"] or "ambiguous"
        factors=RECOVERY.get(reason,(0,0))
        if reason=="vendor_left":
            total,ordered,left,left_ordered=bridge[r["category"]]
            checks=benchmarks[key[:1]][1]
            rate=max(0,ordered/total-left_ordered/left)*median(checks) if total and left and checks else 0
        result[r["search_id"]]=tuple(rate*k for k in factors)
    return result,excluded


def metrics(rows):
    n=len(rows)
    def total(k):
        return sum(r[k] or 0 for r in rows)
    observed=[r for r in rows if r["source"]!="replay"]
    traffic=len(observed)
    failed_n=sum(bool(failed(r)) for r in observed)
    return dict(searches=n,sessions=len({r["session_id"] for r in rows}),zero_rate=total("zero")/(n or 1),
        behavioral_searches=traffic,failed=failed_n,exit_after_failure=sum(r["exits"] for r in observed if failed(r))/(failed_n or 1),
        conversion=total("orders")/(traffic or 1),cart_rate=total("carts")/(traffic or 1),ctr=sum(r["clicks"]>0 for r in observed)/(traffic or 1),
        ctr_top3=sum(0<(r["best_position"] or 0)<=3 for r in observed)/(traffic or 1),mean_click_position=total("positions")/(total("clicks") or 1),
        mrr=sum(1/r["best_position"] for r in observed if r["best_position"])/(traffic or 1),
        first_click_s=total("first_click_s")/(sum(r["clicks"]>0 for r in rows) or 1),reformulation_rate=total("reformulations")/(traffic or 1),
        correction_rate=total("corrected")/(n or 1),accept_rate=total("accepted")/(total("corrected") or 1),
        suggestion_rate=total("suggested")/(n or 1),revenue_rub=round(total("revenue"),2),margin_rub=round(total("margin"),2))


def report(j, **filters):
    all_rows=facts(j)
    latest=j.rows("SELECT id FROM replays ORDER BY created DESC LIMIT 1")
    if latest:
        current={r["id"] for r in j.rows("SELECT json_extract(result,'$.search_id') id FROM replay_results WHERE run_id=?",(latest[0]["id"],))}
        all_rows=[r for r in all_rows if r["source"]!="replay" or r["search_id"] in current]
    loss,excluded=loss_by_search(all_rows)
    if filters.get("day"):
        for r in all_rows:
            r["day"]=str(datetime.fromtimestamp(r["ts"],ZoneInfo("Europe/Moscow")).date())
    rows=[r for r in all_rows if all(r.get(k)==v for k,v in filters.items() if v)]
    groups=defaultdict(lambda:defaultdict(list))
    tz=ZoneInfo("Europe/Moscow")
    for r in rows:
        for k in ("engine","segment","category","intent"):
            groups[k][r[k] or "unknown"].append(r)
        groups["day"][str(datetime.fromtimestamp(r["ts"],tz).date())].append(r)
    totals=metrics(rows)
    existing=assortment=conservative=0
    for r in rows:
        base,low=loss.get(r["search_id"],(0,0))
        if r["reason"] in ("not_in_catalog_known","not_in_catalog_unknown","vendor_left"):
            assortment+=base
        else:
            existing+=base
        conservative+=low
    lost=dict(expected_rub=round(existing+assortment),conservative_rub=round(conservative),
              recoverable_existing_catalog_rub=round(existing),assortment_and_bridge_gap_rub=round(assortment),
              excluded_noise_sessions=len({r["session_id"] for r in rows if r["reason"] in NOISE}),
              formula_note=FORMULA,coefficients=RECOVERY)
    tiles=[dict(key=k,label=label,value=round(totals[k]*scale,2),unit=unit) for k,label,scale,unit in [
        ("searches","Поиски",1,"шт."),("zero_rate","Без результата",100,"%"),("exit_after_failure","Уходы после неудачи",100,"%"),
        ("conversion","Из поиска в заказ",100,"%"),("revenue_rub","Выручка из поиска",1,"₽")]]
    comparison=None
    if latest:
        comparison=j.rows("""SELECT sum(json_extract(result,'$.frequency')) searches,
            sum(json_extract(result,'$.before_zero')) before_zero,sum(json_extract(result,'$.after_zero')) after_zero,
            sum(json_extract(result,'$.improved_top3')) improved_top3 FROM replay_results WHERE run_id=?""",(latest[0]["id"],))[0]
        comparison["run_id"]=latest[0]["id"]
    return dict(totals=totals,lost_orders=lost,tiles=tiles,comparison=comparison,slices={k:[dict(key=v,**metrics(g)) for v,g in sorted(d.items())] for k,d in groups.items()})


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
