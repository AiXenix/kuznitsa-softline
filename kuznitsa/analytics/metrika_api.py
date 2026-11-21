"""Сводные страницы /stat/v1/data. Одна строка соответствует набору измерений."""
import hashlib
import json
from collections import Counter
from functools import lru_cache
from math import isfinite

from .store import dump


def read_page(path):
    with path.open(encoding="utf-8-sig") as stream:
        obj = json.load(stream)
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), list):
        return
    query = obj.get("query")
    if isinstance(query, dict) and all(isinstance(query.get(k), list) and
            all(isinstance(name, str) for name in query[k]) for k in ("dimensions", "metrics")):
        if any(name.startswith("ym:") for name in query["dimensions"] + query["metrics"]):
            return obj


@lru_cache(64)
def page_columns(path, modified_ns, size):
    """Кэшируем только заголовки страниц; день сборки вызывает sniff несколько раз."""
    try:
        page = read_page(path)
    except (ValueError, UnicodeError):
        return None
    if page is not None:
        query = page["query"]
        return {**dict.fromkeys(query["dimensions"],"dimension"), **dict.fromkeys(query["metrics"],"metric")}


def signature(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def save_page(db, path, page):
    query = page["query"]
    identity = {k: v for k, v in query.items() if k not in {"limit", "offset", "sort"}}
    ident = signature(identity)
    db.execute("""CREATE TABLE IF NOT EXISTS metrika_api_pages(
        report TEXT, page TEXT, file TEXT, data TEXT, PRIMARY KEY(report,page))""")
    # При наличии offset новый снимок той же страницы заменяет предыдущий.
    key = str(query["offset"]) if "offset" in query else path.name
    db.execute("INSERT OR REPLACE INTO metrika_api_pages VALUES (?,?,?,?)",
               (ident, key, path.name, dump({k: page.get(k) for k in ("data","totals","total_rows","sampled")})))
    return ident, identity, key


def combine(db, ident, identity, phrase_from_url):
    dimensions, metrics = identity["dimensions"], identity["metrics"]
    files, seen, reasons = [], {}, Counter()
    receipts = {}
    sampled = False
    totals, expected = [], set()
    read = duplicates = conflicts = 0
    for row in db.execute("SELECT page,file,data FROM metrika_api_pages WHERE report=? ORDER BY file,page", (ident,)):
        files.append(row["file"])
        start_unique, start_dupes, previous_reasons = len(seen), duplicates, reasons.copy()
        data = json.loads(row["data"])
        sampled |= bool(data.get("sampled"))
        if isinstance(data.get("total_rows"), int):
            expected.add(data["total_rows"])
        if isinstance(data["totals"], list) and len(data["totals"]) == len(metrics) and data["totals"] not in totals:
            totals.append(data["totals"])
        for item in data["data"]:
            read += 1
            dims = item.get("dimensions") if isinstance(item, dict) else None
            vals = item.get("metrics") if isinstance(item, dict) else None
            if not isinstance(dims, list) or len(dims) != len(dimensions) or not all(
                    isinstance(d, dict) and ("name" in d or "id" in d) for d in dims):
                reasons["Некорректные измерения"] += 1
                continue
            if not isinstance(vals, list) or len(vals) != len(metrics) or not all(
                    v is None or type(v) in (int, float) and isfinite(v) for v in vals):
                reasons["Некорректные показатели"] += 1
                continue
            dim_key = tuple(str(d.get("id") if d.get("id") is not None else d.get("name")) for d in dims)
            if dim_key in seen:
                duplicates += 1
                if seen[dim_key][1] != vals:
                    conflicts += 1
                continue
            seen[dim_key] = ([str(d.get("name") or "") for d in dims], vals)

        receipts[row["page"]] = dict(file=row["file"], rows_read=len(data["data"]),
                                     rows_accepted=len(seen)-start_unique, duplicates=duplicates-start_dupes,
                                     skipped=sum((reasons-previous_reasons).values()), skip_reasons=dict(reasons-previous_reasons))

    count_metric = next((m for m in ("ym:pv:pageviews", "ym:s:visits", "ym:s:pageviews") if m in metrics), None)
    counts = {key: Counter() for key in ("external_phrases", "external_engines", "site_phrases")}
    missing_counts = set()
    for names, values in seen.values():
        dims = dict(zip(dimensions, names))
        sources = {"external_phrases": dims.get("ym:s:searchPhrase"), "external_engines": dims.get("ym:s:searchEngine")}
        if dims.get("ym:pv:URL"):
            try:
                sources["site_phrases"] = phrase_from_url(dims["ym:pv:URL"], {})
            except ValueError:
                pass
        for group, name in sources.items():
            if name and name.strip():
                value = values[metrics.index(count_metric)] if count_metric else None
                counts[group][name.strip()] += value or 0
                if value is None:
                    missing_counts.add((group,name.strip()))
    expected_rows = next(iter(expected)) if len(expected) == 1 else None
    available = {k: [dict(q=q, count=None if (k,q) in missing_counts else n, metric=count_metric)
                     for q,n in sorted(c.items(), key=lambda pair: (-pair[1], pair[0]))[:50]]
                 for k,c in counts.items()}
    external = bool(set(dimensions) & {"ym:s:searchPhrase", "ym:s:searchEngine"})
    site = bool(counts["site_phrases"])
    scope = "mixed" if site and external else "external" if external else "site" if site else "other"
    note = [f"Страниц — {len(files)}, уникальных строк — {len(seen)}. Внутренних фраз — {len(counts['site_phrases'])}, внешних — {len(counts['external_phrases'])}.",
            "Частоты относятся к строкам отчёта. Агрегаты API не добавляют поисковые сессии в воронку."]
    if sampled:
        note.append("Метрика использовала выборку.")
    if len(totals) > 1 or len(expected) > 1:
        note.append("Итоги страниц расходятся. Обновите все страницы одним снимком.")
    if conflicts:
        note.append(f"В пересечениях страниц различаются показатели строк — {conflicts}.")
    complete = expected_rows is not None and len(seen) == expected_rows and len(totals) <= 1 and not reasons and not conflicts
    if not complete:
        note.append("Полнота набора строк не подтверждена.")
    columns = {**dict.fromkeys(dimensions,"dimension"), **dict.fromkeys(metrics,"metric")}
    report = dict(kind="metrika_api", source_type="Метрика · API отчётов", file=files[0], files=files,
                  report_id=ident, pages=len(files), scope=scope, query=identity, sampled=sampled, complete=complete,
                  total_rows=expected_rows, report_metrics=dict(zip(metrics, totals[0])) if len(totals)==1 else {},
                  rows_read=read, rows_accepted=len(seen), duplicates=duplicates,
                  skipped=read-duplicates-len(seen), skip_reasons=dict(reasons), recognized=list(columns),
                  columns=columns, ignored=[], summary_only=True, searches=0, events=0, missing=note, **available)
    return report, receipts
