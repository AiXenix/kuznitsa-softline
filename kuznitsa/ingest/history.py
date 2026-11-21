"""Импорт потоковых таблиц и Logs API. Все изменения файла атомарны."""
import csv
import re
import ast
from functools import lru_cache
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile
import hashlib
import json
from collections import Counter
from datetime import datetime
from itertools import islice,chain
from time import time
from pathlib import Path
from math import isfinite
from urllib.parse import urlsplit,parse_qs,unquote

import yaml
from openpyxl import load_workbook
from kuznitsa.analytics.store import dump
from kuznitsa.mock.querylog_gen import MSK, describe
from kuznitsa.plans.naive import match
from kuznitsa.text import normalize,sku_key

ALIASES={
    "q":["query","поисковая фраза","поисковый запрос","запрос","ym:s:searchphrase","q_raw","text"],
    "visits":["визиты","ym:s:visits"],"bounce":["отказы","отказы, %","доля отказов","ym:s:bouncerate"],
    "count":["поиски","частота","searches"],"n_cards":["результаты","число результатов","results_count","results"],
    "zero_rate":["доля пустых выдач","zero_rate"],"ts":["дата","дата и время","timestamp","time","datetime"],
    "session_id":["визит","visitid","visit_id"],"client_id":["клиент","clientid"],"segment":["сегмент"],
    "click":["клик","клики","clicks"],"order":["заказ","заказы","orders","достижения цели: заказ оформлен"],
    "cart":["корзины","достижения цели: добавление в корзину"],"lead":["достижения цели: запрос кп"],
    "revenue":["доход (₽)","выручка","value"]}


ALIASES["q"] += ["search term","search query","keyword","search phrase","phrase","site search phrase","поиск по сайту","поисковая фраза на сайте","текст запроса","фраза поиска","поисковая фраза (внутренний поиск)","фраза","ym:s:sitesearchphrase"]
ALIASES["n_cards"] += ["result count","results count","number of results","hits","найдено","количество результатов","результатов","найдено товаров"]
ALIASES["ts"] += ["date","дата создания","created at","event time","search date","время запроса","время"]
ALIASES["order"] += ["purchases","purchase","transactions","покупки","заказ оформлен"]
ALIASES["click"] += ["click count","clicked","количество кликов","переходы"]
ALIASES["target"] = ["target card","target card id","clicked product","product id","clicked sku","offer id","артикул","товар клика","целевой товар","card id"]
ALIASES["position"] = ["click position","позиция клика","rank"]
ALIASES["session_id"] += ["visit id","session","идентификатор визита"]
ALIASES["client_id"] += ["client id","visitor id","идентификатор клиента"]
ALIASES["count"] += ["search count","количество поисков","запросы"]
ALIASES["visits"] += ["sessions","visits"]
ALIASES["revenue"] += ["sales amount","order value","оборот","сумма заказа"]

ALIASES["q"] += ["фраза внутреннего поиска","внутренний поисковый запрос","search keyword","search_term"]
ALIASES["depth"] = ["глубина","глубина просмотра","page depth","ym:s:pageDepth"]
ALIASES["ts"] += ["момент","время поиска"]
ALIASES["client_id"] += ["cookie"]
ALIASES["position"] += ["место"]
ALIASES["target"] += ["клик код","код товара клика"]
ALIASES["order_id"] = ["номер заказа","order id","purchase id"]
ALIASES["cart_product"] = ["в корзину","cart sku"]
ALIASES["revenue"] += ["сумма RUB","доход RUB"]

ALIASES["q"] += ["поисковые фразы","ym:s:searchPhrase","ym:s:siteSearchPhrase"]
ALIASES["lead_id"] = ["идентификатор заявки","номер заявки","lead id","request id","crm id"]
ALIASES["product"] = ["товар","продукт","product","product name","номенклатура"]
ALIASES["search_id"] = ["search id","идентификатор поиска"]
ALIASES["client_id"] += ["client","компания","покупатель","заказчик","customer","customer id"]
ALIASES["revenue"] += ["сумма","сумма заявки","amount","deal amount"]
GA4 = {k:k for k in ("event_name","event_timestamp","event_params","user_pseudo_id","items","ecommerce","event_date")}


LOGS={
    "ym:s:visitID":"session_id","ym:s:clientID":"client_id","ym:s:watchIDs":"hit_ids",
    "ym:s:dateTime":"ts","ym:s:date":"ts","ym:s:startURL":"start_url",
    "ym:s:purchaseID":"order_ids","ym:s:purchaseRevenue":"order_values",
    "ym:s:parsedParamsKey1":"visit_parameter_names","ym:s:parsedParamsKey2":"visit_parameter_values",
    "ym:pv:watchID":"hit_id","ym:pv:visitID":"session_id","ym:pv:clientID":"client_id",
    "ym:s:purchaseCurrency":"order_currencies","ym:s:purchasedProductID":"purchased_products","ym:s:purchasedProductQuantity":"purchased_quantities",
    "ym:pv:referer":"referrer","ym:pv:dateTime":"ts","ym:pv:URL":"search_url","ym:pv:params":"search_and_ecommerce",
}


@lru_cache(1024)
def header(v):
    return re.sub(r"[^a-zа-яё0-9]+"," ",re.sub(r"([a-z])([A-Z])",r"\1 \2",str(v)).lower()).strip()


GOAL_TITLE = re.compile(r"достижени[еяй] цел(?:и|ей)|goal (?:achievements?|completions?)", re.I)
GOAL_DATES = {"дата", "день", "дата визита", "дата достижения", "дата достижения цели", "дата визита по дням", "дата по дням",
              "период", "date", "day", "ym s date"}
GOAL_STAGES = {"cart": r"корзин|\bcart\b", "order": r"заказ|покупк|покупок|purchase|\border",
               "lead": r"заяв|запрос кп|\blead|обратн\w* звон"}


@lru_cache(512)
def goal_stage(name):
    text = header(name)
    if "%" in str(name) or re.search(r"конверси|целевые визиты|доход|ценност|conversion|rate|revenue", text):
        return None
    return next((stage for stage, pattern in GOAL_STAGES.items() if re.search(pattern, text)), None)


def goal_columns(keys, title):
    if not any(header(k) in GOAL_DATES for k in keys):
        return {}
    named = bool(GOAL_TITLE.search(title))
    columns = {}
    for key in keys:
        text = header(key)
        if text in GOAL_DATES:
            columns[key] = "ts"
        elif text in {"цель", "название цели", "наименование цели", "goal", "goal name"}:
            columns[key] = "goal_name"
        elif text in {"достижения", "количество достижений", "достижения цели", "достижение цели", "достижения целей", "число достижений", "goal completions"}:
            columns[key] = "achievements"
        elif named or GOAL_TITLE.search(text):
            stage = goal_stage(key)
            if stage:
                columns[key] = stage
    fields = set(columns.values())
    if "ts" in fields and (fields.intersection(GOAL_STAGES) or {"goal_name", "achievements"} <= fields):
        return columns
    return {}


def table_rows(rows,aliases,metadata=None):
    sample=list(islice(rows,80))
    if not sample:
        return
    goal_title = next((str(cell) for row in sample for cell in row if GOAL_TITLE.search(str(cell))), "")
    def score(row):
        return sum(header(v) in aliases or str(v).startswith("ym:") for v in row) + len(goal_columns(row, goal_title))
    index=max(range(len(sample)),key=lambda i:score(sample[i]))
    if metadata is not None:
        for row in sample[:index]:
            line=" ".join(str(v or "") for v in row)
            if GOAL_TITLE.search(line) or re.search(r"поисковые фразы|поиск по сайту|search phrases|site search",line,re.I):
                metadata["report_title"]=line.strip()
            if re.search(r"период|period|date range",line,re.I):
                dates=re.findall(r"\b(?:\d{4}-\d\d-\d\d|\d\d\.\d\d\.\d{4})\b",line)
                if len(dates)==2:
                    try:
                        start,end=(timestamp(v,0) for v in dates)
                        if start<=end:
                            metadata["declared_period"]=[start,end+86400-1]
                    except ValueError:
                        pass
    keys=list(sample[index])
    if index:
        # В Excel объединённая подпись часто занимает только верхнюю строку.
        for i,k in enumerate(keys):
            if not k and i<len(sample[index-1]):
                keys[i]=sample[index-1][i]
    if metadata is not None and metadata.get("capture_headers"):
        metadata["headers"]=[k for k in keys if k]
    for values in chain(sample[index+1:],rows):
        yield {k:v for k,v in zip(keys,values) if k}


def records(path,aliases,metadata=None):
    ext=path.suffix.lower()
    if ext==".xlsx":
        book=load_workbook(path,read_only=True,data_only=True)
        try:
            rows=iter(book.active.values)
            yield from table_rows(rows,aliases,metadata)
        finally:
            book.close()
    elif ext in {".jsonl",".ndjson",".json"}:
        with path.open(encoding="utf-8-sig") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    yield {}
    else:
        with path.open("rb") as raw:
            probe=raw.read(65536)
        try:
            import codecs
            codecs.getincrementaldecoder("utf-8-sig")().decode(probe,final=False)
            encoding="utf-8-sig"
        except UnicodeDecodeError:
            encoding="cp1251"
        with path.open(encoding=encoding,newline="") as f:
            sample=f.read(8192)
            f.seek(0)
            try:
                delim="\t" if ext==".tsv" else csv.Sniffer().sniff(sample,delimiters=";,\t").delimiter
            except csv.Error:
                def header_score(delimiter):
                    rows=csv.reader(sample.splitlines(),delimiter=delimiter)
                    return max((sum(header(c) in aliases or c.startswith("ym:") for c in r) + len(goal_columns(r, sample[:8192])) for r in rows),default=0)
                delim="\t" if ext==".tsv" else max((";",",","\t"),key=header_score)
            yield from table_rows(iter(csv.reader(f,delimiter=delim)),aliases,metadata)


def sniff(path):
    """Распознаёт содержание небольшой выборки, без загрузки файла целиком."""
    path=Path(path)
    unknown=dict(kind="unknown",confidence=0.0,columns={},reason="Нет признаков журнала, заказов или отчёта Метрики")
    if not path.is_file() or path.suffix.lower() not in {".csv",".tsv",".txt",".xlsx",".jsonl",".ndjson",".json"}:
        return unknown
    aliases={header(a):k for k,opts in ALIASES.items() for a in [k,*opts]}
    metadata={"capture_headers":True}
    rows=records(path,aliases,metadata)
    try:
        if path.suffix.lower() in {".jsonl",".ndjson",".json"}:
            r={k:None for row in islice(rows,20) if isinstance(row,dict) for k in row}
        else:
            r=next((r for r in islice(rows,20) if isinstance(r,dict) and r),{})
    except (BadZipFile,UnicodeError,csv.Error,ValueError) as exc:
        return unknown | dict(reason="Таблица не прочитана · "+type(exc).__name__)
    finally:
        rows.close()
    if not r:
        r=dict.fromkeys(metadata.get("headers",[]))
    columns={k:LOGS.get(k) or aliases[header(k)] for k in r if k in LOGS or header(k) in aliases}
    fields=set(columns.values())
    onsite=any(re.search(r"внутренн|по сайту|site.?search",str(k),re.I) for k in [*r,metadata.get("report_title","")])
    external=any(re.search(r"поисковые фразы|ym:s:searchPhrase|поисковая система|search engine",str(k),re.I)
                 for k in [*r,metadata.get("report_title","")])
    generic_phrase=any(header(k) in {"поисковая фраза","search phrase"} for k in r)
    if {"event_name","event_params","user_pseudo_id"}<=r.keys():
        return dict(kind="ga4_events",confidence=1.,columns={k:v for k,v in GA4.items() if k in r},
                    reason="События GA4 с параметрами BigQuery и идентификатором пользователя")
    goals = goal_columns(r, metadata.get("report_title", ""))
    if goals and not fields.intersection({"q", "session_id", "order_id", "search_id", "client_id"}):
        return dict(kind="metrika_goals", confidence=.99, columns=goals,
                    reason="Дата и количество достижений целей Метрики")
    if any(k.startswith("ym:pv:") for k in columns) and fields & {"hit_id","search_url"}:
        kind,confidence,reason="metrika_hits",1., "Поля хита Logs API"
    elif "ym:s:visitID" in columns:
        kind,confidence,reason="metrika_visits",1., "Идентификатор визита Logs API"
    elif "q" in fields and not onsite and (external or generic_phrase and "visits" in fields and not fields & {"n_cards","zero_rate","count"}):
        kind,confidence,reason="metrika_external_phrases",.98,"Поисковые фразы привлечения из внешних поисковых систем"
    elif fields & {"product","target","q","search_id"} and fields & {"lead_id","client_id"} and "ts" in fields and (
            "lead_id" in fields or "revenue" in fields and not fields & {"order","order_id","click","n_cards","count","visits"}):
        kind,confidence,reason="crm_leads",.95,"Карточка заявки с клиентом, датой и суммой или номером"
    elif "q" in fields and fields & {"visits","bounce","depth"}:
        kind,confidence,reason="metrika_report",.98,"Поисковая фраза и показатели визитов"
    elif "q" in fields:
        kind,confidence,reason="search_log",.95 if len(fields)>1 else .7,"Колонка поискового запроса"
    elif fields & {"order_id","order"} and fields & {"revenue","target","ts"}:
        kind,confidence,reason="orders",.9,"Заказы без колонки поискового запроса"
    else:
        return unknown | dict(columns=columns)
    return dict(kind=kind,confidence=confidence,columns=columns,reason=reason)


def log_kind(path):
    return {"metrika_visits":"visits","metrika_hits":"hits"}.get(sniff(path)["kind"])


def search_phrase(url,params):
    keys=("site_search_query","search_term","search_query","q","query","search","text","keyword")
    value=next((params[k] for k in keys if params.get(k)),None)
    if value:
        return value
    query=parse_qs(urlsplit(url or "").query)
    return next((query[k][0] for k in keys if k in query),None)


def ordered_files(files):
    order={"metrika_visits":0,"search_log":1,"metrika_hits":2,"ga4_events":2,"metrika_report":3,"metrika_external_phrases":4,"crm_leads":5,"metrika_goals":6}
    return sorted(files,key=lambda f:order.get(sniff(f)["kind"],1))


@lru_cache(8192)
def timestamp(v,default):
    if not v:
        return default
    try:
        number=float(v)
        if not isfinite(number):
            raise ValueError("Неизвестное время")
        return number/1000 if abs(number)>1e11 else number
    except (ValueError,TypeError):
        try:
            dt=datetime.fromisoformat(str(v))
        except ValueError:
            for fmt in ("%d.%m.%Y %H:%M:%S","%d.%m.%Y %H:%M","%d.%m.%Y"):
                try:
                    dt=datetime.strptime(str(v),fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("Неизвестный формат времени")
        return (dt if dt.tzinfo else dt.replace(tzinfo=MSK)).timestamp()


@lru_cache(4096)
def number(v):
    text="".join(str(v).split()).replace(",",".")
    value=float(text)
    if not isfinite(value):
        raise ValueError("Нечисловое значение")
    return value


@lru_cache(4096)
def amount(v):
    label=str(v).strip().lower()
    if label in {"да","true","yes"}:
        return 1
    if label in {"нет","false","no","","none"}:
        return 0
    x=number(v)
    if x<0 or not x.is_integer():
        raise ValueError("Количество должно быть целым")
    return int(x)


def unpack(value,default):
    if not isinstance(value,str) or not value:
        return value or default
    try:
        return json.loads(value)
    except ValueError:
        return ast.literal_eval(value)


def ga4_hit(row):
    if not isinstance(row,dict):
        raise ValueError("Ожидается объект GA4")
    params={}
    for entry in row.get("event_params") or []:
        value=entry["value"]
        params[entry["key"]]=next((v for v in value.values() if v is not None),None) if isinstance(value,dict) else value
    user=str(row.get("user_pseudo_id") or "")
    name=row["event_name"]
    if not user or not row.get("event_timestamp"):
        raise ValueError("Нет пользователя или времени GA4")
    ts=number(row["event_timestamp"])/1_000_000
    digest=hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    session=params.get("ga_session_id")
    sid="ga4_"+dump([user,str(session) if session is not None else digest])
    p={}
    if name in {"view_search_results","search"}:
        if not params.get("search_term"):
            raise ValueError("Нет search_term")
        p["site_search_query"]=params["search_term"]
        p["search_id"]="ga4_"+digest
        if params.get("search_results_count") is not None:
            p["search_results_count"]=params["search_results_count"]
    elif name in {"purchase","select_item","add_to_cart"}:
        items=row.get("items") or []
        products=[dict(id=str(item["item_id"]),quantity=item.get("quantity"),position=item.get("item_list_index"))
                  for item in items if isinstance(item,dict) and item.get("item_id")]
        ec=row.get("ecommerce") or {}
        value=ec.get("purchase_revenue")
        if value is None:
            value=params.get("value")
        currency=str(params.get("currency") or ec.get("currency") or "").upper()
        tid=ec.get("transaction_id") or params.get("transaction_id")
        kind={"purchase":"purchase","select_item":"click","add_to_cart":"add"}[name]
        p.update(event_id="ga4_order_"+str(tid) if name=="purchase" and tid else "ga4_"+digest,
                 ecommerce={kind:dict(products=products,actionField={"revenue":value if currency=="RUB" else None})},
                 payload=dict(items=items,currency=currency,amount=value,transaction_id=tid))
    return {"ym:pv:visitID":sid,"ym:pv:clientID":user,"ym:pv:watchID":digest,"ym:pv:dateTime":ts,"ym:pv:params":p}


def timed_records(db,path,aliases,default,metadata):
    stream=records(path,aliases,metadata)
    kind=sniff(path)["kind"]
    if kind not in {"metrika_hits","ga4_events"}:
        yield from enumerate(stream)
        return
    # Сортировка на диске сохраняет исходный номер для дедупликации даже
    # в несортированных выгрузках. Дата с ошибкой проверяется при разборе.
    db.execute("DROP TABLE IF EXISTS temp.history_hits")
    db.execute("CREATE TEMP TABLE history_hits(line INTEGER PRIMARY KEY,ts REAL,body TEXT)")
    def encoded():
        for i,row in enumerate(stream):
            if kind=="ga4_events":
                try:
                    row=ga4_hit(row)
                except (KeyError,ValueError,TypeError,AttributeError) as exc:
                    row={"_ga_error":str(exc)}
            try:
                ts=timestamp(row.get("ym:pv:dateTime"),default) if isinstance(row,dict) else None
            except (TypeError,ValueError):
                ts=None
            yield i,ts,dump(row)
    db.executemany("INSERT INTO history_hits VALUES (?,?,?)",encoded())
    for i,body in db.execute("SELECT line,body FROM history_hits ORDER BY ts,line"):
        yield i,json.loads(body)
    db.execute("DROP TABLE temp.history_hits")


def ingest_files(engine,files,mapping=None):
    files=ordered_files(files)
    hits=any(log_kind(f)=="hits" for f in files)
    results=[]
    for f in files:
        summary_only=False
        if results and sniff(f)["kind"]=="metrika_report":
            # Сводку того же трафика нельзя прибавлять к поисковым событиям.
            aliases={header(a):k for k,opts in ALIASES.items() for a in [k,*opts]}
            frequencies=Counter()
            meta={}
            for raw in records(Path(f),aliases,meta):
                row={aliases[header(k)]:v for k,v in raw.items() if header(k) in aliases}
                q=str(row.get("q") or "").strip()
                if not q or total_row(q):
                    continue
                try:
                    frequencies[q]+=amount(row.get("count",row.get("visits")))
                except ValueError:
                    continue
            period=meta.get("declared_period")
            window=" WHERE ts BETWEEN ? AND ?" if period else ""
            history={r["q"]:r["n"] for r in engine.journal.rows(
                "SELECT q_raw q,count(*) n FROM active_history"+window+" GROUP BY q_raw",period or ())}
            summary_only=bool(frequencies and frequencies==history)
        results.append(ingest(engine,f,mapping,visits_with_hits=hits,summary_only=summary_only))
    return results


def total_row(q):
    return bool(re.fullmatch(r"(итого|всего|итоги|total|totals)( и средние| по отч[её]ту)?",q.casefold()))


def collect_goal_row(raw, columns, days):
    row = {field: raw.get(col) for col, field in columns.items()}
    if len(row) != len(columns):
        raise ValueError("Несколько колонок для одной цели")
    day_value = str(row.get("ts") or "").strip()
    if total_row(day_value):
        raise ValueError("Итоговая строка отчёта")
    if not day_value:
        raise ValueError("Нет даты достижения цели")
    try:
        ts = timestamp(day_value, 0)
        day = datetime.fromtimestamp(ts, MSK).date().isoformat()
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError("Некорректная дата достижения цели") from exc
    if "goal_name" in row:
        stage = goal_stage(row["goal_name"])
        values = {stage: row.get("achievements")} if stage else {}
    else:
        values = {stage: row[stage] for stage in GOAL_STAGES if stage in row}
    try:
        counts = {k: amount(v) for k,v in values.items() if v not in (None, "", "—", "-")}
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректное число достижений") from exc
    if not counts:
        raise ValueError("Нет числовых достижений известных целей")
    if days.get(day, {}).keys() & counts.keys():
        raise ValueError("Повтор цели за ту же дату")
    days.setdefault(day, {}).update(counts)
    return ts


def offer_resolver(catalog):
    external={}
    for offer in catalog.offers_by_id.values():
        codes=offer.attrs.get("source_ids",[])
        if isinstance(codes,str):
            try:
                codes=json.loads(codes)
            except ValueError:
                codes=[]
        for code in codes if isinstance(codes,list) else []:
            key=str(code)
            external[key]=offer if external.get(key,offer) is offer else None
    @lru_cache(8192)
    def resolve(code):
        return catalog.offers_by_id.get(code) or external.get(code) or catalog.skus.get(sku_key(code)) if code else None
    return resolve


def link_crm(db,catalog,resolve,event):
    """Заявка принадлежит одному поиску. Повторный импорт сохраняет исходное событие."""
    linked=0
    for lead in db.execute("SELECT * FROM analytics_crm_leads WHERE search_id IS NULL ORDER BY ts,id"):
        params=[lead["client"],lead["ts"]-7*86400,lead["ts"]]
        filters=["s.client_id=?","s.ts>=?","s.ts<=?"]
        if lead["explicit_search"]:
            filters.append("s.search_id=?")
            params.append(lead["explicit_search"])
        elif lead["q"]:
            filters.append("s.q_norm=?")
            params.append(normalize(lead["q"]))
        else:
            product=lead["product"]
            offer=resolve(product) or catalog.offer_names.get(normalize(product))
            card=offer.card_id if offer else product
            oid=offer.offer_id if offer else product
            filters.append("""EXISTS(SELECT 1 FROM events e WHERE e.search_id=s.search_id AND (
                (e.type IN ('click','cart','order') AND (e.card_id=? OR e.offer_id=?)) OR
                (e.type='impression' AND EXISTS(SELECT 1 FROM json_each(e.payload_json,'$.cards')
                                               WHERE value IN (?,?,?)))))""")
            params.extend([card,oid,card,oid,product])
        matches=db.execute("""SELECT s.search_id,s.session_id,s.ts FROM searches s JOIN analytics_import_ids i ON i.id=s.search_id
                WHERE s.source='history' AND """+" AND ".join(filters)+" ORDER BY s.ts DESC,s.search_id LIMIT 2",params).fetchall()
        if matches and (len(matches)==1 or matches[0]["ts"]!=matches[1]["ts"]):
            row=matches[0]
            event(lead["id"],"lead",row["search_id"],lead["ts"],row["session_id"],lead["client"],value=lead["amount"],
                  payload=dict(source="crm",file=lead["file"],product=lead["product"],q=lead["q"]))
            db.execute("DELETE FROM events WHERE event_id=? AND type='exit'",(row["search_id"]+"_exit",))
            db.execute("UPDATE analytics_crm_leads SET search_id=? WHERE id=?",(row["search_id"],lead["id"]))
            linked+=1
    return linked


def ingest(engine,filename,mapping=None,*,visits_with_hits=False,summary_only=False):
    path=Path(filename)
    engine.catalog.legacy_category_names=engine.names["category"]
    raw=path.is_dir()
    hint=sniff(path)
    file_kind=hint["kind"]
    external_counts=Counter()
    goals_by_day = {}
    if file_kind in {"metrika_external_phrases", "metrika_goals"}:
        summary_only=True
    if raw:
        files=ordered_files(f for f in path.iterdir() if f.is_file() and f.suffix.lower() in {".tsv",".jsonl",".csv",".xlsx"})
        files=[f for f in files if log_kind(f)]
        visits_with_hits=any(log_kind(f)=="hits" for f in files)
        if not files:
            raise ValueError("В каталоге нужны файлы visits и hits")
    else:
        files=[path]
    mapped=yaml.safe_load(Path(mapping).read_text()) if mapping else {}
    aliases={header(a):k for k,opts in ALIASES.items() for a in [k,*opts]}
    for k,v in (mapped or {}).items():
        if k in ALIASES and v not in ALIASES:
            aliases[header(v)]=k
        elif v in ALIASES:
            aliases[header(k)]=v
        else:
            raise ValueError(f"Неизвестное поле в карте столбцов · {k}")
    j=engine.journal
    resolve=offer_resolver(engine.catalog)
    stats=Counter(searches=0,events=0,skipped=0,duplicates=0)
    known=set()
    unknown=set()
    visits={}
    last={}
    active={}
    cache={}
    native=set()
    imported=False
    new_members=False
    def observe(ident,flags):
        nonlocal imported,new_members
        imported=True
        db.execute("INSERT OR REPLACE INTO analytics_observation VALUES (?,?,?,?)",(ident,*flags))
        added=db.execute("INSERT OR IGNORE INTO analytics_import_ids VALUES (?)",(ident,))
        new_members|=bool(added.rowcount)
    has=set()
    log_flags=set()
    log_targets=0
    table_target=False
    log_has_position=False
    reasons=Counter()
    report_metadata={}
    report_metrics=Counter()
    visit_purchases=Counter()
    depth_visits=0
    columns={}
    period=[]
    observed=zero=0
    linked=set()
    client_sessions={}
    def recognize_logs(keys):
        columns.update({k:LOGS[k] for k in keys if k in LOGS})
        known.update(k for k in keys if k in LOGS)
        unknown.update(k for k in keys if k not in LOGS)

    def visit_orders(meta,ident,sid,ts):
        ids=meta.get("order_ids",[])
        values=meta.get("amounts",[])
        for i,oid in enumerate(ids):
            value=values[i] if i<len(values) else None
            products=meta.get("product_ids") or []
            item=products[i] if len(products)==len(ids) else None
            offer=resolve(str(item)) if item is not None else None
            quantities=meta.get("quantities") or []
            qty=quantities[i] if len(quantities)==len(ids) else None
            event("ym_visit_order_"+str(oid),"order",ident,ts,sid,meta.get("client_id","guest"),value=value,offer_id=offer.offer_id if offer else str(item) if item is not None else None,card_id=offer.card_id if offer else None,
                  qty=qty if isinstance(qty,(int,float)) else None,margin_value=value*offer.margin if value is not None and offer else None,
                  payload={"attribution":"last_search_in_visit"})
        return len(ids)

    def track(ts,count,n,empty):
        nonlocal observed,zero
        if not period:
            period.extend([ts,ts])
        else:
            period[:]=[min(period[0],ts),max(period[1],ts)]
        if count is not None:
            observed+=n
            zero+=empty

    @lru_cache(8192)
    def template(q,ids,observed_count):
        key=(q,ids)
        if key not in cache:
            if len(cache)>=16384:
                cache.clear()
            if ids is None:
                matches=match(engine.catalog,q,limit=None)
                hits=matches[:20]
                total=len(matches)
            else:
                hits=[engine.catalog.cards[c].offers[0] for c in ids if c in engine.catalog.cards]
                total=len(ids)
            cache[key]=(hits,total,describe(engine,q,hits))
        hits,total,(intent,reason,cat,_,filters,entities)=cache[key]
        count=total if observed_count is None else observed_count
        cards=ids if ids is not None else [o.card_id for o in hits[:count]]
        return (normalize(q),intent,cat,filters,entities,count,int(not count),reason if not count else None,
                dump(cards),dump(["products"] if count else []))

    def save(ident,q,ts,sid,client,segment,count=None,ids=None,category=None,previous=None):
        norm,intent,cat,filters,entities,count,empty,reason,cards,blocks=template(q,tuple(ids) if ids is not None else None,count)
        added=db.execute("""INSERT OR IGNORE INTO searches
            (search_id,ts,session_id,client_id,segment,source,engine,mode,q_raw,q_norm,q_corrected,intent,
             category_ctx,prev_search_id,filters_json,entities_json,n_cards,zero,fail_reason,top_cards_json,blocks_json)
            VALUES (?,?,?,?,?,'history','legacy','naive',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ident,ts,sid,client,segment,q,norm,norm,intent,category or cat,previous,filters,entities,count,empty,reason,cards,blocks))
        if not added.rowcount:
            existing=db.execute("SELECT session_id FROM searches WHERE search_id=?",(ident,)).fetchone()
            if existing[0]!=sid:
                native.add(ident)
            stats["duplicates"]+=1
            return False
        stats["searches"]+=1
        return True

    def event(eid,kind,ident,ts,sid,client,**fields):
        # Тот же визит и тот же поиск встречаются в журнале магазина и Logs API.
        if eid.startswith("ym_") and ident in linked and db.execute("SELECT 1 FROM events WHERE search_id=? AND type=? AND event_id NOT GLOB 'ym_*' LIMIT 1",
                                          (ident,kind)).fetchone():
            stats["duplicates"]+=1
            return
        if ident in native:
            stats["duplicates"]+=1
            return
        if not db.execute("SELECT 1 FROM events WHERE event_id=?",(eid,)).fetchone():
            j.event(ts,dict(event_id=eid,type=kind,search_id=ident,session_id=sid,client_id=client,**fields))
            stats["events"]+=1
        else:
            stats["duplicates"]+=1

    with j.transaction() as db:
        # SQLite восстанавливает DDL вместе с данными при откате файла.
        # Вторичные индексы пустого журнала дешевле построить одним проходом.
        rebuild=[]
        if not db.execute("SELECT 1 FROM searches LIMIT 1").fetchone() and not any(log_kind(f) for f in files):
            rebuild=db.execute("""SELECT name,sql FROM sqlite_master WHERE type='index'
                AND name IN ('searches_source','searches_session','searches_engine_mode','searches_query_ts','events_search')""").fetchall()
            for idx in rebuild:
                db.execute(f'DROP INDEX "{idx[0]}"')
        triggers=db.execute("""SELECT name,sql FROM sqlite_master WHERE name IN
                    ('invalidate_searches_INSERT','invalidate_events_INSERT')""").fetchall()
        for trigger in triggers:
            db.execute(f'DROP TRIGGER "{trigger[0]}"')
        db.execute("CREATE TEMP TABLE IF NOT EXISTS imported_log_search(id TEXT PRIMARY KEY)")
        db.execute("DELETE FROM imported_log_search")
        db.execute("CREATE TABLE IF NOT EXISTS analytics_targets(id TEXT PRIMARY KEY,card_id TEXT,position INTEGER)")
        if file_kind=="crm_leads":
            db.execute("CREATE INDEX IF NOT EXISTS history_client_time ON searches(client_id,ts) WHERE source='history'")
        db.execute("""CREATE TABLE IF NOT EXISTS analytics_crm_leads(id TEXT PRIMARY KEY,file TEXT,ts REAL,client TEXT,
                    q TEXT,product TEXT,amount REAL,explicit_search TEXT,search_id TEXT)""")
        for f in files:
            default=f.stat().st_mtime
            for i,r in timed_records(db,f,aliases,default,report_metadata):
                stats["rows"]=stats.get("rows",0)+1
                if not isinstance(r,dict):
                    reasons["Запись не является объектом"]+=1
                    stats["skipped"]+=1
                    continue
                if file_kind=="metrika_goals":
                    columns.update(hint["columns"])
                    known.update(columns)
                    unknown.update(r.keys() - columns.keys())
                    try:
                        ts = collect_goal_row(r, columns, goals_by_day)
                        track(ts,None,0,0)
                    except ValueError as exc:
                        stats["skipped"]+=1
                        reasons[str(exc)]+=1
                    continue
                if "_ga_error" in r:
                    reasons["Повреждены параметры GA4 или отсутствует поисковая фраза"]+=1
                    stats["skipped"]+=1
                    continue
                if "ym:s:visitID" in r:
                    try:
                        vid=str(r["ym:s:visitID"])
                        visits[vid]=dict(zip(unpack(r.get("ym:s:parsedParamsKey1"),[]),unpack(r.get("ym:s:parsedParamsKey2"),[])))
                        meta=visits[vid]
                        meta.setdefault("client_id",str(r.get("ym:s:clientID") or "guest"))
                        if "ym:s:purchaseID" in r:
                            ids=unpack(r["ym:s:purchaseID"],[])
                            if not isinstance(ids,list):
                                raise ValueError()
                            meta["order_ids"]=ids
                        if "ym:s:purchaseRevenue" in r:
                            meta["amounts"]=[number(v) for v in unpack(r["ym:s:purchaseRevenue"],[])]
                        if "amounts" in meta:
                            currencies=unpack(r.get("ym:s:purchaseCurrency"),[])
                            if not isinstance(currencies,list):
                                raise ValueError()
                            meta["amounts"]=[v if not currencies or str(currencies[min(i,len(currencies)-1)]).upper() in {"RUB","RUR"}
                                             else None for i,v in enumerate(meta["amounts"])]
                        meta["product_ids"]=unpack(r.get("ym:s:purchasedProductID"),[])
                        meta["quantities"]=unpack(r.get("ym:s:purchasedProductQuantity"),[])
                        ts=timestamp(r.get("ym:s:dateTime") or r.get("ym:s:date"),default)
                        watchers=unpack(r.get("ym:s:watchIDs"),[])
                    except (TypeError, ValueError,SyntaxError):
                        stats["skipped"]+=1
                        reasons["Параметры визита не распознаны"]+=1
                        continue
                    if not isinstance(watchers,(list,tuple)):
                        stats["skipped"]+=1
                        reasons["Неверный список идентификаторов хитов"]+=1
                        continue
                    track(ts,None,0,0)
                    has.add("ts")
                    if "order_ids" in meta:
                        has.add("order")
                        visit_purchases["orders"]+=len(meta["order_ids"])
                        for rub in meta.get("amounts",[]):
                            if rub is not None:
                                has.add("revenue")
                                visit_purchases["priced_orders"]+=1
                                visit_purchases["revenue_rub"]+=rub
                    for wid in watchers:
                        db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",("settings:watch:"+str(wid),vid,default))
                    db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",("settings:visit:"+vid,dump(visits[vid]),default))
                    if not visits_with_hits:
                        url=r.get("ym:s:startURL") or ""
                        try:
                            q=search_phrase(url,meta)
                        except ValueError:
                            q=None
                        seen=db.execute("SELECT 1 FROM searches WHERE session_id=? AND source='history' AND search_id!=? LIMIT 1",
                                        (vid,"import_visit_"+vid)).fetchone() if q else None
                        if q and len(q)<=1500 and not seen:
                            # Если позже придут хиты того же визита, их наблюдения
                            # заменят оценку по стартовой странице.
                            ident="import_visit_"+vid
                            client=str(r.get("ym:s:clientID") or "guest")
                            save(ident,q,ts,vid,client,visits[vid].get("segment","unknown"))
                            observe(ident,("order_ids" in meta,"amounts" in meta,False))
                            visit_orders(meta,ident,vid,ts)
                            has.add("ts")
                            if "order_ids" in meta:
                                has.add("order")
                            if "amounts" in meta:
                                has.add("revenue")
                    recognize_logs(r)
                    continue
                if "ym:pv:URL" in r and "ym:pv:watchID" not in r and "ym:pv:visitID" not in r:
                    r["ym:pv:watchID"]=hashlib.sha256(dump([r,i]).encode()).hexdigest()[:24]
                input_headers=tuple(r) if "ym:pv:watchID" in r or "ym:pv:visitID" in r else ()
                if "ym:pv:watchID" in r and "ym:pv:visitID" not in r:
                    visit=visits.get("watch:"+str(r["ym:pv:watchID"]))
                    if not visit:
                        saved=db.execute("SELECT value FROM kv WHERE key=?",("settings:watch:"+str(r["ym:pv:watchID"]),)).fetchone()
                        visit=saved[0] if saved else None
                    if not visit and r.get("ym:pv:clientID"):
                        client=str(r["ym:pv:clientID"])
                        try:
                            when=timestamp(r.get("ym:pv:dateTime"),default)
                            prior,previous_ts=client_sessions.get(client,(None,0))
                            visit=prior if prior and 0<=when-previous_ts<=1800 else "ym_client_"+client+"_"+str(r["ym:pv:watchID"])
                            client_sessions[client]=(visit,when)
                        except ValueError:
                            pass
                    r["ym:pv:visitID"]=visit or "hit_"+str(r["ym:pv:watchID"])
                if "ym:pv:visitID" in r:
                    recognize_logs(input_headers)
                    sid=str(r["ym:pv:visitID"])
                    if sid not in visits:
                        saved=db.execute("SELECT value FROM kv WHERE key=?",("settings:visit:"+sid,)).fetchone()
                        visits[sid]=json.loads(saved[0]) if saved else {}
                    meta=visits[sid]
                    client=meta.get("client_id",str(r.get("ym:pv:clientID","guest")))
                    try:
                        ts=timestamp(r.get("ym:pv:dateTime"),default)
                        p=unpack(r.get("ym:pv:params"),{})
                        if p==[]:
                            p={}
                        if not isinstance(p,dict) or not isinstance(p.get("ecommerce",{}),dict):
                            raise ValueError()
                        if "search_results_count" in p:
                            p["search_results_count"]=amount(p["search_results_count"])
                    except (TypeError,ValueError,SyntaxError):
                        stats["skipped"]+=1
                        reasons["Не распознаны время или параметры хита"]+=1
                        continue
                    ec=p.get("ecommerce",{})
                    try:
                        url=r.get("ym:pv:URL") or ""
                        q=search_phrase(url,p)
                    except ValueError:
                        reasons["Неверный URL хита"]+=1
                        stats["skipped"]+=1
                        continue
                    wid=str(r.get("ym:pv:watchID",i))
                    eid="ym_"+sid+"_"+wid
                    if q:
                        if not isinstance(q,str) or not q.strip() or len(q)>1500:
                            reasons["Неверная поисковая фраза хита"]+=1
                            stats["skipped"]+=1
                            continue
                        estimate="import_visit_"+sid
                        if db.execute("SELECT 1 FROM analytics_import_ids WHERE id=?",(estimate,)).fetchone():
                            db.execute("DELETE FROM events WHERE search_id=?",(estimate,))
                            for table in ("analytics_import_ids","analytics_observation"):
                                db.execute("DELETE FROM "+table+" WHERE id=?",(estimate,))
                            db.execute("DELETE FROM searches WHERE search_id=? AND source='history'",(estimate,))
                        ident=str(p.get("search_id") or eid)
                        impressions=ec.get("impressions",[])
                        impressions=[x for x in impressions if isinstance(x,dict) and isinstance(x.get("id"),str)] if isinstance(impressions,list) else []
                        ids=[offer.card_id if (offer:=resolve(x["id"])) else x["id"] for x in impressions]
                        track(ts,p.get("search_results_count"),1,int(p.get("search_results_count")==0))
                        shop=db.execute("""SELECT s.search_id FROM searches s JOIN analytics_import_ids i ON i.id=s.search_id
                            WHERE s.session_id=? AND s.ts=? AND s.q_raw=? AND s.search_id GLOB 'import_*'
                            AND s.search_id NOT GLOB 'import_visit_*' LIMIT 1""",(sid,ts,q)).fetchone()
                        if shop:
                            ident=shop[0]
                            linked.add(ident)
                            stats["linked_searches"]+=1
                            active[ident]=bool(db.execute("SELECT 1 FROM events WHERE search_id=? AND type IN ('order','cart','click') LIMIT 1",(ident,)).fetchone())
                        else:
                            save(ident,q,ts,sid,client,meta.get("segment","unknown"),p.get("search_results_count"),ids if impressions else None,p.get("search_category_ctx"),(p.get("inherited") or {}).get("from_search_id"))
                            observe(ident,(False,False,False))
                        db.execute("INSERT OR IGNORE INTO imported_log_search VALUES (?)",(ident,))
                        if sid in last:
                            prev,t,old=last[sid]
                            if 0<=ts-t<=180 and normalize(old)!=normalize(q) and not active.get(prev) and not p.get("inherited"):
                                event(prev+"_reform","reformulate",prev,ts,sid,client,payload={"to":q})
                        last[sid]=ident,ts,q
                        if impressions:
                            event(ident+"_impression","impression",ident,ts,sid,client,payload={"cards":[x["id"] for x in impressions]})
                        continue
                    if sid not in last and file_kind=="ga4_events":
                        previous=db.execute("""SELECT search_id,ts,q_raw FROM searches WHERE source='history'
                            AND session_id=? AND ts<=? ORDER BY ts DESC LIMIT 1""",(sid,ts)).fetchone()
                        if previous:
                            last[sid]=tuple(previous)
                    if sid not in last:
                        reasons["Хит до первого поиска в визите"]+=1
                        stats["skipped"]+=1
                        continue
                    ident=last[sid][0]
                    kind=p.get("event_type")
                    action_key=next((k for k in ("purchase","add","click","detail") if k in ec),None)
                    kind=kind or {"purchase":"order","add":"cart","click":"click","detail":"click"}.get(action_key)
                    if kind in {"order","cart","click","lead","reformulate","exit","suggest_click","chip","correction_accept","correction_reject","suggest_show"}:
                        a=ec.get(action_key,{})
                        if not isinstance(a,dict) or not isinstance(a.get("actionField",{}),dict):
                            reasons["Неверные поля действия ecommerce"]+=1
                            stats["skipped"]+=1
                            continue
                        items=a.get("products") or [{}]
                        if not isinstance(items,list) or not isinstance(items[0],dict):
                            reasons["Неверный список товаров ecommerce"]+=1
                            stats["skipped"]+=1
                            continue
                        item=items[0]
                        revenue=a.get("actionField",{}).get("revenue")
                        margin=p.get("margin_value")
                        offer=resolve(item.get("id"))
                        if kind=="order":
                            log_flags.add("order")
                            if revenue is not None:
                                try:
                                    revenue=number(revenue)
                                except ValueError:
                                    reasons["Неверная сумма заказа"]+=1
                                    stats["skipped"]+=1
                                    continue
                                log_flags.add("revenue")
                        if file_kind=="ga4_events":
                            db.execute("INSERT OR IGNORE INTO imported_log_search VALUES (?)",(ident,))
                            db.execute("DELETE FROM events WHERE event_id=? AND type='exit'",(ident+"_exit",))
                            imported=True
                        if kind=="click":
                            log_flags.add("click")
                            log_has_position|=item.get("position") is not None
                        if kind in ("order","click") and (offer or item.get("card_id") in engine.catalog.cards or item.get("id") in engine.catalog.cards):
                            log_targets+=1
                        if kind=="order" and margin is None and revenue is not None and offer and len(items)==1:
                            margin=round(float(revenue)*offer.margin,2)
                        event(str(p.get("event_id") or eid),kind,ident,ts,sid,client,card_id=offer.card_id if offer else item.get("card_id") or item.get("id"),
                              offer_id=offer.offer_id if offer else item.get("id"),position=item.get("position"),qty=item.get("quantity"),
                              value=revenue,margin_value=margin,payload=p.get("payload",{}))
                        active[ident]=True
                    else:
                        # Переход из поисковой выдачи на карточку — наблюдаемый клик.
                        # Остальные просмотры учитываем отдельно, без выдуманных покупок.
                        parts=urlsplit(url).path.strip("/").split("/")
                        if (len(parts)>1 and parts[-2].lower() in {"product","products","item","goods","catalog"}
                                and search_phrase(r.get("ym:pv:referer"),{})==last[sid][2]):
                            oid=unquote(parts[-1])
                            offer=resolve(oid)
                            event(eid,"click",ident,ts,sid,client,offer_id=offer.offer_id if offer else oid,card_id=offer.card_id if offer else oid)
                            active[ident]=True
                            log_flags.add("click")
                            log_targets+=int(bool(offer))
                        else:
                            stats["pageviews_without_search_event"]+=1
                    continue
                row={}
                for k,v in r.items():
                    key=aliases.get(header(k))
                    if key:
                        known.add(k)
                        columns[k]=key
                        row[key]=v
                    else:
                        unknown.add(str(k))
                q=str(row.get("q") or "").strip()
                if file_kind=="crm_leads":
                    client=str(row.get("client_id") or "").strip()
                    product=str(row.get("product") or row.get("target") or "").strip()
                    try:
                        if not client or not row.get("ts") or not (q or product or row.get("search_id")):
                            raise ValueError()
                        ts=timestamp(row["ts"],default)
                        if re.fullmatch(r"(?:\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})",str(row["ts"])):
                            ts+=86399
                        rub=number(row["revenue"]) if row.get("revenue") not in (None,"") else None
                    except (TypeError,ValueError):
                        reasons["Для заявки нужны клиент, дата, фраза или товар и корректная сумма"]+=1
                        stats["skipped"]+=1
                        continue
                    identity=row.get("lead_id") or [client,ts,q,product,rub,row.get("search_id")]
                    lid="crm_"+hashlib.sha256(dump(identity).encode()).hexdigest()[:24]
                    inserted=db.execute("INSERT OR IGNORE INTO analytics_crm_leads VALUES (?,?,?,?,?,?,?,?,NULL)",
                                (lid,path.name,ts,client,q,product,rub,row.get("search_id")))
                    stats["duplicates"]+=int(not inserted.rowcount)
                    track(ts,None,0,0)
                    continue
                if total_row(q):
                    totals={}
                    for key in ("visits","count","depth","bounce"):
                        if row.get(key) not in (None,""):
                            try:
                                raw_value=str(row[key]).strip()
                                value=number(raw_value.rstrip("%"))
                                if key=="bounce" and (raw_value.endswith("%") or value>1):
                                    value/=100
                                totals[key]=value
                            except ValueError:
                                continue
                    report_metadata["totals"]=totals
                    reasons["Итоговая строка отчёта"]+=1
                    stats["skipped"]+=1
                    continue
                try:
                    visits_n=amount(row["visits"]) if row.get("visits") not in (None,"") else None
                    n=amount(row.get("count",visits_n if visits_n is not None else 1))
                    bounce_text=str(row.get("bounce") or 0).strip()
                    bounce=number(bounce_text.rstrip("%"))
                    if "%" in bounce_text or bounce>1 or "отказы, %" in (str(k).lower() for k in r):
                        bounce/=100
                    if not 0<=bounce<=1 or (visits_n is not None and not 1<=visits_n<=n):
                        raise ValueError()
                    ts=timestamp(row.get("ts"),default)
                    raw_rate=str(row.get("zero_rate") or 0).strip()
                    rate=number(raw_rate.rstrip("%"))/(100 if raw_rate.endswith("%") else 1)
                    order_value=row.get("order")
                    if isinstance(order_value,str) and re.fullmatch(r"[^\W_]+[-/#][\w/-]*\d[\w/-]*",order_value):
                        row["order_id"]=order_value
                    amounts={k:amount(row.get(k)) for k in ("click","cart","lead")}
                    amounts["order"]=1 if row.get("order_id") else amount(order_value)
                    if row.get("cart_product"):
                        amounts["cart"]=1
                    if any(header(k) in {"клик код","код товара клика","clicked product","clicked sku"} for k in r):
                        amounts["click"]=max(int(bool(row.get("target"))),amounts["click"])
                        row["click"]=amounts["click"]
                    # Пустой заказ в событийной строке журнала означает отсутствие покупки.
                    if n==1 and "order" in row:
                        row["order"]=amounts["order"]
                    depth=number(row["depth"]) if row.get("depth") not in (None,"") else None
                    pos=amount(row.get("position")) or None
                    revenue=number(row.get("revenue") or 0)
                    count=amount(row["n_cards"]) if row.get("n_cards") not in ("",None) else None
                    if not q or len(q)>1500 or n<1 or not 0<=rate<=1 or any(v>n for v in amounts.values()):
                        raise ValueError()
                except (TypeError,ValueError,SyntaxError):
                    stats["skipped"]+=1
                    reasons["Пустая фраза или неверное числовое поле"]+=1
                    continue
                track(ts,count if "zero_rate" not in row else rate,n,round(n*rate) if "zero_rate" in row else n if count==0 else 0)
                target=str(row.get("target") or "")
                explicit=any(header(name) in {"target","target card","target card id","целевой товар"} for name,assigned in columns.items() if assigned=="target") if target else False
                offer=resolve(target)
                card_id=offer.card_id if offer else target if target in engine.catalog.cards else None
                table_target|=bool(card_id and (explicit or amounts["click"] or amounts["order"]))
                has.update(k for k,v in row.items() if v not in (None,""))
                if visits_n is not None:
                    report_metrics["visits"]+=visits_n
                    report_metrics["searches"]+=n
                    if "bounce" in row:
                        report_metrics["estimated_bounces"]+=round(visits_n*bounce)
                    if depth is not None:
                        depth_visits+=visits_n
                        report_metrics["pageviews_estimate"]+=depth*visits_n
                if summary_only:
                    if file_kind=="metrika_external_phrases":
                        external_counts[q]+=visits_n if visits_n is not None else n
                    continue
                prefix="import_"+hashlib.sha256((str(i)+dump({k:str(v) for k,v in row.items()})).encode()).hexdigest()[:24]
                for k in range(n):
                    ident=prefix+"_"+str(k)
                    if explicit and card_id:
                        db.execute("INSERT OR REPLACE INTO analytics_targets VALUES (?,?,?)",(ident,card_id,pos))
                    observe(ident,tuple(field in row and row[field] not in ("",None) for field in ("order","revenue","click")))
                    sid=str(row.get("session_id") or (prefix+"_v"+str(k%visits_n) if visits_n else ident))
                    client=str(row.get("client_id") or "guest")
                    size=(0 if k<round(n*rate) else count or 1) if "zero_rate" in row else count
                    if save(ident,q,ts,sid,client,row.get("segment") or "unknown",size):
                        if "bounce" in row and k>=n-round((visits_n or n)*bounce):
                            event(ident+"_bounce","exit",ident,ts,sid,client,payload={"aggregate":True})
                        for kind,num in amounts.items():
                            if k<num:
                                event(ident+kind,kind,ident,ts,sid,client,card_id=card_id,offer_id=offer.offer_id if offer else None,position=pos,value=revenue/num if kind=="order" else None)
        for _,ddl in rebuild:
            db.execute(ddl)
        for sid,(ident,ts,q) in last.items():
            meta=visits.get(sid,{})
            if "order_ids" in meta:
                log_flags.add("order")
                if "amounts" in meta:
                    log_flags.add("revenue")
                hit_orders=db.execute("""SELECT 1 FROM searches s JOIN events e USING(search_id) WHERE s.session_id=? AND e.type='order'
                    AND e.event_id NOT GLOB 'ym_visit_order_*' LIMIT 1""",(sid,)).fetchone() if meta["order_ids"] else None
                if meta["order_ids"] and not hit_orders:
                    visit_orders(meta,ident,sid,ts)
                    active[ident]=True
            if not active.get(ident) and not db.execute("SELECT 1 FROM events WHERE search_id=? AND type='lead' LIMIT 1",(ident,)).fetchone():
                event(ident+"_exit","exit",ident,ts,sid,visits.get(sid,{}).get("client_id","guest"))
        if link_crm(db,engine.catalog,resolve,event):
            imported=True
        for _,ddl in triggers:
            db.execute(ddl)
        if log_flags:
            db.execute("""UPDATE analytics_observation SET orders=max(orders,?),revenue=max(revenue,?),clicks=max(clicks,?)
                          WHERE id IN (SELECT id FROM imported_log_search)""",tuple(k in log_flags for k in ("order","revenue","click")))
        logs=any(str(k).startswith("ym:pv:") for k in known)
        if logs:
            has.update(log_flags)
            if observed:
                has.add("n_cards")
        missing=[]
        if client_sessions:
            missing.append("Для хитов без идентификатора визита визит восстановлен по clientID и перерыву до 30 минут.")
        if any(m.get("order_ids") for m in visits.values()):
            missing.append("Покупки из сводки визита при отсутствии заказов в хитах отнесены к последнему поиску этого визита.")
        if logs:
            has.add("ts")
        if has or logs:
            for field,label in [("order","Нет данных о заказах: конверсия недоступна."),("revenue","Нет сумм заказов: выручка и потери не оценены."),
                                ("click","Нет кликов: CTR недоступен."),("ts","Нет дат: используется дата файла.")]:
                if field not in has:
                    missing.append(label)
            if not has.intersection({"n_cards","zero_rate"}):
                missing.append("Нет размеров исходной выдачи. Обычный поиск по словам воспроизведён по каталогу.")
            if has.intersection({"bounce","visits"}) and not summary_only:
                missing.append("Агрегаты Метрики распределены по визитам. Отказ в визите служит приближением ухода.")
        if not log_targets and not table_target:
            missing.append("Для цели в топ-5 нужен идентификатор товара либо товар клика или заказа из каталога.")
        availability=dict(zero_rate="наблюдение" if has.intersection({"n_cards","zero_rate"}) else "модель поиска по словам",
            orders="наблюдение" if "order" in has else "нет цели заказа",revenue="наблюдение" if "revenue" in has else "нет суммы заказа",
            ctr="наблюдение" if "click" in has else "нет кликов",click_position="по событиям" if log_has_position or "position" in has else "нет позиций клика",
            exit_after_fail="по событиям" if logs else "приближение по отказам" if "bounce" in has else "нет отказов",
            top5_hit="по целевому товару в кликах и заказах" if log_targets or table_target else "нет разметки целевого товара",reformulation="по визитам и хитам" if logs else "нет последовательности событий")
        if file_kind=="metrika_external_phrases":
            missing=["Фразы относятся к привлечению посетителей из поисковых систем. Внутренних поисков добавлено 0."]
        elif summary_only:
            missing.append("Частоты всех фраз совпали с журналом. Сводка Метрики сохранена отдельно, поиски повторно не добавлены.")
        if depth_visits:
            report_metrics["avg_depth"]=round(report_metrics["pageviews_estimate"]/depth_visits,4)
        if "declared_period" in report_metadata:
            period=report_metadata["declared_period"]
        report=dict(report_metadata=report_metadata,summary_only=summary_only,report_metrics=dict(report_metrics),kind=sniff(path)["kind"] if not raw else "metrika_hits",columns=columns,rows_read=stats["rows"] if stats["rows"] else 0,rows_accepted=stats["rows"]-stats["skipped"],
                    period=period,observed_searches=observed,observed_empty=zero,zero_rate=zero/observed if observed else None,availability=availability,file=path.name,source_type="Logs API" if logs or any(str(k).startswith("ym:s:") for k in known) else "Отчёт Метрики" if has.intersection({"visits","bounce"}) else "Журнал поиска",**stats,skip_reasons=dict(reasons),recognized=sorted(known),ignored=sorted(unknown),
                    visits=len(visits),fields=sorted(has),logs=logs,missing=missing)
        if file_kind=="crm_leads":
            crm=dict(db.execute("""SELECT count(*) records,count(search_id) linked,count(*)-count(search_id) unlinked,
                       sum(amount) pipeline_rub FROM analytics_crm_leads WHERE file=?""",(path.name,)).fetchone())
            report.update(source_type="CRM · заявки менеджеру",crm=crm,
                          missing=["Заявка привязана к последнему поиску того же клиента с той же фразой или показанным товаром за 7 дней; при наличии search_id проверяется этот поиск. Сумма заявки учитывается отдельно от выручки."],
                          availability={"funnel":"Учитываются связанные заявки","revenue":"Сумма заявки — потенциальная продажа"})
        if file_kind=="metrika_visits":
            if "revenue_rub" in visit_purchases:
                visit_purchases["revenue_rub"]=round(visit_purchases["revenue_rub"],2)
            report["visit_purchases"]=dict(visit_purchases)
            if visits_with_hits:
                report["missing"]=["Визиты дают связь с хитами и данные электронной коммерции. Размер выдачи, клики и последовательность запросов определяются по хитам."]
                report["availability"]["zero_rate"]="по связанным поисковым хитам"
            if "ym:s:purchaseRevenue" in known and "ym:s:purchaseCurrency" not in known:
                report["missing"].append("Валюта сумм визита не указана, при импорте приняты рубли.")
        if file_kind=="metrika_goals":
            report.update(source_type="Метрика · достижения целей", goals_by_day=goals_by_day,
                          report_metrics={k:sum(v[k] for v in goals_by_day.values() if k in v)
                                          for k in GOAL_STAGES if any(k in v for v in goals_by_day.values())},
                          availability={"funnel":"Достижения целей по дням"}, missing=[
                              "Дневные суммы не содержат фраз, идентификаторов заказов и связи с поисковой сессией."])
        if file_kind=="ga4_events":
            report.update(source_type="GA4 · события BigQuery",columns=hint["columns"],recognized=sorted(hint["columns"]),ignored=[])
            report["missing"].append("Суммы покупок показаны в рублях при валюте RUB. Исходная сумма, валюта и позиции сохранены в событии.")
        if file_kind=="metrika_external_phrases":
            report.update(source_type="Метрика · внешние поисковые фразы",
                          availability={"acquisition":"Наблюдаемые визиты из внешних поисковых систем"},external_phrases=[
                dict(q=q,visits=n) for q,n in external_counts.most_common(50)])
        db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",("settings:import-report:"+path.name,dump(report),time()))
        previous=db.execute("SELECT value FROM kv WHERE key='settings:history_source'").fetchone()
        switch = not previous or previous[0]!="import"
        goals_only = file_kind=="metrika_goals" and goals_by_day and switch
        if goals_only or imported and (stats["events"] or stats["searches"] or new_members or switch):
            db.execute("INSERT OR REPLACE INTO kv VALUES ('settings:history_source','import',?)",(time(),))
            db.execute("DELETE FROM analytics_reports")
            db.execute("UPDATE analytics_revision SET revision=revision+1")
            db.execute("INSERT OR REPLACE INTO kv VALUES ('settings:active_replay','',?)",(time(),))
        for row in j.rows("SELECT file,count(search_id) linked,count(*)-count(search_id) unlinked FROM analytics_crm_leads GROUP BY file"):
            saved=j.rows("SELECT value FROM kv WHERE key=?",("settings:import-report:"+row["file"],))
            if saved:
                prior=json.loads(saved[0]["value"])
                if "crm" in prior and prior["crm"]["linked"]!=row["linked"]:
                    prior["crm"].update(linked=row["linked"],unlinked=row["unlinked"])
                    j.db.execute("UPDATE kv SET value=? WHERE key=?",(dump(prior),"settings:import-report:"+row["file"]))
        reports=[json.loads(r["value"]) for r in j.rows("SELECT value FROM kv WHERE key GLOB 'settings:import-report:*' ORDER BY updated,key")]
        from kuznitsa.analytics.goals import reconcile
        reconcile(j, reports)
        report = next(r for r in reports if r["file"] == path.name)
        dest=Path(j.path).parent/"history_report.json"
        with NamedTemporaryFile("w",dir=dest.parent,delete=False) as out:
            json.dump({"files":reports},out,ensure_ascii=False,indent=2)
        Path(out.name).replace(dest)
    return report
