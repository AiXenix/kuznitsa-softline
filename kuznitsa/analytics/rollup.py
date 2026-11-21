"""Витрина на уровне одного исторического поиска с парным исходом и долей сессионных потерь."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from .kpi import facts, failed, loss_by_search
from .failures import NOISE

DIMENSIONS=("day","engine","segment","category","intent")
FIELDS="""search_id session_id ts day engine segment category intent zero clicks best_position positions first_click_s
exits reformulations carts orders leads suggested accepted corrected revenue margin reason failed noise base low assortment
peer_zero hit_before hit_after paired orders_known revenue_known clicks_known""".split()


def prepare(j):
    if j.rows("SELECT 1 FROM analytics_reports WHERE key='fact-ready'"):
        return
    with j.transaction() as db:
        if db.execute("SELECT 1 FROM analytics_reports WHERE key='fact-ready'").fetchone():
            return
        rows=facts(j)
        losses,_=loss_by_search(rows)
        runs=j.rows("SELECT id FROM active_replay")
        peers={r["q"]:json.loads(r["result"]) for r in j.rows("SELECT q,result FROM replay_results WHERE run_id=?",(runs[0]["id"],))} if runs else {}
        db.execute("DROP TABLE IF EXISTS analytics_fact")
        db.execute("CREATE TABLE analytics_fact("+",".join(FIELDS)+")")
        tz=ZoneInfo("Europe/Moscow")
        observed={r["id"]:r for r in j.rows("SELECT * FROM analytics_observation")}
        def records():
            for row in rows:
                peer=peers.get(row["q"],{})
                pair=peer.get("cases",{}).get(row["search_id"],[None,None])
                base,low=losses.get(row["search_id"],(0,0))
                row.update(day=str(datetime.fromtimestamp(row["ts"],tz).date()),failed=bool(failed(row)),noise=row["reason"] in NOISE,
                           base=base,low=low,assortment=row["reason"] in ("not_in_catalog_known","not_in_catalog_unknown","vendor_left"),
                           paired=bool(peer),peer_zero=bool(peer.get("after_zero")),hit_before=pair[0],hit_after=pair[1])
                flags=observed.get(row["search_id"],{})
                for k in ("orders","revenue","clicks"):
                    row[k+"_known"]=flags.get(k,1)
                yield tuple(row[k] for k in FIELDS)
        db.executemany("INSERT INTO analytics_fact VALUES ("+",".join("?" for _ in FIELDS)+")",records())
        for col in DIMENSIONS:
            db.execute(f"CREATE INDEX analytics_fact_{col} ON analytics_fact({col})")
        db.execute("INSERT INTO analytics_reports VALUES ('fact-ready','true')")


AGG="""count(*) searches,count(distinct session_id) sessions,avg(zero) zero_rate,count(*) behavioral_searches,
sum(failed) failed,1.*sum(failed*exits)/nullif(sum(failed),0) exit_after_failure,avg(CASE WHEN orders_known THEN orders END) conversion,
avg(carts) cart_rate,avg(CASE WHEN clicks_known THEN clicks>0 END) ctr,avg(coalesce(best_position between 1 and 3,0)) ctr_top3,
1.*sum(positions)/nullif(sum(clicks),0) mean_click_position,avg(coalesce(1./best_position,0)) mrr,avg(first_click_s) first_click_s,
avg(reformulations) reformulation_rate,avg(corrected) correction_rate,1.*sum(accepted)/nullif(sum(corrected),0) accept_rate,
avg(suggested) suggestion_rate,round(sum(revenue),2) revenue_rub,round(sum(margin),2) margin_rub,
sum(paired) paired_searches,avg(case when paired then zero end) before_zero_rate,avg(case when paired then peer_zero end) after_zero_rate,sum(orders_known) order_denominator,sum(revenue_known) revenue_denominator,sum(clicks_known) click_denominator,sum(clicks>0) clicked,sum(carts) carts,sum(orders) orders"""


def summarize(j,filters):
    from .kpi import FORMULA,RECOVERY
    prepare(j)
    where=" WHERE "+" AND ".join(k+"=?" for k in filters) if filters else ""
    params=tuple(filters.values())
    def read(fields,tail=""):
        return j.rows("SELECT "+fields+" FROM analytics_fact"+where+tail,params)
    def clean(r):
        return {k:(0 if v is None and k!="key" else v) for k,v in r.items()}
    totals=clean(read(AGG)[0])
    slices={k:[clean(row) for row in read(f"coalesce({k},'unknown') key,"+AGG," GROUP BY 1 ORDER BY 1")] for k in DIMENSIONS}
    money=read("""min(ts) start,max(ts) end,round(sum(base)) expected_rub,round(sum(low)) conservative_rub,
        round(sum(base*(1-assortment))) recoverable_existing_catalog_rub,round(sum(base*assortment)) assortment_and_bridge_gap_rub,
        count(distinct case when noise then session_id end) excluded_noise_sessions""")[0]
    scope=dict(engine="legacy",source="history",start=money.pop("start"),end=money.pop("end"),label="Обычный поиск по словам · загруженная история")
    if scope["start"] is not None:
        tz=ZoneInfo("Europe/Moscow")
        span=" — ".join(datetime.fromtimestamp(scope[k],tz).strftime("%d.%m.%Y") for k in ("start","end"))
        scope["label"]=f"Обычный поиск по словам · {span}"
    today=str(datetime.now(ZoneInfo("Europe/Moscow")).date())
    imported=bool(j.rows("SELECT 1 FROM kv WHERE key='settings:history_source' AND value='import'"))
    if imported:
        scope["label"]=scope["label"].replace("Обычный поиск по словам","Загруженная история магазина")
    last=j.rows("SELECT max(day) day FROM analytics_fact")[0]["day"] if imported else None
    for day in slices["day"]:
        day["partial"]=day["key"]>=today or (imported and day["key"]==last)
    lost=clean(money)|dict(formula_note=FORMULA,coefficients=RECOVERY)
    tiles=[dict(key=k,label=label,value=round(totals[k]*scale,2),unit=unit,note=scope["label"]) for k,label,scale,unit in [
        ("searches","Поиски",1,"шт."),("zero_rate","Без результата",100,"%"),("exit_after_failure","Уходы после неудачи",100,"%"),
        ("conversion","Из поиска в заказ",100,"%"),("revenue_rub","Выручка из поиска",1,"₽")]]
    funnel=[dict(key=k,label=v,count=totals[k]) for k,v in [("searches","Поиски"),("clicked","С кликом"),("carts","В корзину"),("orders","Заказ")]]
    peer_where=" AND paired" if where else " WHERE paired"
    buckets=read("""case when zero then 'empty' when hit_before then 'hit' else 'other' end old,
           case when peer_zero then 'empty' when hit_after then 'hit' else 'other' end new,
           count(*) n,count(hit_before) labels,sum(orders) orders,sum(failed) failed,sum(exits*failed) exits,sum(low) loss""",
           peer_where+" GROUP BY 1,2")
    from collections import Counter,defaultdict
    old=defaultdict(Counter)
    new=Counter()
    for row in buckets:
        new[row["new"]]+=row["n"]
        old[row["old"]].update({k:row[k] for k in ("n","labels","orders","failed","exits","loss")})
    def expected(key):
        return sum(new[k]*old[k][key]/old[k]["n"] for k in new if old[k]["n"])
    def total(key):
        return sum(g[key] for g in old.values())
    n=sum(new.values())
    paired_note="Одинаковые фразы, взвешенные по числу поисков."
    model="После — оценка по модели кликов. Частоты исходов истории в группах пусто, цель в топ-5, прочее × новый объём группы."
    pairs=[]
    def add(key,label,unit,before,after,better,n1,n2,note):
        provenance=("До — загруженные данные организаторов. При отсутствии исходного числа результатов используется обычный поиск по словам."
                    if imported else "До — обычный поиск по словам. Фактические значения «до» подставятся из данных Метрики организаторов при импорте.")
        pairs.append(dict(key=key,label=label,unit=unit,before=before,after=after,better=better,n_before=n1,n_after=n2,note=provenance+" "+note,before_label="Обычный поиск по словам" if not imported else "Загруженная история",after_label="Кузница"))
    if n:
        m=total("labels")
        add("zero_rate","Пустые выдачи","rate",old["empty"]["n"]/n,new["empty"]/n,"lower",n,n,paired_note)
        add("top5_hit","Цель в первых пяти","rate",old["hit"]["n"]/m if m else None,new["hit"]/m if m else None,"higher",m,m,paired_note if m else "Нет разметки целевого товара.")
        add("exit_after_fail","Уходы после неудачи","rate",total("exits")/(total("failed") or 1),expected("exits")/(expected("failed") or 1),"lower",total("failed"),round(expected("failed")),model)
        add("search_to_order","Из поиска в заказ","rate",total("orders")/n,expected("orders")/n,"higher",n,n,model)
        add("lost_orders_rub","Потери · осторожно","rub",round(total("loss")),round(expected("loss")),"lower",n,n,model+" Потери дедуплицированы по сессии.")
    latest=j.rows("SELECT id FROM active_replay")
    comparison=dict(run_id=latest[0]["id"],searches=n,before_zero=old["empty"]["n"],after_zero=new["empty"]) if latest else None
    if comparison:
        comparison["improved_top3"]=j.rows("SELECT coalesce(sum(json_extract(result,'$.improved_top3')),0) n FROM replay_results WHERE run_id=?",(comparison["run_id"],))[0]["n"] if not filters else None
    missing=[]
    if totals["order_denominator"]<totals["searches"]:
        missing.append("Заказы переданы только для части истории. Знаменатель конверсии указан в order_denominator.")
        if not totals["order_denominator"]:
            totals["conversion"]=None
            for tile in tiles:
                if tile["key"]=="conversion":
                    tile.update(value=None,note="Нет данных о заказах")
        for pair in pairs:
            if pair["key"] in ("search_to_order","lost_orders_rub"):
                pair.update(before=None,after=None,note="Нет полного наблюдения заказов в парной выборке.")
    if totals["revenue_denominator"]<totals["searches"]:
        missing.append("Выручка включает только переданные суммы. Модель потерь на неполной выручке не калибрована.")
        lost["available"]=False
    order_where=" AND orders AND revenue_known" if where else " WHERE orders AND revenue_known"
    amounts=[v["revenue"] for v in read("revenue",order_where)]
    from statistics import median
    checks=dict(orders=len(amounts),median_rub=median(amounts) if amounts else None,
                mean_rub=round(sum(amounts)/len(amounts),2) if amounts else None,max_rub=max(amounts,default=None),
                note="Заказы с известной суммой. Выручка — сумма стоимости заказанных единиц по SKU в момент заказа.")
    tiles[-1]["formula"]=checks["note"]
    return dict(order_amounts=checks,coverage_notes=missing,scope=scope,totals=totals,lost_orders=lost,tiles=tiles,comparison=comparison,slices=slices,pairs=pairs,funnel=funnel)
