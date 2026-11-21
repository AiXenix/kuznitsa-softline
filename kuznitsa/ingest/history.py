"""Импорт потоковых таблиц и Logs API. Все изменения файла атомарны."""
import csv
import re
import ast
from functools import lru_cache
from tempfile import NamedTemporaryFile
import hashlib
import json
from collections import Counter
from datetime import datetime
from itertools import islice,chain
from time import time
from pathlib import Path
from math import isfinite
from urllib.parse import urlsplit,parse_qs

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


LOGS={
    "ym:s:visitID":"session_id","ym:s:clientID":"client_id","ym:s:watchIDs":"hit_ids",
    "ym:s:dateTime":"ts","ym:s:date":"ts","ym:s:startURL":"start_url",
    "ym:s:purchaseID":"order_ids","ym:s:purchaseRevenue":"order_values",
    "ym:s:parsedParamsKey1":"visit_parameter_names","ym:s:parsedParamsKey2":"visit_parameter_values",
    "ym:pv:watchID":"hit_id","ym:pv:visitID":"session_id","ym:pv:clientID":"client_id",
    "ym:pv:dateTime":"ts","ym:pv:URL":"search_url","ym:pv:params":"search_and_ecommerce",
}


@lru_cache(1024)
def header(v):
    return re.sub(r"[^a-zа-яё0-9]+"," ",re.sub(r"([a-z])([A-Z])",r"\1 \2",str(v)).lower()).strip()


def table_rows(rows,aliases):
    sample=list(islice(rows,12))
    if not sample:
        return
    def score(row):
        return sum(header(v) in aliases or str(v).startswith("ym:") for v in row)
    index=max(range(len(sample)),key=lambda i:score(sample[i]))
    keys=list(sample[index])
    if index:
        # В Excel объединённая подпись часто занимает только верхнюю строку.
        for i,k in enumerate(keys):
            if not k and i<len(sample[index-1]):
                keys[i]=sample[index-1][i]
    for values in chain(sample[index+1:],rows):
        yield {k:v for k,v in zip(keys,values) if k}


def records(path,aliases):
    ext=path.suffix.lower()
    if ext==".xlsx":
        book=load_workbook(path,read_only=True,data_only=True)
        try:
            rows=iter(book.active.values)
            yield from table_rows(rows,aliases)
        finally:
            book.close()
    elif ext==".jsonl":
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
                    return max((sum(header(c) in aliases or c.startswith("ym:") for c in r) for r in rows),default=0)
                delim="\t" if ext==".tsv" else max((";",",","\t"),key=header_score)
            yield from table_rows(iter(csv.reader(f,delimiter=delim)),aliases)


def log_kind(path):
    """Брать вид таблицы из заголовка, в том числе у безымянных частей экспорта."""
    path=Path(path)
    if path.is_dir():
        return None
    rows=records(path,{header(a) for opts in ALIASES.values() for a in opts})
    try:
        keys=next(rows,{})
    finally:
        rows.close()
    if isinstance(keys,dict):
        if "ym:s:visitID" in keys:
            return "visits"
        if "ym:pv:watchID" in keys or "ym:pv:visitID" in keys:
            return "hits"
    return None


def ordered_files(files):
    return sorted(files,key=lambda f:{"visits":0,None:1,"hits":2}[log_kind(f)])


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
    text=str(v).strip().replace("\u00a0","").replace(" ","").replace(",",".")
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


def timed_records(db,path,aliases,default):
    stream=records(path,aliases)
    if log_kind(path)!="hits":
        yield from enumerate(stream)
        return
    # Сортировка на диске сохраняет исходный номер для дедупликации даже
    # в несортированных выгрузках. Дата с ошибкой проверяется при разборе.
    db.execute("DROP TABLE IF EXISTS temp.history_hits")
    db.execute("CREATE TEMP TABLE history_hits(line INTEGER PRIMARY KEY,ts REAL,body TEXT)")
    def encoded():
        for i,row in enumerate(stream):
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
    return [ingest(engine,f,mapping,visits_with_hits=hits) for f in files]


def ingest(engine,filename,mapping=None,*,visits_with_hits=False):
    path=Path(filename)
    engine.catalog.legacy_category_names=engine.names["category"]
    raw=path.is_dir()
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
    columns={}
    period=[]
    observed=zero=0
    def recognize_logs(keys):
        columns.update({k:LOGS[k] for k in keys if k in LOGS})
        known.update(k for k in keys if k in LOGS)
        unknown.update(k for k in keys if k not in LOGS)

    def visit_orders(meta,ident,sid,ts):
        ids=meta.get("order_ids",[])
        values=meta.get("amounts",[])
        for i,oid in enumerate(ids):
            value=values[i] if i<len(values) else None
            event("ym_visit_order_"+str(oid),"order",ident,ts,sid,meta.get("client_id","guest"),value=value,
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
        for f in files:
            default=f.stat().st_mtime
            for i,r in timed_records(db,f,aliases,default):
                stats["rows"]=stats.get("rows",0)+1
                if not isinstance(r,dict):
                    reasons["Запись не является объектом"]+=1
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
                    for wid in watchers:
                        db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",("settings:watch:"+str(wid),vid,default))
                    db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",("settings:visit:"+vid,dump(visits[vid]),default))
                    if not visits_with_hits:
                        url=r.get("ym:s:startURL") or ""
                        try:
                            terms=parse_qs(urlsplit(url).query)
                        except ValueError:
                            terms={}
                        q=next((terms[k][0] for k in ("q","query","text","search") if k in terms),None)
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
                input_headers=tuple(r) if "ym:pv:watchID" in r or "ym:pv:visitID" in r else ()
                if "ym:pv:watchID" in r and "ym:pv:visitID" not in r:
                    visit=visits.get("watch:"+str(r["ym:pv:watchID"]))
                    if not visit:
                        saved=db.execute("SELECT value FROM kv WHERE key=?",("settings:watch:"+str(r["ym:pv:watchID"]),)).fetchone()
                        visit=saved[0] if saved else None
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
                        query=parse_qs(urlsplit(r.get("ym:pv:URL","")).query)
                    except ValueError:
                        reasons["Неверный URL хита"]+=1
                        stats["skipped"]+=1
                        continue
                    q=p.get("site_search_query") or next((query[k][0] for k in ("q","query","search","text") if k in query),None)
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
                        ids=[engine.catalog.offers_by_id[x["id"]].card_id if x["id"] in engine.catalog.offers_by_id else x["id"] for x in impressions]
                        track(ts,p.get("search_results_count"),1,int(p.get("search_results_count")==0))
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
                        offer=engine.catalog.offers_by_id.get(item.get("id"))
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
                        if kind=="click":
                            log_flags.add("click")
                            log_has_position|=item.get("position") is not None
                        if kind in ("order","click") and (offer or item.get("card_id") in engine.catalog.cards or item.get("id") in engine.catalog.cards):
                            log_targets+=1
                        if kind=="order" and margin is None and revenue is not None and offer:
                            margin=round(float(revenue)*offer.margin,2)
                        event(str(p.get("event_id") or eid),kind,ident,ts,sid,client,card_id=item.get("card_id") or item.get("id"),
                              offer_id=item.get("id"),position=item.get("position"),qty=item.get("quantity"),
                              value=revenue,margin_value=margin,payload=p.get("payload",{}))
                        active[ident]=True
                    else:
                        stats["skipped"]+=1
                        reasons["Хит без поискового события"]+=1
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
                    amounts={k:amount(row.get(k)) for k in ("click","cart","order","lead")}
                    pos=amount(row.get("position")) or None
                    revenue=number(row.get("revenue") or 0)
                    count=amount(row["n_cards"]) if row.get("n_cards") not in ("",None) else None
                    if q.casefold() in {"итого","всего","total","totals"}:
                        stats["skipped"]+=1
                        reasons["Итоговая строка отчёта"]+=1
                        continue
                    if not q or len(q)>1500 or n<1 or not 0<=rate<=1 or any(v>n for v in amounts.values()):
                        raise ValueError()
                except (TypeError,ValueError,SyntaxError):
                    stats["skipped"]+=1
                    reasons["Пустая фраза или неверное числовое поле"]+=1
                    continue
                track(ts,count if "zero_rate" not in row else rate,n,round(n*rate) if "zero_rate" in row else n if count==0 else 0)
                target=str(row.get("target") or "")
                explicit=any(header(name) in {"target","target card","target card id","целевой товар"} for name,assigned in columns.items() if assigned=="target") if target else False
                offer=engine.catalog.offers_by_id.get(target) or engine.catalog.skus.get(sku_key(target)) if target else None
                card_id=offer.card_id if offer else target if target in engine.catalog.cards else None
                table_target|=bool(card_id and (explicit or amounts["click"] or amounts["order"]))
                has.update(k for k,v in row.items() if v not in (None,""))
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
            if not active.get(ident):
                event(ident+"_exit","exit",ident,ts,sid,visits.get(sid,{}).get("client_id","guest"))
        for _,ddl in triggers:
            db.execute(ddl)
        if log_flags:
            db.execute("""UPDATE analytics_observation SET orders=?,revenue=?,clicks=?
                          WHERE id IN (SELECT id FROM imported_log_search)""",tuple(k in log_flags for k in ("order","revenue","click")))
        logs=any(str(k).startswith("ym:pv:") for k in known)
        if logs:
            has.update(log_flags)
            if observed:
                has.add("n_cards")
        missing=[]
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
            if has.intersection({"bounce","visits"}):
                missing.append("Агрегаты Метрики распределены по визитам. Отказ в визите служит приближением ухода.")
        if not log_targets and not table_target:
            missing.append("Для цели в топ-5 нужен идентификатор товара либо товар клика или заказа из каталога.")
        availability=dict(zero_rate="наблюдение" if has.intersection({"n_cards","zero_rate"}) else "модель поиска по словам",
            orders="наблюдение" if "order" in has else "нет цели заказа",revenue="наблюдение" if "revenue" in has else "нет суммы заказа",
            ctr="наблюдение" if "click" in has else "нет кликов",click_position="по событиям" if log_has_position or "position" in has else "нет позиций клика",
            exit_after_fail="по событиям" if logs else "приближение по отказам" if "bounce" in has else "нет отказов",
            top5_hit="по целевому товару в кликах и заказах" if log_targets or table_target else "нет разметки целевого товара",reformulation="по визитам и хитам" if logs else "нет последовательности событий")
        report=dict(columns=columns,rows_read=stats["rows"] if stats["rows"] else 0,rows_accepted=stats["rows"]-stats["skipped"],
                    period=period,observed_searches=observed,observed_empty=zero,zero_rate=zero/observed if observed else None,availability=availability,file=path.name,source_type="Logs API" if logs or any(str(k).startswith("ym:s:") for k in known) else "Отчёт Метрики" if has.intersection({"visits","bounce"}) else "Журнал поиска",**stats,skip_reasons=dict(reasons),recognized=sorted(known),ignored=sorted(unknown),
                    visits=len(visits),fields=sorted(has),logs=logs,missing=missing)
        db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",("settings:import-report:"+path.name,dump(report),time()))
        previous=db.execute("SELECT value FROM kv WHERE key='settings:history_source'").fetchone()
        if imported and (stats["events"] or stats["searches"] or new_members or not previous or previous[0]!="import"):
            db.execute("INSERT OR REPLACE INTO kv VALUES ('settings:history_source','import',?)",(time(),))
            db.execute("DELETE FROM analytics_reports")
            db.execute("UPDATE analytics_revision SET revision=revision+1")
            db.execute("INSERT OR REPLACE INTO kv VALUES ('settings:active_replay','',?)",(time(),))
    with j.transaction():
        reports=[json.loads(r["value"]) for r in j.rows("SELECT value FROM kv WHERE key LIKE 'settings:import-report:%' ORDER BY updated")]
        dest=Path(j.path).parent/"history_report.json"
        with NamedTemporaryFile("w",dir=dest.parent,delete=False) as out:
            json.dump({"files":reports},out,ensure_ascii=False,indent=2)
        Path(out.name).replace(dest)
    return report
