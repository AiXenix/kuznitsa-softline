"""Импорт потоковых таблиц и Logs API. Все изменения файла атомарны."""
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from math import isfinite
from urllib.parse import urlsplit,parse_qs

import yaml
from openpyxl import load_workbook
from kuznitsa.analytics.store import dump
from kuznitsa.mock.querylog_gen import MSK, describe
from kuznitsa.plans.naive import match
from kuznitsa.text import normalize

ALIASES={
    "q":["query","поисковая фраза","поисковый запрос","запрос","ym:s:searchphrase","q_raw","text"],
    "count":["поиски","частота","searches"],"n_cards":["результаты","число результатов","results_count","results"],
    "zero_rate":["доля пустых выдач","zero_rate"],"ts":["дата","дата и время","timestamp","time","datetime"],
    "session_id":["визит","visitid","visit_id"],"client_id":["клиент","clientid"],"segment":["сегмент"],
    "click":["клик","клики","clicks"],"order":["заказ","заказы","orders","достижения цели: заказ оформлен"],
    "cart":["корзины","достижения цели: добавление в корзину"],"lead":["достижения цели: запрос кп"],
    "revenue":["доход (₽)","выручка","value"]}


def records(path):
    ext=path.suffix.lower()
    if ext==".xlsx":
        book=load_workbook(path,read_only=True,data_only=True)
        try:
            rows=iter(book.active.values)
            keys=next(rows,[])
            for values in rows:
                yield dict(zip(keys,values))
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
        with path.open(encoding="utf-8-sig",newline="") as f:
            sample=f.read(8192)
            f.seek(0)
            try:
                delim=csv.Sniffer().sniff(sample,delimiters=";,\t").delimiter
            except csv.Error:
                delim="\t" if ext==".tsv" else ";"
            yield from csv.DictReader(f,delimiter=delim)


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


def number(v):
    text=str(v).strip().replace("\u00a0","").replace(" ","").replace(",",".")
    value=float(text)
    if not isfinite(value):
        raise ValueError("Нечисловое значение")
    return value


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
    return json.loads(value) if isinstance(value,str) and value else value or default


def ingest(engine,filename,mapping=None):
    path=Path(filename)
    raw=path.is_dir()
    if raw:
        files=sorted(path.glob("*visits*"))+sorted(path.glob("*hits*"))
        if not files:
            raise ValueError("В каталоге нужны файлы visits и hits")
    else:
        files=[path]
    mapped=yaml.safe_load(Path(mapping).read_text()) if mapping else {}
    aliases={a:k for k,opts in ALIASES.items() for a in [k,*opts]}
    for k,v in (mapped or {}).items():
        if k in ALIASES and v not in ALIASES:
            aliases[str(v).strip().lower()]=k
        elif v in ALIASES:
            aliases[str(k).strip().lower()]=v
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
    reasons=Counter()

    def save(ident,q,ts,sid,client,segment,count=None,ids=None,category=None,previous=None):
        existing=db.execute("SELECT session_id FROM searches WHERE search_id=?",(ident,)).fetchone()
        if existing:
            if existing[0]!=sid:
                native.add(ident)
            stats["duplicates"]+=1
            return False
        key=(q,ids is not None)
        if key not in cache:
            if ids is None:
                matches=match(engine.catalog,q,limit=None)
                hits=matches[:20]
                total=len(matches)
            else:
                hits=[engine.catalog.cards[c].offers[0] for c in ids if c in engine.catalog.cards]
                total=len(ids)
            cache[key]=(hits,total,describe(engine,q,hits))
        hits,total,(intent,reason,cat,_,filters,entities)=cache[key]
        count=total if count is None else int(count)
        j.insert("searches",dict(search_id=ident,ts=ts,session_id=sid,client_id=client,segment=segment,source="history",
                 engine="legacy",mode="naive",q_raw=q,q_norm=normalize(q),q_corrected=normalize(q),intent=intent,
                 prev_search_id=previous,category_ctx=category or cat,filters_json=filters,entities_json=entities,n_cards=count,zero=int(not count),
                 fail_reason=reason if not count else None,top_cards_json=dump(ids if ids is not None else [o.card_id for o in hits][:count]),
                 blocks_json=dump(["products"] if count else [])))
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
        for f in files:
            default=f.stat().st_mtime
            for i,r in enumerate(records(f)):
                if not isinstance(r,dict):
                    stats["skipped"]+=1
                    continue
                if "ym:s:visitID" in r:
                    try:
                        vid=str(r["ym:s:visitID"])
                        visits[vid]=dict(zip(unpack(r.get("ym:s:parsedParamsKey1"),[]),unpack(r.get("ym:s:parsedParamsKey2"),[])))
                    except (TypeError, ValueError):
                        stats["skipped"]+=1
                        reasons["Параметры визита не распознаны"]+=1
                        continue
                    db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",("settings:visit:"+vid,dump(visits[vid]),default))
                    known.update(r)
                    continue
                if "ym:pv:visitID" in r:
                    known.update(r)
                    sid=str(r["ym:pv:visitID"])
                    if sid not in visits:
                        saved=db.execute("SELECT value FROM kv WHERE key=?",("settings:visit:"+sid,)).fetchone()
                        visits[sid]=json.loads(saved[0]) if saved else {}
                    meta=visits[sid]
                    client=meta.get("client_id",str(r.get("ym:pv:clientID","guest")))
                    try:
                        ts=timestamp(r.get("ym:pv:dateTime"),default)
                        p=unpack(r.get("ym:pv:params"),{})
                        goals=unpack(r.get("ym:pv:goalsID"),[])
                        if not isinstance(p,dict) or not isinstance(p.get("ecommerce",{}),dict):
                            raise ValueError()
                        if "search_results_count" in p:
                            p["search_results_count"]=int(p["search_results_count"])
                    except (TypeError,ValueError):
                        stats["skipped"]+=1
                        reasons["Не распознаны время или параметры хита"]+=1
                        continue
                    ec=p.get("ecommerce",{})
                    query=parse_qs(urlsplit(r.get("ym:pv:URL","")).query)
                    q=p.get("site_search_query") or next((query[k][0] for k in ("q","query","search","text") if k in query),None)
                    wid=str(r.get("ym:pv:watchID",i))
                    eid="ym_"+sid+"_"+wid
                    if q:
                        ident=str(p.get("search_id") or eid)
                        impressions=ec.get("impressions",[])
                        ids=[engine.catalog.offers_by_id[x["id"]].card_id if x["id"] in engine.catalog.offers_by_id else x["id"] for x in impressions]
                        save(ident,q,ts,sid,client,meta.get("segment","unknown"),p.get("search_results_count"),ids,p.get("search_category_ctx"),(p.get("inherited") or {}).get("from_search_id"))
                        if sid in last:
                            prev,t,old=last[sid]
                            if 0<=ts-t<=180 and normalize(old)!=normalize(q) and not active.get(prev) and not p.get("inherited"):
                                event(prev+"_reform","reformulate",prev,ts,sid,client,payload={"to":q})
                        last[sid]=ident,ts,q
                        if impressions:
                            event(ident+"_impression","impression",ident,ts,sid,client,payload={"cards":[x["id"] for x in impressions]})
                        continue
                    if sid not in last:
                        stats["skipped"]+=1
                        continue
                    ident=last[sid][0]
                    kind=p.get("event_type") or next((k for k,g in [("order",301007),("lead",301006),("cart",301005),("click",301004)] if g in goals),None)
                    action_key=next((k for k in ("purchase","add","click","detail") if k in ec),None)
                    kind=kind or {"purchase":"order","add":"cart","click":"click","detail":"click"}.get(action_key)
                    if kind in {"order","cart","click","lead","reformulate","exit","suggest_click","chip","correction_accept","correction_reject","suggest_show"}:
                        a=ec.get(action_key,{})
                        item=(a.get("products") or [{}])[0]
                        revenue=a.get("actionField",{}).get("revenue")
                        margin=p.get("margin_value")
                        offer=engine.catalog.offers_by_id.get(item.get("id"))
                        if kind=="order" and margin is None and revenue is not None and offer:
                            margin=round(float(revenue)*offer.margin,2)
                        event(str(p.get("event_id") or eid),kind,ident,ts,sid,client,card_id=item.get("card_id") or item.get("id"),
                              offer_id=item.get("id"),position=item.get("position"),qty=item.get("quantity"),
                              value=revenue,margin_value=margin,payload=p.get("payload",{}))
                        active[ident]=True
                    continue
                row={}
                for k,v in r.items():
                    key=aliases.get(str(k).strip().lower())
                    if key:
                        known.add(k)
                        row[key]=v
                    else:
                        unknown.add(str(k))
                q=str(row.get("q") or "").strip()
                try:
                    n=amount(row.get("count",1))
                    ts=timestamp(row.get("ts"),default)
                    raw_rate=str(row.get("zero_rate") or 0).strip()
                    rate=number(raw_rate.rstrip("%"))/(100 if raw_rate.endswith("%") else 1)
                    amounts={k:amount(row.get(k)) for k in ("click","cart","order","lead")}
                    revenue=number(row.get("revenue") or 0)
                    count=amount(row["n_cards"]) if row.get("n_cards") not in ("",None) else None
                    if not q or len(q)>1500 or n<1 or not 0<=rate<=1:
                        raise ValueError()
                except (TypeError,ValueError):
                    stats["skipped"]+=1
                    reasons["Пустая фраза или неверное числовое поле"]+=1
                    continue
                prefix="import_"+hashlib.sha256((str(i)+dump({k:str(v) for k,v in row.items()})).encode()).hexdigest()[:24]
                for k in range(n):
                    ident=prefix+"_"+str(k)
                    sid=str(row.get("session_id") or ident)
                    client=str(row.get("client_id") or "guest")
                    size=(0 if k<round(n*rate) else count or 1) if "zero_rate" in row else count
                    if save(ident,q,ts,sid,client,row.get("segment") or "unknown",size):
                        for kind,num in amounts.items():
                            if k<num:
                                event(ident+kind,kind,ident,ts,sid,client,value=revenue/num if kind=="order" else None)
        for sid,(ident,ts,q) in last.items():
            if not active.get(ident):
                event(ident+"_exit","exit",ident,ts,sid,visits.get(sid,{}).get("client_id","guest"))
    return dict(**stats,skip_reasons=dict(reasons),recognized=sorted(known),ignored=sorted(unknown),visits=len(visits))
