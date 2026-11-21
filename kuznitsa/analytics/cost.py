import os


def _groups(j):
    columns={r["name"] for r in j.rows("PRAGMA table_info(llm_calls)")}
    groups={}
    if columns and not j.rows("SELECT 1 FROM llm_calls LIMIT 1"):
        # На импортированной истории расходы нулевые, но число поисков и отправок известно.
        groups = {r["mode"]: r for r in j.rows("""SELECT
            CASE WHEN mode='fast' THEN 'fast' ELSE 'smart_uncached' END mode,
            count(*) requests,coalesce(sum(llm_calls),0) sent,0 cached,0 usd
            FROM searches WHERE engine='kuznitsa' GROUP BY 1""")}
    elif columns:
        # В старой схеме нет sent. Движок пишет точное число отправок в searches.llm_calls
        # (включая ошибки транспорта). Отказ по бюджету не является отправкой.
        confirmed="l.sent" if "sent" in columns else "(l.cached=0 AND l.ok)" if "ok" in columns else "(l.cached=0)"
        groups={r["mode"]:r for r in j.rows(f"""WITH calls AS (
            SELECT search_id,sum({confirmed}) sent,sum(cached) cached,sum(cost_usd) usd FROM llm_calls l GROUP BY search_id
            ), requests AS (SELECT CASE WHEN s.mode='fast' THEN 'fast' WHEN cached>0 AND sent=0 THEN 'smart_cached'
                ELSE 'smart_uncached' END mode,sent,cached,usd FROM (
                SELECT s.mode,max(coalesce(s.llm_calls,0),coalesce(c.sent,0)) sent,coalesce(c.cached,0) cached,
                coalesce(c.usd,0) usd FROM searches s LEFT JOIN calls c USING(search_id) WHERE s.engine='kuznitsa'
            ) s) SELECT mode,count(*) requests,sum(sent) sent,sum(cached) cached,sum(usd) usd FROM requests GROUP BY mode""")}
    return bool(columns), groups


def report(j,daily=1000):
    from .cache import live_cached
    rate=float(os.getenv("KZ_USD_RUB","100"))
    columns, groups = live_cached(j, "cost", lambda: _groups(j))
    items=[]
    for mode in ("smart_uncached","smart_cached","fast"):
        g=groups.get(mode,{})
        rub=g.get("usd",0)*rate/(g.get("requests") or 1)
        items.append(dict(mode=mode,requests=g.get("requests",0),sent=g.get("sent",0),cached=g.get("cached",0),
                     rub_per_query=rub,rub_per_1000=rub*1000,rub_per_100000=rub*100000,monthly_rub=rub*daily*30))
    sent=sum(r["sent"] for r in items)
    cached=sum(r["cached"] for r in items)
    avg=sum(r["requests"]*r["rub_per_query"] for r in items)/(sum(r["requests"] for r in items) or 1)
    return dict(items=items,usd_rub=rate,requests_per_day=daily,sent=sent,cached=cached,cache_rate=cached/(sent+cached or 1),
                monthly_rub=avg*daily*30,rub_per_100000=avg*100000,formula="Стоимость вызовов / поиски × нагрузка за месяц; курс указан в usd_rub.",
                note="Журнал вызовов, включая служебные прогоны." if columns else "Таблица вызовов LLM ещё не создана. Зарегистрированные расходы равны нулю.")
