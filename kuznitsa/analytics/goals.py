"""Дневные цели Метрики и события, связанные с поисками, в часовом поясе магазина."""
import json
from datetime import datetime
from time import time
from zoneinfo import ZoneInfo

from .store import dump

STAGES = {"cart": ("carts", "Корзина"), "order": ("orders", "Заказ"), "lead": ("leads", "Заявка")}
KEY = "settings:metrika_goals"
MSK = ZoneInfo("Europe/Moscow")


def local_day(ts):
    return datetime.fromtimestamp(ts, MSK).date().isoformat()


def reconcile(journal, reports):
    goal_reports = [r for r in reports if r.get("kind") == "metrika_goals"]
    saved = journal.rows("SELECT value FROM kv WHERE key=?", (KEY,))
    if not goal_reports and not saved:
        return

    # Сопоставляем только дни, для которых есть агрегаты. Ноль заказов в журнале
    # с колонкой заказа является наблюдением даже при полном отсутствии покупок.
    observed = {r["day"]: r["known"] for r in journal.rows("""
        SELECT date(s.ts,'unixepoch','+3 hours') day, max(coalesce(o.orders,0)) known
        FROM active_history s LEFT JOIN analytics_observation o ON o.id=s.search_id GROUP BY day""")}
    events = {}
    for row in journal.rows("""
        SELECT date(e.ts,'unixepoch','+3 hours') day, e.type stage, count(*) n
        FROM events e JOIN active_history s USING(search_id)
        WHERE e.type IN ('cart','order','lead') GROUP BY day,e.type"""):
        events.setdefault(row["day"], {})[row["stage"]] = row["n"]
    coverage = []
    for r in reports:
        if r.get("kind")=="metrika_goals" or r.get("summary_only") or not r.get("period"):
            continue
        fields = set(r.get("fields", []))
        stages = set()
        if fields.intersection({"cart", "cart_product"}):
            stages.add("cart")
        if "lead" in fields or r.get("kind")=="crm_leads":
            stages.add("lead")
        coverage.append((local_day(r["period"][0]), local_day(r["period"][1]), stages))

    days = {}
    for report in goal_reports:
        comparison = {}
        different = set()
        for day, measures in sorted(report["goals_by_day"].items()):
            known = set(events.get(day, {}))
            if observed.get(day):
                known.add("order")
            if day in observed:
                for start, end, stages in coverage:
                    if start <= day <= end:
                        known.update(stages)
            for stage, count in measures.items():
                actual = events.get(day, {}).get(stage, 0) if stage in known else None
                if actual is not None:
                    pair = comparison.setdefault(stage, [0, 0])
                    pair[0] += count
                    pair[1] += actual
                    if count != actual:
                        different.add(day)
                # Последняя выгрузка одного дня и цели заменяет прежнюю.
                days.setdefault(day, {})[stage] = dict(metrika=count, journal=actual,
                    count=count if actual is None else actual,
                    source="journal" if actual is not None else "metrika_goals", file=report["file"])
        text = ", ".join(f"{STAGES[k][1].lower()} {a} / {b} (Δ {a-b:+d})"
                         for k, (a,b) in comparison.items())
        note = (f"Сверка целей (Метрика / журнал) · {text}. Дней с расхождениями — {len(different)}."
                if comparison else "Для сверки нет наблюдаемых этапов в журнале за эти даты. Воронка использует дневные цели Метрики.")
        previous_note = report.get("reconciliation_text")
        report["missing"] = [v for v in report.get("missing", []) if v != previous_note] + [note]
        report.update(reconciliation_text=note, comparison={k:dict(metrika=a,journal=b,delta=a-b)
                                                            for k,(a,b) in comparison.items()})
        journal.db.execute("UPDATE kv SET value=? WHERE key=?", (dump(report), "settings:import-report:"+report["file"]))

    body = dump(dict(goals=days, events=events))
    if not saved or saved[0]["value"] != body:
        if days:
            journal.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)", (KEY, body, time()))
        elif saved:
            journal.db.execute("DELETE FROM kv WHERE key=?", (KEY,))
        journal.db.execute("DELETE FROM analytics_reports WHERE key GLOB 'kpi-*' OR key GLOB 'dashboard:ready-*'")
        journal.db.execute("UPDATE analytics_revision SET revision=revision+1")


def apply_to_funnel(journal, result, filters):
    if set(filters) - {"day"}:
        return
    saved = journal.rows("SELECT value FROM kv WHERE key=?", (KEY,))
    if not saved:
        return
    series = json.loads(saved[0]["value"])
    days = series["goals"]
    events = series["events"]
    if filters.get("day"):
        start = end = filters["day"]
        days = {k:v for k,v in days.items() if k==start}
    elif result["scope"]["start"] is not None:
        start, end = (local_day(result["scope"][k]) for k in ("start","end"))
        days = {k:v for k,v in days.items() if start <= k <= end}
    else:
        start, end = min(days), max(days)
    if not days:
        return
    if result["comparison"]:
        # Агрегаты за день нельзя приписать выборочному повтору части фраз.
        historical = journal.rows("SELECT count(*) n FROM active_history" +
            (" WHERE date(ts,'unixepoch','+3 hours')=?" if filters else ""), tuple(filters.values()))[0]["n"]
        if historical != result["totals"]["searches"]:
            return
    result["funnel_daily"] = [dict(day=day, stages=days[day]) for day in sorted(days)]
    steps = {step["key"]: step for step in result["funnel"]}
    for stage, (key, label) in STAGES.items():
        fallback = [v[stage]["metrika"] for v in days.values() if stage in v and v[stage]["source"]=="metrika_goals"]
        if not fallback:
            continue
        step = steps[key]
        linked = sum(v.get(stage, 0) for day,v in events.items() if start <= day <= end)
        step.update(count=linked+sum(fallback), observed=True, metrika_count=sum(fallback),
                    label=label+" · включая дневные цели Метрики")
        if stage in {"order","lead"}:
            steps["orders_or_leads"]["label"] = "Поиски со связанным заказом или заявкой · только журнал"
    result["coverage_notes"].append("Дневные цели Метрики учитываются по этапам без наблюдений. Они не привязаны к отдельным поискам и не входят в конверсию поиска или выручку.")
    if not result["totals"]["searches"]:
        result["scope_text"] = f"Цели Метрики · {min(days)} — {max(days)} · дневные достижения"
