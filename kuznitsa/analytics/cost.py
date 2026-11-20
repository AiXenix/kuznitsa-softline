import os


def report(j,daily=1000):
    rate=float(os.getenv("KZ_USD_RUB","100"))
    available=bool(j.rows("SELECT name FROM sqlite_master WHERE name='llm_calls' AND type='table'"))
    rows=j.rows("""SELECT s.mode,s.search_id,coalesce(sum(l.cost_usd),0) usd,
                   count(l.id) calls,coalesce(sum(l.cached),0) cache
                   FROM searches s LEFT JOIN llm_calls l USING(search_id)
                   WHERE s.engine='kuznitsa' GROUP BY s.search_id""") if available else []
    groups={"smart_uncached":[],"smart_cached":[],"fast":[]}
    for r in rows:
        key="fast" if r["mode"]=="fast" else "smart_cached" if r["calls"] and r["calls"]==r["cache"] else "smart_uncached"
        groups[key].append(r)
    items=[]
    for key,group in groups.items():
        rub=sum(r["usd"] for r in group)*rate/(len(group) or 1)
        items.append(dict(mode=key,requests=len(group),rub_per_query=rub,rub_per_1000=rub*1000,monthly_rub=rub*daily*30))
    return dict(items=items,usd_rub=rate,requests_per_day=daily,cache_rate=sum(r["cache"] for r in rows)/(sum(r["calls"] for r in rows) or 1),
                formula="Средняя стоимость поиска × поиски в сутки × 30 дней",note="Расходы по журналу вызовов" if available else "Таблица вызовов LLM ещё не создана. Зарегистрированные расходы равны нулю.")


