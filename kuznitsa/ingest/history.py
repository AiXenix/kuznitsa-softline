"""Импорт потоковых таблиц и Logs API. Все изменения файла атомарны."""
import csv
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
from kuznitsa.text import normalize

ALIASES={
    "q":["query","поисковая фраза","поисковый запрос","запрос","ym:s:searchphrase","q_raw","text"],
    "visits":["визиты","ym:s:visits"],"bounce":["отказы","отказы, %","доля отказов","ym:s:bouncerate"],
    "count":["поиски","частота","searches"],"n_cards":["результаты","число результатов","results_count","results"],
    "zero_rate":["доля пустых выдач","zero_rate"],"ts":["дата","дата и время","timestamp","time","datetime"],
    "session_id":["визит","visitid","visit_id"],"client_id":["клиент","clientid"],"segment":["сегмент"],
    "click":["клик","клики","clicks"],"order":["заказ","заказы","orders","достижения цели: заказ оформлен"],
    "cart":["корзины","достижения цели: добавление в корзину"],"lead":["достижения цели: запрос кп"],
    "revenue":["доход (₽)","выручка","value"]}


def table_rows(rows,aliases):
    sample=list(islice(rows,12))
    if not sample:
        return
    def score(row):
        return sum(str(v).strip().lower() in aliases or str(v).startswith("ym:") for v in row)
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
                delim="\t" if ext==".tsv" else ";"
            yield from table_rows(iter(csv.reader(f,delimiter=delim)),aliases)


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
    imported_ids=set()
    observations={}
    has=set()
    reasons=Counter()

    def save(ident,q,ts,sid,client,segment,count=None,ids=None,category=None,previous=None):
        existing=db.execute("SELECT session_id FROM searches WHERE search_id=?",(ident,)).fetchone()
        imported_ids.add(ident)
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
            for i,r in enumerate(records(f,aliases)):
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
                        observations[ident]=(True,True,True)
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
                    revenue=number(row.get("revenue") or 0)
                    count=amount(row["n_cards"]) if row.get("n_cards") not in ("",None) else None
                    if not q or len(q)>1500 or n<1 or not 0<=rate<=1 or any(v>n for v in amounts.values()):
                        raise ValueError()
                except (TypeError,ValueError):
                    stats["skipped"]+=1
                    reasons["Пустая фраза или неверное числовое поле"]+=1
                    continue
                has.update(k for k,v in row.items() if v not in (None,""))
                prefix="import_"+hashlib.sha256((str(i)+dump({k:str(v) for k,v in row.items()})).encode()).hexdigest()[:24]
                for k in range(n):
                    ident=prefix+"_"+str(k)
                    observations[ident]=tuple(field in row and row[field] not in ("",None) for field in ("order","revenue","click"))
                    sid=str(row.get("session_id") or (prefix+"_v"+str(k%visits_n) if visits_n else ident))
                    client=str(row.get("client_id") or "guest")
                    size=(0 if k<round(n*rate) else count or 1) if "zero_rate" in row else count
                    if save(ident,q,ts,sid,client,row.get("segment") or "unknown",size):
                        if "bounce" in row and k>=n-round((visits_n or n)*bounce):
                            event(ident+"_bounce","exit",ident,ts,sid,client,payload={"aggregate":True})
                        for kind,num in amounts.items():
                            if k<num:
                                event(ident+kind,kind,ident,ts,sid,client,value=revenue/num if kind=="order" else None)
        for sid,(ident,ts,q) in last.items():
            if not active.get(ident):
                event(ident+"_exit","exit",ident,ts,sid,visits.get(sid,{}).get("client_id","guest"))
        logs=any(str(k).startswith("ym:pv:") for k in known)
        missing=[]
        if not logs:
            for field,label in [("order","Нет данных о заказах: конверсия недоступна."),("revenue","Нет сумм заказов: выручка и потери не оценены."),
                                ("click","Нет кликов: CTR недоступен."),("ts","Нет дат: используется дата файла.")]:
                if field not in has:
                    missing.append(label)
            if not has.intersection({"n_cards","zero_rate"}):
                missing.append("Нет размеров исходной выдачи. Обычный поиск по словам воспроизведён по каталогу.")
            if has.intersection({"bounce","visits"}):
                missing.append("Агрегаты Метрики распределены по визитам. Отказ в визите служит приближением ухода.")
        availability=dict(zero_rate="наблюдение" if logs or has.intersection({"n_cards","zero_rate"}) else "модель поиска по словам",
            orders="наблюдение" if logs or "order" in has else "нет цели заказа",revenue="наблюдение" if logs or "revenue" in has else "нет суммы заказа",
            ctr="наблюдение" if logs or "click" in has else "нет кликов",click_position="по событиям" if logs else "нет позиций клика",
            exit_after_fail="по событиям" if logs else "приближение по отказам" if "bounce" in has else "нет отказов",
            top5_hit="нет разметки целевого товара",reformulation="по визитам и хитам" if logs else "нет последовательности событий")
        report=dict(availability=availability,file=path.name,**stats,skip_reasons=dict(reasons),recognized=sorted(known),ignored=sorted(unknown),
                    visits=len(visits),fields=sorted(has),logs=logs,missing=missing)
        if imported_ids:
            db.executemany("INSERT OR REPLACE INTO analytics_observation VALUES (?,?,?,?)",((i,*flags) for i,flags in observations.items()))
            db.executemany("INSERT OR IGNORE INTO analytics_import_ids VALUES (?)",((i,) for i in imported_ids))
            db.execute("INSERT OR REPLACE INTO kv VALUES ('settings:history_source','import',?)",(time(),))
            db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",("settings:import-report:"+path.name,dump(report),time()))
            db.execute("DELETE FROM analytics_reports")
            db.execute("UPDATE analytics_revision SET revision=revision+1")
            if stats["searches"] or stats["events"]:
                db.execute("INSERT OR REPLACE INTO kv VALUES ('settings:active_replay','',?)",(time(),))
    return report
