"""Базовые правила Neon, правки магазина и события допродаж."""
from copy import copy
from functools import lru_cache
import hashlib
import json
from time import time
from urllib.parse import urlsplit

import yaml
import os
from pathlib import Path
from kuznitsa.config import ROOT
from kuznitsa.schema import Request
from kuznitsa.text import normalize
from .store import dump, result_cards


def validate(body):
    allowed = {"id","when","offer","reason","weight","source","enabled"}
    if not isinstance(body,dict) or body.keys()-allowed:
        raise ValueError("Неизвестное поле правила")
    rule = dict(enabled=True,source="kb",weight=1.) | body
    for key in ("id","reason","source"):
        if not isinstance(rule.get(key),str) or not rule[key].strip():
            raise ValueError("Заполните поле "+key)
    if len(rule["id"])>160 or "/" in rule["id"]:
        raise ValueError("Недопустимый идентификатор")
    if type(rule["weight"]) not in (int,float) or not 0<=rule["weight"]<=1 or type(rule["enabled"]) is not bool:
        raise ValueError("Укажите вес от 0 до 1 и логический признак включения")
    if rule["source"]!="kb":
        source=urlsplit(rule["source"].removeprefix("vendor_site:"))
        if not rule["source"].startswith("vendor_site:") or source.scheme not in ("https","http") or not source.hostname:
            raise ValueError("Источник должен быть kb или vendor_site с адресом сайта")
    for key in ("when","offer"):
        group=rule.get(key)
        fields={"classes","families","vendors"}
        if key=="when":
            fields.add("query_words")
        if not isinstance(group,dict) or group.keys()-fields:
            raise ValueError("Проверьте условия "+key)
        clean={}
        for k,values in group.items():
            if not isinstance(values,list) or any(type(v) not in (str,int) or not str(v).strip() for v in values):
                raise ValueError("Ожидается список идентификаторов в "+k)
            clean[k]=list(dict.fromkeys(str(v).strip() for v in values))
        if not any(clean.values()):
            raise ValueError("Нужно хотя бы одно условие в "+key)
        rule[key]=clean
    return rule


@lru_cache(8)
def base(path,mtime,size):
    if not size:
        return {},0
    raw=path.read_bytes()
    data=yaml.safe_load(raw) or []
    if isinstance(data,dict):
        data=data["rules"]
    rules={}
    for row in data:
        rule=validate(row)
        if rule["id"] in rules:
            raise ValueError("Повторяется идентификатор базового правила")
        rules[rule["id"]]=rule
    return rules,int.from_bytes(hashlib.sha256(raw).digest()[:6],"big")


def snapshot(j):
    path=Path(os.environ.get("KZ_KB_DIR",ROOT/"kb"))/"upsell_r9.yaml"
    try:
        stat=path.stat()
        rules,stamp=base(path,stat.st_mtime_ns,stat.st_size)
    except FileNotFoundError:
        rules,stamp={},0
    with j.lock:
        db=j.db
        if not getattr(j,"_upsell_ready",False):
            db.execute("CREATE TABLE IF NOT EXISTS upsell_overrides(id TEXT PRIMARY KEY,body TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS upsell_audit(rev INTEGER PRIMARY KEY,id TEXT,op TEXT,
                        ts REAL,author TEXT,before_json TEXT,after_json TEXT)""")
            db.execute("""CREATE INDEX IF NOT EXISTS upsell_events ON events(search_id,card_id,type)
                       WHERE json_type(payload_json,'$.rule_id')='text'""")
            j._upsell_ready=not db.in_transaction
        rev=db.execute("SELECT coalesce(max(rev),0) FROM upsell_audit").fetchone()[0]
        version=(stamp,rev)
        cached=getattr(j,"_upsell_snapshot",None)
        if not cached or cached[0]!=version:
            effective=dict(rules)
            for row in db.execute("SELECT id,body FROM upsell_overrides ORDER BY id"):
                ident=row["id"]
                effective[ident]=effective.get(ident,{})|json.loads(row["body"])
                if not {"when","offer","enabled","id","reason"}<=effective[ident].keys():
                    del effective[ident]
            cached=(version,effective,[r for r in effective.values() if r["enabled"]])
            j._upsell_snapshot=cached
        return cached


def active_rules(journal):
    if not hasattr(journal,"db"):
        return 0,[]
    version,_,rules=snapshot(journal)
    return (version[0]<<32)+version[1],rules


def change(j,op,body,ident,author):
    snapshot(j)
    with j.transaction() as db:
        _,rules,_=snapshot(j)
        ident=ident or body.get("id")
        if not isinstance(ident,str):
            raise ValueError("Нужен строковый идентификатор правила")
        before=rules.get(ident)
        if op=="create" and before:
            raise ValueError("Идентификатор уже занят")
        if op!="create" and not before:
            raise KeyError(ident)
        rule=validate((before or {})|body)
        if rule["id"]!=ident:
            raise ValueError("Идентификатор правила нельзя менять")
        prior=db.execute("SELECT body FROM upsell_overrides WHERE id=?",(ident,)).fetchone()
        overlay=json.loads(prior[0]) if prior else {}
        fields=rule.keys() if op=="create" else body.keys()
        overlay.update((k,rule[k]) for k in fields)
        db.execute("INSERT OR REPLACE INTO upsell_overrides VALUES (?,?)",(ident,dump(overlay)))
        cursor=db.execute("INSERT INTO upsell_audit(id,op,ts,author,before_json,after_json) VALUES (?,?,?,?,?,?)",
                          (ident,op,time(),author,dump(before),dump(rule)))
        return dict(rule=rule,revision=cursor.lastrowid)


def audit(j):
    snapshot(j)
    rows=j.rows("SELECT * FROM upsell_audit ORDER BY rev DESC LIMIT 200")
    for row in rows:
        for key in ("before","after"):
            row[key]=json.loads(row.pop(key+"_json"))
    return dict(items=rows)


def analytics(j):
    _,rules,_=snapshot(j)
    rows=j.rows("""SELECT json_extract(e.payload_json,'$.rule_id') rule_id,json_extract(e.payload_json,'$.kind') placement,s.q_raw q,e.card_id,
        sum(type='impression') impressions,sum(type='click') clicks,sum(type='cart') carts
        FROM events e JOIN searches s USING(search_id)
        WHERE s.source IN ('ui','gallery','api','widget','compare') AND e.type IN ('impression','click','cart')
        AND json_type(e.payload_json,'$.rule_id')='text' AND e.card_id IS NOT NULL
        GROUP BY rule_id,placement,s.q_raw,e.card_id""")
    totals=dict(impressions=0,clicks=0,carts=0)
    by_rule={}
    pairs={}
    for row in rows:
        if row["placement"] not in (None,"upsell","crosssell") or row["placement"] is None and row["rule_id"] not in rules:
            continue
        group=by_rule.setdefault(row["rule_id"],dict.fromkeys(totals,0))
        pair=pairs.setdefault((row["q"],row["card_id"]),dict(q=row["q"],card_id=row["card_id"],**dict.fromkeys(totals,0)))
        for key in totals:
            totals[key]+=row[key]
            group[key]+=row[key]
            pair[key]+=row[key]
    return dict(totals=totals,by_rule=by_rule,best_pairs=sorted((p for p in pairs.values() if p["carts"]),
                key=lambda p:(-p["carts"],-p["clicks"],p["q"],p["card_id"]))[:30],
                note="События витрины за всё время. Пара означает добавление предложенной карточки в корзину.")


def listing(j):
    version,rules,_=snapshot(j)
    counts=analytics(j)["by_rule"]
    return dict(version=f"{version[0]:x}.{version[1]}",items=[r|dict(counters=counts.get(r["id"],dict(impressions=0,clicks=0,carts=0))) for r in rules.values()])


def preview(engine,q,rule):
    draft=validate(rule)
    req=Request(q=q,mode="fast",source="eval")
    feed=getattr(engine.catalog,"feed",None)
    if feed is not None and hasattr(feed,"recommend"):
        # Используем витринную расстановку A. Кэш подборщика и черновик принадлежат только этому запросу.
        trial=copy(engine)
        trial.catalog=copy(engine.catalog)
        trial.catalog.feed=copy(feed)
        rec=trial.catalog.feed.recommend=copy(feed.recommend)
        _,stored,_=snapshot(engine.journal)
        rec.provider=None
        rec.compiled=rec.compile(list((stored|{draft["id"]:draft}).values()))
        response=trial.preview(req,priorities=None)
        items=[]
        main=set()
        for block in response["blocks"]:
            for item in block.get("items",[]):
                if not isinstance(item,dict):
                    continue
                card=item.get("card",item)
                if card.get("rule_id")==draft["id"] and card.get("kind")=="upsell":
                    items.append(dict(card_id=card["card_id"],title=card["title"],rule_id=draft["id"],
                                      reason=draft["reason"],block=block["type"],position=card.get("position")))
                elif block["type"]=="products" and card.get("card_id") and not card.get("kind")=="upsell" and not card.get("fill"):
                    main.add(card["card_id"])
        return dict(q=q,matched=bool(items),main_count=len(main),items=items,
                    note="Результат быстрого поиска с черновиком и действующими правилами.")
    response=engine.preview(req,priorities=None)
    main=[engine.catalog.cards[c["card_id"]] for c in result_cards(response) if c["card_id"] in engine.catalog.cards and c.get("kind")!="upsell" and not c.get("fill")]
    def matches(card,side):
        offer=card.offers[0]
        actual={"classes":[card.category,offer.attrs.get("class_id")],
                "families":[card.family,card.category,offer.attrs.get("line_id")],"vendors":[card.vendor,offer.vendor]}
        return any(str(v).casefold()==str(x).casefold() for k,vs in actual.items() for v in vs if v for x in side.get(k,[]))
    when=draft["when"]
    phrase_match=any(normalize(w) in normalize(q) for w in when.get("query_words",[]))
    matched=draft["enabled"] and main and (phrase_match or matches(main[0],when))
    excluded={c.id for c in main}
    items=[]
    if matched:
        candidates=(c for c in engine.catalog.cards.values() if c.id not in excluded and matches(c,draft["offer"]))
        for c in sorted(candidates,key=lambda c:(-max(o.popularity for o in c.offers),c.id))[:min(1,len(excluded)//2)]:
            items.append(dict(card_id=c.id,title=c.title,rule_id=draft["id"],reason=draft["reason"]))
    return dict(q=q,matched=bool(matched),main_count=len(excluded),items=items,note="Кандидаты одного правила на текущей выдаче. Места в ленте расставляет витринный движок.")
