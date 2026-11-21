from collections import Counter, defaultdict
import json
import re
from .kpi import facts,loss_by_search

GAPS={"not_in_catalog_known","not_in_catalog_unknown"}


def demand(engine,rows,loss,end=None):
    if end is None:
        end=max((r["ts"] for r in rows),default=0)
    groups=defaultdict(list)
    from functools import lru_cache
    from kuznitsa.understand.repair import repair
    @lru_cache(None)
    def corrected(term):
        return bool(repair(term,engine.lex)[1])
    from kuznitsa.text import tokens,lemma,morphology
    catalog_words={w for c in engine.catalog.cards.values() for name in
                   (c.title,c.offers[0].vendor,*c.kb.get("aliases",[])) if name for w in tokens(name)}
    catalog_words.update(w for title in engine.names["category"].values() for w in tokens(title))
    stop=set("купить покупка оплата цена лицензия лицензирование продление коммерческий корпоративный организация компания команда юрлицо версия поставка сервер программа запрос работать поддержка enterprise commercial license licenses server pro linux windows astra fresh premises premise onprem onpremise on site self hosted business edition version pricing team software bazovyi".split())
    stop.update(lemma(w) for w in list(stop))
    @lru_cache(None)
    def brand_term(query):
        fixed,changes=repair(query,engine.lex)
        repaired={part for change in changes for part in tokens(change["to"])}
        for w in fixed:
            term=lemma(w)
            if re.fullmatch(r"[a-z][a-z0-9+.-]{2,}",term) and w not in repaired and term not in stop and w not in catalog_words:
                return term
        for w in fixed:
            if (re.fullmatch("[а-яё]{4,}",w) and w not in repaired and w not in catalog_words and
                    w not in engine.lex.words and not morphology().word_is_known(w)):
                return w
        return None
    @lru_cache(None)
    def resolved_family(query):
        words,_=repair(query,engine.lex)
        families=[ident for _,_,matches in engine.lex.match(words) for kind,ident,_ in matches if kind=="family"]
        return next((f for f in families if f in engine.catalog.by["family"]),next(iter(families),None))
    commercial={"купить","закупка","лицензия","продление","оплата","стоимость","commercial","license","лицензирование"}
    following=defaultdict(Counter)
    for entry in engine.journal.rows("""SELECT s.q_raw q,json_extract(e.payload_json,'$.to') target,count(*) n
           FROM events e JOIN active_history s USING(search_id) WHERE e.type='reformulate' AND s.ts>?
           GROUP BY 1,2""",(end-30*86400,)):
        if entry["target"]:
            following[entry["q"]][entry["target"]]+=entry["n"]
    impressions=Counter()
    for group in engine.journal.rows("""SELECT e.payload_json body,count(*) n FROM events e JOIN active_history s USING(search_id)
            WHERE e.type='impression' AND s.ts>? GROUP BY e.payload_json""",(end-30*86400,)):
        shown=json.loads(group["body"] or "{}").get("cards",[])
        card_ids={engine.catalog.offers_by_id[v].card_id if v in engine.catalog.offers_by_id else v
                  for v in shown if isinstance(v,str)}
        for card_id in card_ids:
            impressions[card_id]+=group["n"]
    for r in rows:
        if r["reason"]=="unknown_term" and r["zero"]:
            term=brand_term(r.get("normalized_query") or r["q"])
            if term:
                groups[(False,term)].append((r,None,None))
            continue
        if r["reason"] not in GAPS|{"vendor_left"}:
            continue
        f=json.loads(r["filters_json"] or "{}")
        family=resolved_family(r.get("normalized_query") or r["q"]) or next(iter(f.get("family",[])),None)
        if family in engine.catalog.by["family"] and r["reason"] in GAPS:
            continue
        vendor=engine.kb.rows["families"].get(family,{}).get("vendor") or next(iter(f.get("vendor",[])),None)
        left=r["reason"]=="vendor_left" or engine.kb.rows["vendors"].get(vendor,{}).get("market_status")=="left"
        if left:
            key=vendor or family or r["q"]
        else:
            key=family or vendor or brand_term(r.get("normalized_query") or r["q"])
            if not key:
                continue
        groups[(left,key)].append((r,vendor,family))
    gaps=[]
    departed=[]
    for (left,key),entries in groups.items():
        recent=[r for r,_,_ in entries if r["ts"]>end-30*86400]
        if not recent:
            continue
        prev=sum(end-60*86400<r["ts"]<=end-30*86400 for r,_,_ in entries)
        vendor,family=entries[0][1:]
        known=key in engine.kb.rows["families"] or key in engine.kb.rows["vendors"]
        if not left and (key in engine.catalog.by["family"] or key in engine.catalog.by["vendor"] or (not known and
                (key in catalog_words or len({r["q"] for r in recent})<2 or len({r["session_id"] for r in recent})<8 or corrected(key)))):
            continue
        if not known and not left:
            # Устойчивое уточнение до одного имеющегося семейства указывает на пробел словаря.
            destinations=sum((following[q] for q in {r["q"] for r in recent}),Counter())
            families=Counter()
            for phrase,n in destinations.items():
                family_id=resolved_family(phrase)
                if family_id in engine.catalog.by["family"]:
                    families[family_id]+=n
            if families and max(families.values())>=max(4,.6*sum(destinations.values())):
                continue
            # Обрывок сломанной раскладки или транслита сам по себе не доказывает спрос.
            # Ищем независимое подтверждение: исходное название рядом с признаком покупки.
            confirmed=any(key in tokens(r["q"]) and any(lemma(w) in commercial for w in tokens(r["q"])) for r in recent)
            if not confirmed:
                continue
        proper=engine.names["family"].get(key) or engine.names["vendor"].get(key)
        display=proper or next((w for r in recent for w in r["q"].split() if w.lower()==key and w!=key),key.capitalize())
        item=dict(key=key,title=display if proper or left else f"Лицензии {display}",vendor=vendor,family=family,
                  category=Counter(r["category"] for r in recent).most_common(1)[0][0],searches=len(recent),
                  sessions=len({r["session_id"] for r in recent}),previous=prev,change=len(recent)-prev,
                  segments=dict(Counter(r["segment"] for r in recent)),queries=[q for q,_ in Counter(r["q"] for r in recent).most_common(5)],
                  expected_rub=round(sum(loss.get(r["search_id"],(0,0))[0] for r in recent)))
        item["examples"]=[dict(q=q,normalized=" ".join(lemma(w) for w in repair(q,engine.lex)[0] if lemma(w) not in stop),search_id=next(r["search_id"] for r in recent if r["q"]==q)) for q in item["queries"]]
        item["search_id"]=item["examples"][0]["search_id"]
        item["search_ids"]={ex["q"]:ex["search_id"] for ex in item["examples"]}
        item["alternatives"]=dict(sum((following[q] for q in {r["q"] for r in recent}),Counter()).most_common(3))
        item["alternatives_note"]="Следующие фразы, зарегистрированные событием переформулировки."
        item["conservative_rub"]=round(sum(loss.get(r["search_id"],(0,0))[1] for r in recent))
        item["formula"]="Сумма потерь уникальных сессий этого кластера по формуле KPI"
        (departed if left else gaps).append(item)
    defects=[]
    for c in engine.catalog.cards.values():
        fields=[]
        expected=set(c.kb.get("compat_ru_os",[])) & {"astra","redos"}
        if expected and not any(expected.intersection(o.platforms) for o in c.offers):
            fields.append("platforms")
        if c.kb.get("registry") is True and c.kb.get("confidence")!="low" and all(o.registry is None for o in c.offers):
            fields.append("registry")
        bands=c.kb.get("license",{}).get("bands",[])
        required={int(m[0]) for band in bands if (m:=re.findall(r"\d+",str(band)))}
        observed={o.lic.qty_min for o in c.offers}
        if required.intersection({25,50})-observed:
            fields.append("qty_range")
        if c.kb.get("summary") and not any(o.description for o in c.offers):
            fields.append("description")
        if not any(o.price or o.price_on_request for o in c.offers):
            fields.append("price")
        if fields:
            defects.append(dict(card_id=c.id,title=c.title,category=c.category,fields=fields,impressions=impressions[c.id]))
    sort=lambda items:sorted(items,key=lambda x:-x["searches"])
    breakdown={}
    for dimension in ("family","vendor","category"):
        grouped=defaultdict(list)
        for item in gaps:
            grouped[item[dimension] or "unknown"].append(item)
        breakdown[dimension]=sort([dict(key=key,searches=sum(i["searches"] for i in items),
            previous=sum(i["previous"] for i in items),expected_rub=sum(i["expected_rub"] for i in items),
            clusters=[i["key"] for i in items]) for key,items in grouped.items()])
    return dict(items=sort(gaps),breakdown=breakdown,departed=sort(departed),card_defects=sorted(defects,key=lambda x:-x["impressions"]),
                period_days=30,through=end)


def report(engine):
    from .cache import cached
    return cached(engine.journal,"gaps:b2.4",lambda:_report(engine))


def _report(engine):
    j=engine.journal
    packed=bool(j.rows("SELECT 1 FROM analytics_reports WHERE key='packed'"))
    if packed:
        end=j.rows("SELECT max(ts) end FROM analytics_detail")[0]["end"]
        losses={r["id"]:(r["base"],r["low"]) for r in j.rows("SELECT search_id id,base,low FROM analytics_fact WHERE base>0")}
        with j.lock:
            rows=(dict(r) for r in j.db.execute("""SELECT * FROM analytics_detail WHERE ts>? AND reason IN
                ('unknown_term','not_in_catalog_known','not_in_catalog_unknown','vendor_left')""",(end-60*86400,)))
            result=demand(engine,rows,losses,end)
        groups=j.rows("""SELECT q,count(*) n,min(ts) start,max(ts) end FROM analytics_detail
                        WHERE reason='vendor_left' GROUP BY q""")
        found=j.rows("""SELECT avg(clicks>0) clicks,avg(carts) carts,avg(orders) orders FROM analytics_detail WHERE NOT zero""")[0]
    else:
        rows=facts(j)
        result=demand(engine,rows,loss_by_search(rows)[0])
        departed=defaultdict(list)
        for r in rows:
            if r["reason"]=="vendor_left":
                departed[r["q"]].append(r["ts"])
        groups=[dict(q=q,n=len(times),start=min(times),end=max(times)) for q,times in departed.items()]
        available=[r for r in rows if not r["zero"]]
        found={k:sum(bool(r[k]) for r in available)/(len(available) or 1) for k in ("clicks","carts","orders")}
    latest=engine.journal.rows("SELECT id FROM active_replay")
    seen={}
    if latest:
        seen={r["q"]:json.loads(r["result"]) for r in engine.journal.rows("SELECT q,result FROM replay_results WHERE run_id=?",(latest[0]["id"],))}
    bridge=[r for r in groups if r["q"] in seen]
    shown=sum(r["n"] for r in bridge if seen[r["q"]].get("analogs"))
    result["bridge"]=dict(searched=sum(r["n"] for r in bridge),impressions=shown,run_id=latest[0]["id"] if latest else None,
        start=min((r["start"] for r in bridge),default=None),end=max((r["end"] for r in bridge),default=None),
        **{k:round(shown*(rate or 0)) for k,rate in found.items()},
        note="Показы блоков аналогов измерены в парном прогоне. Клики, корзины и заказы — прогноз по частотам непустой исторической выдачи.")
    return result
