"""Синтетические визиты. Эталонные цели изолированы от бизнес-аналитики."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from time import time
from functools import lru_cache
from pathlib import Path
import random
import re
from zoneinfo import ZoneInfo

import yaml
from kuznitsa.analytics.store import dump
from kuznitsa.config import ROOT
from kuznitsa.plans.naive import match
from kuznitsa.schema import Client
from kuznitsa.text import normalize, tokens
from kuznitsa.understand.intent import scenario
from kuznitsa.understand.repair import LAYOUT, TRANS

MSK = ZoneInfo("Europe/Moscow")


NOISE_QUERIES={
    "hardware":["ноутбук для офиса","принтер для бухгалтерии","картридж для принтера"],
    "piracy":["активатор офис","торрент скачать бесплатно","кряк для windows"],
    "off_topic":["рецепт борща","погода на завтра","заказать пиццу"],
    "gibberish":["asdfghjkl","123456","йцукенгш"]
}


def distort(q,kind,card,rng):
    if kind=="wrong_layout":
        return q.lower().translate(LAYOUT)
    if kind=="translit":
        return "".join(TRANS.get(ch,ch) for ch in q.lower())
    if kind=="merged_tokens":
        return q.replace(" ","")
    if kind=="homoglyph_sku" and card and q in {o.sku for o in card.offers}:
        return q.translate(str.maketrans("AEOCPTX","АЕОСРТХ"))
    if kind=="typo":
        starts=[i for i in range(len(q)-1) if q[i].isalpha() and q[i+1].isalpha()]
        if starts:
            i=rng.choice(starts)
            return q[:i]+q[i+1]+q[i]+q[i+2:]
    if kind=="slang_abbr" and card and card.kb.get("aliases"):
        name=card.offers[0].family_name
        if name and name in q:
            return q.replace(name,rng.choice(card.kb["aliases"]),1)
    return q


def describe(engine, q, hits):
    filters = defaultdict(list)
    entities = []
    for a,b,found in engine.lex.match(tokens(q)):
        for kind,value,source in found:
            filters[kind].append(value)
            entities.append(dict(type=kind,id=value,source=source))
    family = next((f for f in filters["family"] if f in engine.catalog.by["family"]),next(iter(filters["family"]),None))
    info = engine.kb.rows["families"].get(family,{})
    vendor = info.get("vendor") or next(iter(filters["vendor"]),None)
    cat = info.get("category") or next(iter(filters["category"]),None)
    parsed = dict(filters)
    if parsed.get("action"):
        parsed["action"] = parsed["action"][0]
    intent = scenario(q,tokens(q),parsed,entities,None,None)
    reason = None
    if engine.kb.rows["vendors"].get(vendor,{}).get("market_status")=="left":
        reason = "vendor_left"
    elif not hits and family and family not in engine.catalog.by["family"]:
        reason = "not_in_catalog_known"
    elif not hits:
        if q.lower() in NOISE_QUERIES["off_topic"]:
            reason="off_topic"
        elif re.fullmatch(r"[0-9]+|asdfghjkl|йцукенгш",q.lower()):
            reason="gibberish"
        elif re.search("кряк|торрент|активатор",q):
            reason = "piracy"
        elif re.search("ноутбук|принтер|картридж",q):
            reason = "hardware"
        elif not family and any(w.isascii() and w.isalpha() and len(w)>=4 and w not in engine.lex.words for w in tokens(q)):
            reason = "not_in_catalog_unknown"
        else:
            reason = "unknown_term"
    elif all(o.price_on_request for o in hits):
        reason = "price_on_request_only"
    return intent,reason,cat or (hits[0].category_id if hits else None),family, dump(dict(filters)),dump(entities)


def generate(engine, seed=20261126, today=None):
    spec = yaml.safe_load((ROOT/"mock/spec/querylog.yaml").read_text())
    rng = random.Random(seed+spec["meta"]["seed_offset"])
    anchor = date.fromisoformat(today) if today else datetime.now(MSK).date()
    journal = engine.journal
    engine.catalog.legacy_category_names=engine.names["category"]
    cards = list(engine.catalog.cards.values())
    profiles = dict(engine.clients)
    for row in yaml.safe_load((ROOT/"mock/spec/profiles.yaml").read_text())["profiles"]:
        if row["id"] not in profiles:
            profiles[row["id"]]=Client.model_validate(dict(row,client_id=row["id"]))
    leads={story["client_id"] for story in spec["seeded_anomalies"] if story.get("client_id")}
    clients = [c for c in profiles.values() if c.client_id not in leads|{"guest"}]
    by_segment = defaultdict(list)
    for c in clients:
        by_segment[c.segment].append(c)
    weights = spec["seasonality"]
    daily = list(weights["day_of_week_multipliers"].values())
    hourly = list(weights["hour_of_day_weights"].values())
    end = datetime.combine(anchor,datetime.min.time(),MSK).timestamp()
    funnel = spec["session_model"]["legacy_funnel"]
    choose = rng.choice

    @lru_cache(None)
    def lookup(q):
        offers = match(engine.catalog,q,limit=None)
        hits = offers[:20]
        return hits,len(offers),dump([o.card_id for o in hits]),describe(engine,q,hits)

    def visit(client=None, window=(-89,0), segments=None):
        offsets = list(range(window[0],window[1]+1))
        ds = [daily[(anchor+timedelta(days=d)).weekday()]*(1.32 if d>=-14 else 1) for d in offsets]
        day = rng.choices(offsets,ds)[0]
        ts = end+day*86400+rng.choices(range(24),hourly)[0]*3600+rng.randrange(3400)
        if client in profiles:
            c = profiles[client]
        elif segments:
            pool = by_segment[rng.choices(list(segments),list(segments.values()))[0]]
            c = choose(pool or clients)
        else:
            c = engine.clients["guest"] if rng.random()<.38 or not clients else choose(clients)
        return ts,c

    seeded = []
    for story in spec["seeded_anomalies"]:
        phrases = story.get("queries") or story.get("sample_queries_from_cohort",[])
        if not phrases:
            continue
        for window,n in [(story["window_days"],story.get("sessions_30d",story.get("searches_count",len(phrases)))),
                         ([-59,-30],story.get("prev_sessions_30d",story.get("prev_window_sessions",0)))]:
            for i in range(n):
                q = phrases[i%len(phrases)]
                if story.get("clicked_target_products") and "антивирус" in q and i%4==0:
                    q=rng.choice(["защитить десять касс от вирусов","антивирь в бухгалтерию на десяток машин"])
                seq = [(q,None,story["type"])]
                if story.get("reformulate_to") and rng.random()<story["reformulate_share"]:
                    seq.append((choose(story["reformulate_to"]),None,"reformulate"))
                desired=story.get("clicked_target_products") or ([story["preferred_analog_pin"]] if "preferred_analog_pin" in story else [])
                if desired:
                    label=choose(desired)
                    choices=[c for c in cards if normalize(label) in normalize(c.title)]
                    if choices:
                        # Уточнение к базовой линейке, без случайного отраслевого модуля с тем же префиксом.
                        family=min(choices,key=lambda c:len(c.kb.get("title") or c.offers[0].family_name or c.title)).family
                        dest=choose([c for c in choices if c.family==family])
                        seq[0]=(q,dest.family,story["type"])
                        if rng.random()<.65:
                            seq.append((dest.title,dest.family,"product"))
                seeded.append((visit(story.get("client_id"),window,story.get("segments")),seq,story["id"]))

    # Разговорное название из обращений в поддержку. Уточнение покупателя
    # всегда ведёт к существующему семейству в текущем каталоге.
    backup=next((c for c in cards if c.family=="cyber_backup"),next((c for c in cards if c.category=="backup_recovery"),None))
    if backup:
        for i in range(80):
            shorthand=["резервилка","лицензия резервилка","корпоративная резервилка"][i%3]
            seq=[(shorthand,backup.family,"product"),(backup.kb.get("title") or backup.title,backup.family,"product")]
            seeded.append((visit(window=(-29,0)),seq,None))

    # Повторяемые фразы, точные артикулы и длинные запросы с параметрами.
    pool = []
    # Основной интернет-спрос приходится на доступные коммерческие лицензии.
    commercial=[c for c in cards if any(o.available and o.price and o.lic.action=="new" and
                o.lic.audience=="business" and o.lic.term_months in (12,None) for o in c.offers)]
    popular=sorted(commercial,key=lambda c:-sum(o.sales_90d for o in c.offers))[:80]
    head=[]

    for card in cards:
        o = choose(card.offers)
        name = card.kb.get("title") or card.title
        aliases=card.kb.get("aliases") or [name]
        variants=[name,card.title,choose(aliases),o.sku or name]
        # Отдельный вендор имеет смысл при выборе из его линейки.
        variants.append(o.vendor or name)
        if any(x.lic.action=="new" and x.lic.term_months==12 for x in card.offers):
            variants.append(f"{name} на год")
        if any(x.lic.action=="renewal" and x.available for x in card.offers):
            variants.append(f"{name} продление")
        quantity=choose([15,30,100])
        if any(x.lic.metric=="device" and (x.lic.qty_min or 1)<=quantity<=(x.lic.qty_max or quantity)
               and x.available and x.lic.action=="new" for x in card.offers):
            variants.append(f"{name} на {quantity} пк")
        variants.append(f"купить {choose(aliases)}")
        for q in variants:
            entry=(q,card.family,"product")
            pool.append(entry)
            if card in popular:
                head.append(entry)
        if card in popular:
            for alias in card.kb.get("aliases",[])[:4]:
                head.append((alias,card.family,"product"))
    tail = []
    departed = [f["name"] for f in engine.kb.rows["families"].values()
                if engine.kb.rows["vendors"].get(f.get("vendor"),{}).get("market_status")=="left"]
    for _ in range(4800):
        card = choose(cards)
        o = choose(card.offers)
        template = choose(spec["query_templates"])
        name = card.kb.get("title") or card.title
        slots = dict(product=name,qty=choose([5,10,15,25,30,50,75,100,250]),vendor=o.vendor,edition=o.edition or "",
                     category_name=engine.names["category"].get(card.category,card.category),sku=o.sku or name,
                     term=choose(["на год","на 2 года"]),metric_user="пользователей",metric_dev="пк",
                     role_genitive=choose(["бухгалтера","инженера","дизайнера"]),industry_genitive=choose(["банка","клиники","завода"]),
                     departed=choose(departed or [name]),os_ru=choose(["астру","ред ос"]),cert=choose(["фстэк","из реестра"]),
                     vendor_alt=choose(cards).offers[0].vendor)
        for index in range(1,5):
            slots[f"product_{index}"]=name if index==1 else choose(cards).title
            slots[f"qty_{index}"]=rng.randint(1,30)
        q=choose(template["patterns"]).format(**slots)
        tail.append((q,card.family if template["intent"] not in {"industry","role_kit","analog"} else None,template["intent"]))
    n = spec["meta"]["target_searches"]
    remaining = n-sum(len(seq) for _,seq,_ in seeded)
    sessions = spec["meta"]["target_sessions"]-len(seeded)
    lengths = [1]*sessions
    extra = remaining-sessions
    for pos in rng.sample(range(sessions*3),extra):
        lengths[pos//3]+=1
    distortions={}
    noise_shares={k:spec["noise_and_gaps_breakdown"][k] for k in NOISE_QUERIES}
    family_card={c.family:c for c in reversed(cards)}
    background_random=random.Random(seed+17)
    for length in lengths:
        initial = choose(tail if rng.random()<.16 else (head if head and rng.random()<.83 else pool))
        visit_data=visit()
        reporting=weights["reporting_period"]
        day=datetime.fromtimestamp(visit_data[0],MSK).day
        if day in reporting["days_of_month"] and initial[1]:
            category=engine.kb.rows["families"].get(initial[1],{}).get("category")
            factor=reporting["category_multipliers"].get(category,1)
            if factor==1 and rng.random()<.045:
                candidates=[entry for entry in pool if engine.kb.rows["families"].get(entry[1],{}).get("category") in reporting["category_multipliers"]]
                initial=choose(candidates) if candidates else initial
        q,target,intent=initial
        if background_random.random()<sum(noise_shares.values()):
            noise=background_random.choices(list(noise_shares),list(noise_shares.values()))[0]
            initial=(background_random.choice(NOISE_QUERIES[noise]),None,"off_topic")
        else:
            weights_dist=spec["distortions"]
            kind=background_random.choices(list(weights_dist),list(weights_dist.values()))[0]
            raw=distort(q,kind if background_random.random()<.6 else "clean",family_card.get(target),background_random)
            if q!=raw:
                distortions[raw]=kind
            initial=(raw,target,intent)
        seq=[initial]
        for _ in range(length-1):
            if not initial[1]:
                seq.append(choose(pool))
                continue
            card = engine.catalog.cards[sorted(engine.catalog.by["family"][initial[1]])[0]]
            if len(seq)==1 and lookup(initial[0])[1] and rng.random()<.08:
                seq.append((f"а на {choose([15,30,50])} мест?",card.family,"refinement"))
            else:
                seq.append((card.kb.get("title") or card.title,card.family,"product") if len(seq)==1 else choose(pool))
        seeded.append((visit_data,seq,None))

    commercial_families={c.family for c in commercial}
    truth = []
    with journal.transaction() as db:
        db.execute("INSERT OR REPLACE INTO kv VALUES ('settings:history_source','mock',?)",(time(),))
        db.execute("INSERT OR REPLACE INTO kv VALUES ('settings:active_replay','',?)",(end,))
        db.execute("DELETE FROM events WHERE search_id IN (SELECT search_id FROM searches WHERE search_id GLOB 's_mock_*')")
        db.execute("DELETE FROM searches WHERE search_id GLOB 's_mock_*'")
        for idx,((start,c),seq,story) in enumerate(seeded):
            sid = f"mock_{idx:06}"
            for k,(q,target,label) in enumerate(seq):
                ident = f"s_{sid}_{k}"
                ts = start+k*110
                hits,count,ids,(intent,reason,cat,family,filters,entities) = lookup(q)
                target = target or family
                # Обычная онлайн-закупка — новая коммерческая лицензия на год или бессрочно.
                # Для артикула, спецсценария и явной операции сохраняем исходную цель.
                retail=bool(target and label=="product" and intent in ("product","vendor","category") and not story and
                            target in commercial_families)
                def suitable(o):
                    return o.family_id==target and (not retail or (o.available and not o.price_on_request and o.price and o.lic.action=="new" and
                           o.lic.audience=="business" and o.lic.term_months in (12,None)))
                rank = next((p for p,o in enumerate(hits,1) if suitable(o)),None)
                truth.append(dump(dict(search_id=ident,q=q,story=story,distortion=distortions.get(q,"clean"),retail=retail,legacy_offers=[o.offer_id for o in hits[:5]],target_family=target,target_category=cat,intent=label if label in spec["intent_shares"] else intent)))
                journal.insert("searches",dict(search_id=ident,session_id=sid,ts=ts,client_id=c.client_id,
                    prev_search_id=f"s_{sid}_{k-1}" if label=="refinement" else None,
                    segment=c.segment if c.client_id!="guest" else "guest",source="history",engine="legacy",mode="naive",
                    q_raw=q,q_norm=normalize(q),q_corrected=normalize(q),intent=intent,category_ctx=cat,entities_json=entities,
                    filters_json=filters,n_cards=count,zero=int(not count),relaxed=0,fail_reason=reason,
                    top_cards_json=ids,blocks_json='["products"]' if count else '[]',llm_calls=0,llm_cost_usd=0,cached=0))
                seqno=0
                def event(kind,**fields):
                    nonlocal seqno
                    seqno+=1
                    journal.event(ts+seqno*4,dict(event_id=f"{ident}_{seqno}",type=kind,session_id=sid,
                                  search_id=ident,client_id=c.client_id,**fields))
                if count:
                    event("impression",payload={"cards":[o.offer_id for o in hits[:5]]})
                case = "when_hit_top5" if rank and rank<=5 else "when_hit_below5" if rank else "when_irrelevant"
                model = funnel[case]
                if count and rng.random()<model["click_prob"]:
                    positions=[i for i,o in enumerate(hits[:5],1) if suitable(o)]
                    pos = (rng.choices(positions,[funnel["when_hit_top5"]["click_pos_weights"][i-1] for i in positions])[0]
                           if positions else rank or rng.randint(1,min(len(hits),10)))
                    o = hits[pos-1]
                    fields=dict(card_id=o.card_id,offer_id=o.offer_id,position=pos)
                    event("click",**fields,payload={"price_on_request":o.price_on_request})
                    segment = c.segment if c.client_id!="guest" else "guest"
                    if o.price_on_request:
                        if rng.random()<funnel["when_hit_top5"]["lead_given_click_price_on_request"]:
                            event("lead",**fields)
                    elif o.price and o.available and rng.random()<(model["cart_given_click"][segment] if rank and rank<=5 else model["cart_given_click"]):
                        units=re.search(r"(\d+)\s*(?:пк|мест|устройств|пользовател|арм)",q.lower())
                        seats=int(units[1]) if units else min(c.size_seats or 1,rng.choice([15,25,50,100])) if c.client_id!="guest" else rng.choice([5,10,15,25])
                        if o.lic.metric not in {"device","user","mailbox","concurrent"}:
                            seats=1
                        qty=max(1,(seats+(o.lic.pack or 1)-1)//(o.lic.pack or 1))
                        if not o.lic.pack and not (o.lic.qty_min or 1)<=seats<=(o.lic.qty_max or seats):
                            variants=[v for v in engine.catalog.cards[o.card_id].offers
                                      if v.available and v.price and not v.price_on_request and
                                      (v.lic.metric,v.lic.action,v.lic.audience,v.lic.term_months)==
                                      (o.lic.metric,o.lic.action,o.lic.audience,o.lic.term_months) and
                                      (v.lic.qty_min or 1)<=seats<=(v.lic.qty_max or seats)]
                            if not variants:
                                event("lead",**fields)
                                continue
                            o=min(variants,key=lambda v:v.price*((seats+(v.lic.pack or 1)-1)//(v.lic.pack or 1)))
                            qty=(seats+(o.lic.pack or 1)-1)//(o.lic.pack or 1)
                            fields["offer_id"]=o.offer_id
                        if qty*o.price>2500000:
                            event("lead",**fields)
                            continue
                        event("cart",qty=qty,**fields)
                        if rng.random()<funnel["when_hit_top5"]["order_given_cart"][segment]:
                            event("order",qty=qty,value=round(o.price*qty,2),margin_value=round(o.price*qty*o.margin,2),**fields)
                elif k+1<len(seq):
                    if seq[k+1][0]!=q and seq[k+1][2]!="refinement":
                        event("reformulate",payload={"to":seq[k+1][0]})
                else:
                    event("exit")
    path=Path(journal.path).parent/"mock_truth.jsonl"
    path.write_text("\n".join(truth)+"\n")
    return dict(author="AiXenix",searches=len(truth),sessions=len(seeded),today=str(anchor),seed=seed)
