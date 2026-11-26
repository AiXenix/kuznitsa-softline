"""Базовые правила Neon, правки магазина и события допродаж."""
from copy import copy
import json
import os
from pathlib import Path
from time import time
from kuznitsa.config import ROOT
from kuznitsa.kb.upsell import load_rules,query_matches,validate
from kuznitsa.rank.upsell import audience,audience_values
from kuznitsa.schema import Request
from kuznitsa.text import normalize
from .store import dump, result_cards


def base(path,mtime,size):
    rules,stamp,_=load_rules(path,mtime,size)
    return rules,stamp


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
    def matches(card,side,*,target=False):
        offer=card.offers[0]
        actual={"classes":[card.category,offer.attrs.get("class_id")],
                "families":[card.family,card.category,offer.attrs.get("line_id")],"vendors":[card.vendor,offer.vendor]}
        if any(w.casefold() in card.title.casefold() for w in side.get("exclude_words",[])):
            return False
        expected=side.get("audience")
        if target and expected and not any(
            (audience(o.name) or o.lic.audience) in [None,*audience_values(expected)] for o in card.offers
        ):
            return False
        if side.get("strict"):
            actual["families"]=[card.family,offer.attrs.get("line_id"),card.title]
        checks=[{str(v).casefold() for v in vs if v}.intersection(str(x).casefold() for x in side[k])
                for k,vs in actual.items() if side.get(k)]
        return bool(checks) and (all(checks) if side.get("strict") else any(checks))
    when=draft["when"]
    words=when.get("query_words")
    scope=any(when.get(k) for k in ("classes","families","vendors"))
    requested=audience(q) or (audience(main[0].title) if main else None)
    matched=(draft["enabled"] and main and (not words or query_matches(words,normalize(q)))
             and (not scope or matches(main[0],when))
             and (not requested or not when.get("audience") or requested in audience_values(when["audience"])))
    excluded={c.id for c in main}
    items=[]
    if matched:
        candidates=(c for c in engine.catalog.cards.values() if c.id not in excluded and matches(c,draft["offer"],target=True))
        for c in sorted(candidates,key=lambda c:(-max(o.popularity for o in c.offers),c.id))[:min(1,len(excluded)//2)]:
            items.append(dict(card_id=c.id,title=c.title,rule_id=draft["id"],reason=draft["reason"]))
    return dict(q=q,matched=bool(matched),main_count=len(excluded),items=items,note="Кандидаты одного правила на текущей выдаче. Места в ленте расставляет витринный движок.")
