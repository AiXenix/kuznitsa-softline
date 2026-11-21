"""Приоритеты применяются к выбранным предложениям после проверки ограничений."""
from datetime import date, datetime, timezone
from functools import lru_cache
import json
from kuznitsa.plans.base import descendants
from kuznitsa.text import normalize
from .fit import TIERS

CRITERIA=dict(popularity="Популярность",margin="Маржа",personal="Профиль клиента",stock="Наличие и срок поставки",
              novelty="Новизна",price_low="Низкая цена",domestic="Отечественный продукт",promo="Акция",conversion="Конверсия в заказ")
TAGS=dict(domestic="Отечественный продукт",fstec="ФСТЭК",fsb="ФСБ",in_stock="В наличии",promo="Акция",new="Новинка",
          subscription="Подписка",perpetual="Бессрочная лицензия",cloud="Облако",electronic="Электронная поставка",
          box="Коробка",edu="Образование",gov="Государственные учреждения")


class Priorities:
    """Кэш хранит только решения для конкретных предложений, дня и версии правил."""
    def __init__(self, rows, catalog):
        self.rows = rows
        self.catalog = catalog
        self.query_scope = any(r.get("scope",{}).get("queries") for r,*_ in rows)
        self.resolve = lru_cache(maxsize=128)(self._resolve)

    def _resolve(self, day, scope, items, exact):
        ctx = dict(zip(("segment","profile_id","region","intent","channel","q_norm"),scope))
        cards = [dict(card_id=cid,offer=dict(offer_id=oid,price=price),
                      score=dict(tier=tier,score=score,parts={"pers":personal}),badges=[])
                 for cid,oid,price,tier,score,personal in items]
        applied,moves = evaluate(cards,self.rows,ctx,self.catalog,day,exact)
        order = tuple((c["card_id"],c["score"]["tier"],tuple(b["label"] for b in c["badges"])) for c in cards)
        return order,applied,moves


def compile_rules(catalog,kb,rules,journal=None):
    conversion={}
    if journal is not None and hasattr(journal,"rows") and any("conversion" in (r.get("action",{}).get("criteria") or {}) for r in rules):
        rows=journal.rows("""WITH orders AS (SELECT DISTINCT search_id,card_id FROM events WHERE type='order')
            SELECT j.value AS card_id, AVG(o.search_id IS NOT NULL) AS fraction
            FROM searches s, json_each(s.top_cards_json) j
            LEFT JOIN orders o ON o.search_id=s.search_id AND o.card_id=j.value
            WHERE s.source IN ('ui','api','widget','history') GROUP BY j.value""")
        conversion={r["card_id"]:r["fraction"] for r in rows}

    compiled=[]
    target_keys={}
    scope_keys={}
    for rule in sorted((r for r in rules if r.get("enabled",True)),key=lambda r:r.get("order",0)):
        target=rule.get("target",{})
        ids=None
        for field,index in (("categories","category"),("vendors","vendor"),("families","family"),("cards",None)):
            values=target.get(field)
            if values:
                if field=="categories":
                    values=descendants(kb,values)
                subset=set(values) if index is None else set().union(*(catalog.by[index].get(v,()) for v in values))
                ids=subset if ids is None else ids & subset
        target_key=target_keys.setdefault(json.dumps(target,sort_keys=True),len(target_keys))
        scope_key=scope_keys.setdefault(json.dumps(rule.get("scope",{}),sort_keys=True),len(scope_keys))
        compiled.append((rule,ids,conversion,target_key,scope_key))
    return Priorities(compiled,catalog) if compiled else None


def scope_matches(scope,ctx,today):
    for field,key in (("segments","segment"),("profiles","profile_id"),("regions","region"),("intents","intent"),("channels","channel")):
        if scope.get(field) and ctx.get(key) not in scope[field]:
            return False
    return (not scope.get("from") or scope["from"]<=today) and (not scope.get("to") or today<=scope["to"]) and (
        not scope.get("queries") or any(normalize(q) in ctx["q_norm"] for q in scope["queries"]))


def facts(o,card,today):
    def value(k):
        v=getattr(o,k,None)
        return o.attrs.get(k) if v is None else v
    def flag(k):
        return str(value(k)).lower() in ("true","1","да")
    added=value("added_at")
    try:
        age=(today-date.fromisoformat(str(added)[:10])).days
    except ValueError:
        age=None
    fresh=age is not None and 0<=age<=30
    tags=set(o.certs)|{o.lic.model,o.lic.audience,"electronic" if o.delivery=="esd" else o.delivery}
    if "cloud" in card.kb.get("deployment",[]) or o.attrs.get("deployment")=="cloud":tags.add("cloud")
    for tag,yes in (("domestic",o.registry or flag("domestic")),("promo",flag("promo")),("new",fresh),("in_stock",flag("in_stock"))):
        if yes:tags.add(tag)
    days=value("delivery_days")
    pop,margin=card.commercial[o.offer_id]
    vals=dict(popularity=pop,margin=margin)

    if age is not None:vals["novelty"]=1/(1+max(0,age)/30)
    if value("in_stock") is not None:
        delay=int(days) if str(days).isdigit() else 0
        vals["stock"]=float(flag("in_stock"))/(1+delay)
    if o.registry is not None or value("domestic") is not None:vals["domestic"]=int("domestic" in tags)
    if value("promo") is not None:vals["promo"]=int("promo" in tags)
    return tags,vals


def apply(cards,compiled,ctx,catalog,now,exact=False,signals=None):
    if not compiled or len(cards)<1:return [],[]
    day=datetime.fromtimestamp(now,timezone.utc).date()
    scope=tuple(ctx.get(k) for k in ("segment","profile_id","region","intent","channel")) + (
        ctx.get("q_norm","") if compiled.query_scope else "",)
    items=tuple((c["card_id"],c["offer"]["offer_id"],c["offer"]["price"],c["score"]["tier"],
                 c["score"]["score"],signals[c["card_id"]] if signals else c["score"]["parts"].get("pers",0)) for c in cards)
    order,applied,moves=compiled.resolve(day,scope,items,exact)
    if applied:
        by_id={c["card_id"]:c for c in cards}
        cards[:]=[by_id[cid] for cid,_,_ in order]
        for c,(_,tier,labels) in zip(cards,order):
            c["score"].update(tier=tier,tier_label=TIERS[tier])
            c["badges"].extend(dict(kind="priority",label=label) for label in labels)
    return [dict(r) for r in applied],[dict(m) for m in moves]


def evaluate(cards,compiled,ctx,catalog,day,exact):
    positions={c["card_id"]:i for i,c in enumerate(cards,1)}
    hits={}
    boosts={}
    criteria={}
    claimed_criteria=set()
    cross_tier_boost={}
    applied=[]
    initial={c["card_id"]:c["score"]["tier"] for c in cards}
    protected={k for k,t in initial.items() if exact and t==0}
    priced=[c["offer"]["price"] for c in cards if c["offer"]["price"] is not None]
    lo,hi=(min(priced),max(priced)) if priced else (0,0)
    by_id={c["card_id"]:c for c in cards}
    member_sets={}
    scopes={}
    group_boost={}
    group_cross={}
    today=day.isoformat()

    def offer_facts(cid):
        if cid not in hits:
            offer=catalog.offers_by_id[by_id[cid]["offer"]["offer_id"]]
            hits[cid]=facts(offer,catalog.cards[cid],day)
        return hits[cid]

    for rule,ids,conversion,target_key,scope_key in compiled:
        if scope_key not in scopes:
            scopes[scope_key]=scope_matches(rule.get("scope",{}),ctx,today)
        if not scopes[scope_key]:
            continue
        if target_key not in member_sets:
            target=rule.get("target",{})
            tags=target.get("tags")
            bound=target.get("price_rub") or {}
            members=set(by_id) if ids is None else by_id.keys() & ids
            if bound:
                lower,upper=bound.get("min"),bound.get("max")
                members={cid for cid in members if (price:=by_id[cid]["offer"]["price"]) is not None and
                         (lower is None or lower<=price) and (upper is None or price<=upper)}
            if tags:
                members={cid for cid in members if not offer_facts(cid)[0].isdisjoint(tags)}
            member_sets[target_key]=members
        members=member_sets[target_key]
        if not members:
            continue
        applied.append((rule,members))
        act=rule["action"]
        weights=act.get("criteria")
        if weights:
            for cid in members-claimed_criteria:
                _,vals=offer_facts(cid)
                if cid in conversion:vals["conversion"]=conversion[cid]
                vals["personal"]=by_id[cid]["score"]["parts"].get("pers",0.)
                price=by_id[cid]["offer"]["price"]
                if price is not None:vals["price_low"]=(hi-price)/(hi-lo) if hi>lo else 1.
                total=sum(w for key,w in weights.items() if key in vals)
                if total:
                    criteria[cid]=sum(w*vals[key] for key,w in weights.items() if key in vals)/total
            claimed_criteria.update(members)
        boost=act.get("boost",0)
        if boost:
            group_boost[target_key]=group_boost.get(target_key,0)+boost
            if rule.get("cross_tier") or act.get("cross_tier"):
                group_cross[target_key]=group_cross.get(target_key,0)+boost
        if act.get("public_label"):
            for cid in members:
                by_id[cid]["badges"].append(dict(kind="priority",label=act["public_label"]))
    for target_key,value in group_boost.items():
        for cid in member_sets[target_key]:
            boosts[cid]=boosts.get(cid,0)+value
    for target_key,value in group_cross.items():
        for cid in member_sets[target_key]-protected:
            cross_tier_boost[cid]=cross_tier_boost.get(cid,0)+value
    if not applied:return [],[]
    for k,delta in cross_tier_boost.items():
        tier=max(0,min(3,initial[k]-(delta>0)+(delta<0)))
        by_id[k]["score"].update(tier=tier,tier_label=TIERS[tier])
    baseline={}
    floors={}
    for c in cards:
        tier=initial[c["card_id"]]
        floors[tier]=min(floors.get(tier,float("inf")),c["score"]["score"])
        baseline[c["card_id"]]=floors[tier]
    def order(c):
        k=c["card_id"]
        adjustment=max(-100,min(100,boosts.get(k,0)))/100
        return c["score"]["tier"],k not in protected,-(criteria.get(k,baseline[k])+adjustment),positions[k]
    # Только затронутые уровни пересортировываются. При нулевом изменении сохраняется разнообразие выдачи.
    if any(boosts.values()) or criteria or any(cross_tier_boost.values()):
        cards.sort(key=order)
    for rule,members in applied:
        act=rule["action"]
        cap=act.get("max_in_top")
        if cap:
            used=0
            for i,c in enumerate(cards[:cap["n"]]):
                if c["card_id"] not in members:continue
                used+=1
                if used<=cap["k"] or c["card_id"] in protected:continue
                j=next((j for j in range(cap["n"],len(cards)) if cards[j]["card_id"] not in members and cards[j]["card_id"] not in protected and
                        cards[j]["score"]["tier"]==c["score"]["tier"]),None)
                if j is not None:cards[i],cards[j]=cards[j],cards[i]
        pin=act.get("pin")
        if pin and pin["card_id"] in members-protected:
            i=next(i for i,c in enumerate(cards) if c["card_id"]==pin["card_id"])
            permitted=[j for j,c in enumerate(cards) if c["score"]["tier"]==cards[i]["score"]["tier"] and c["card_id"] not in protected]
            j=max(permitted[0],min(pin["position"]-1,permitted[-1]))
            cards.insert(j,cards.pop(i))
    moves=[dict(card_id=c["card_id"],before=positions[c["card_id"]],after=i) for i,c in enumerate(cards,1) if positions[c["card_id"]]!=i]
    moved={row["card_id"] for row in moves}
    fired=[dict(id=r["id"],title=r.get("title"),matched=len(m),moved=len(m & moved)) for r,m in applied]
    return fired,moves
