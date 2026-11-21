"""Предложения строятся по наблюдаемым фразам, действиям и карточкам."""
from copy import copy
from functools import lru_cache
from math import ceil
from kuznitsa.controls import PhraseRules
from collections import Counter,defaultdict
import hashlib
import json
import re
from time import time
from kuznitsa.config import WEIGHTS
from kuznitsa.schema import Request
from kuznitsa.text import tokens
from .gaps import demand
from .kpi import facts,loss_by_search
from .replay import compare,products,experiment_engine
from .store import dump

ROLES=dict(add_synonym="content_manager",add_product="content_manager",fix_card="content_manager",merch_rule="ecom_manager",
           rising_demand="product_manager",hot_lead="ecom_manager",renewal_campaign="ecom_manager",weights_advice="head_ecom")


def preview(e,weights,phrases):
    items=[]
    for q in dict.fromkeys(phrases):
        def sample(w):
            r=e.search(Request(q=q,source="eval",mode="fast",weights=w,page_size=10))
            out=[]
            for c in products(r):
                o=e.catalog.offers_by_id.get(c.get("offer",{}).get("offer_id"))
                out.append(dict(card_id=c["card_id"],title=c["title"],tier=c["score"]["tier"],
                           margin_rub=round((o.price or 0)*o.margin,2) if o else 0))
            return out
        before,after=sample(None),sample(weights)
        items.append(dict(q=q,before=before,after=after,
            moved=sum(x["card_id"]!=y["card_id"] for x,y in zip(before,after))+abs(len(before)-len(after)),
            band_inversions=sum(x["tier"]>y["tier"] for i,x in enumerate(after) for y in after[i+1:]),
            margin_top5_before_rub=round(sum(x["margin_rub"] for x in before[:5]),2),
            margin_top5_after_rub=round(sum(x["margin_rub"] for x in after[:5]),2),
            margin_delta_rub=sum(x["margin_rub"]/(i+1) for i,x in enumerate(after[:5]))-
                             sum(x["margin_rub"]/(i+1) for i,x in enumerate(before[:5]))))
    return dict(margin_delta_rub=round(sum(x["margin_delta_rub"] for x in items),2),items=items,moved=sum(x["moved"] for x in items),band_inversions=sum(x["band_inversions"] for x in items),
                formula="Сумма удельной маржи первых пяти позиций с весом 1 / позиция")


def discover(e):
    j=e.journal
    rows=[r for r in facts(j) if r["source"] in ("ui","history")]
    end=max((r["ts"] for r in rows),default=e.clock())
    recent=[r for r in rows if r["ts"]>end-30*86400]
    losses,_=loss_by_search(rows)
    source=j.rows("SELECT value FROM kv WHERE key='settings:history_source'")
    imported=bool(source and source[0]["value"]=="import")
    suggestions={}
    merchandising=set()
    @lru_cache(None)
    def probe(q):
        return e.search(Request(q=q,source="eval",mode="fast",page_size=10))

    def add(kind,key,title,g,action,extra=None,impact=None):
        if not g and kind!="renewal_campaign":
            return
        samples=Counter(r["q"] for r in g)
        probes={}
        for q,_ in samples.most_common(5):
            response=probe(q)
            probes[q]=dict(search_id=response["search_id"],top5=[c["card_id"] for c in products(response)[:5]],
                           repaired=bool(response["query"].get("corrections")))
        if kind=="add_synonym":
            payload=action["payload_json"]
            targets={c["card_id"] for c in products(probe(payload["to"]))[:1]}
            trial=experiment_engine(e)
            trial._rules()
            trial._phrases=PhraseRules([r for r in trial.controls.synonyms() if r["kind"]=="text"]+[dict(payload,rule_id="preview")])
            kept=[]
            for q,result in probes.items():
                if targets.intersection(result["top5"]):
                    continue
                after=compare(trial,q)
                if targets.intersection(c["card_id"] for c in after["cards"][:5]):
                    kept.append(q)
            if not kept:
                return
            probes={q:probes[q] for q in kept}
            g=[r for r in g if r["q"] in kept]
            samples=Counter(r["q"] for r in g)
        if kind in ("fix_card","rising_demand"):
            targets=set(action["payload_json"].get("card_ids",[])) or e.catalog.by["category"].get(action["payload_json"].get("category"),set())
            unresolved=[q for q,v in probes.items() if not targets.intersection(v["top5"])]
            if not unresolved:
                return
            extra=dict(extra or {},unresolved_queries=unresolved)
        if kind=="add_product":
            if key in e.catalog.by["family"] or key in e.catalog.by["vendor"]:
                return
            known=key in e.kb.rows["families"] or key in e.kb.rows["vendors"]
            if not known and (len(samples)<2 or probe(str(key))["query"].get("corrections") or any(v["repaired"] for v in probes.values())):
                return
            if not any(not v["top5"] or any(b["type"]=="not_in_catalog" for b in probe(q)["blocks"]) for q,v in probes.items()):
                return
        if kind=="merch_rule":
            q=action["conditions"]["phrase"]
            target=action["payload_json"].get("card_id") or (extra or {}).get("target_card")
            if q in merchandising or target in probes[q]["top5"]:
                return
            # Пробное правило работает только на изолированной копии управления.
            trial=experiment_engine(e)
            trial.controls=copy(e.controls)
            trial.controls.active=lambda:[*e.controls.active(),dict(id="preview",enabled=True,
                kind=action["kind"],conditions=action["conditions"],action=action["payload_json"])]
            trial._rules_key=(trial.controls,trial.controls.version())
            result=compare(trial,q)
            if target not in [c["card_id"] for c in result["cards"][:5]]:
                return
            probes[q]["trial_search_id"]=result["search_id"]
            merchandising.add(q)
        if kind=="hot_lead" and all(v["top5"] for v in probes.values()):
            return
        sessions={r["session_id"] for r in g}
        ident=kind+"-"+hashlib.sha256((("import:" if imported else "")+str(key)).encode()).hexdigest()[:12]
        evidence=dict(searches_30d=len(g),sessions_30d=len(sessions),sample_queries=[q for q,_ in samples.most_common(8)],
                      checks=probes,search_ids={q:next(r["search_id"] for r in g if r["q"]==q) for q,_ in samples.most_common(8)},sample_sessions=sorted(sessions)[:6],segments=dict(Counter(r["segment"] for r in g)),
                      metric_before=dict(zero=sum(r["zero"] for r in g),orders=sum(r["orders"] for r in g)),
                      **(extra or {}))
        evidence["examples"]=[dict(q=q,search_id=sid) for q,sid in evidence["search_ids"].items()]
        sums=[round(sum(losses.get(r["search_id"],(0,0))[i] for r in g)) for i in range(2)]
        suggestions[ident]=dict(id=ident,dataset="import" if imported else "mock",type=kind,role=ROLES[kind],title=title,status="new",
            summary=f"За последние {'72 часа' if kind=='hot_lead' else '30 дней'} — {len(g)} поисков в {len(sessions)} сессиях.",
            confidence=round(len(sessions)/(len(sessions)+20),2),priority="high" if len(sessions)>=50 else "medium",
            evidence=evidence,action=action,impact=impact or dict(expected_rub=sums[0],conservative_rub=sums[1],
                metric_label="Оценка потенциала",formula_note="Сумма оценок неудачных сессий из KPI, отнесённых к этим запросам. Предложения могут пересекаться."))

    by_q=defaultdict(list)
    by_cat=defaultdict(list)
    by_client=defaultdict(list)
    for r in recent:
        by_q[r["q"]].append(r)
        by_cat[r["category"]].append(r)
        by_client[r["client_id"]].append(r)
    # Повторяющийся неизвестный оборот и направление следующего запроса.
    pairs=defaultdict(Counter)
    for r in j.rows("""SELECT s.q_raw q,json_extract(e.payload_json,'$.to') target,count(*) n
       FROM events e JOIN active_history s USING(search_id) WHERE e.type='reformulate' AND s.zero=1 AND s.ts>?
       AND s.source IN ('ui','history') GROUP BY 1,2""",(end-30*86400,)):
        if r["target"] and r["target"].lower()!=r["q"].lower():
            pairs[r["q"]][r["target"]]+=r["n"]
    words=defaultdict(list)
    for q in pairs:
        for word in set(tokens(q)):
            if len(word)>=3 and word.isalpha() and word not in {"для","под","при","или","год","цена","купить","как","лет","чем","поиск"}:
                words[word].append(q)
    for word,qs in words.items():
        if any(kind=="vendor" for _,_,matches in e.lex.match([word]) for kind,_,_ in matches):
            continue
        if word not in [q.lower() for q in qs]:
            continue
        dest=sum((pairs[q] for q in qs),Counter())
        ranked=[(target,n) for target,n in dest.most_common() if word not in tokens(target)]
        if not ranked or ranked[0][1]<4:
            continue
        target,n=ranked[0]
        if n/sum(dest.values())<.26:
            continue
        # Предпочитаем переход, после которого наблюдалась непустая выдача.
        target=next((t for t,m in ranked if m>=n/2 and any(not r["zero"] for r in by_q[t])),target)
        add("add_synonym",word,f"Связать «{word}» с запросом «{target}»",[r for q in qs for r in by_q[q]],
            dict(kind="synonym",label="Добавить синоним",conditions={},payload_json=dict(kind="text",phrase=word,to=target)),dict(reformulated_to=dict(ranked[:5])))
    gaps=demand(e,rows,losses)
    for item in gaps["items"]:
        if item["sessions"]>=8:
            add("add_product",item["key"],f"Проверить поставку · {item['title']}",[r for q in item["queries"] for r in by_q[q]],
                dict(kind="ticket",label="Завести товар",payload_json=dict(product=item["key"],category=item["category"])),dict(alternatives=item["alternatives"],demand=item["searches"],segments_30d=item["segments"]))
    # Незнакомые коммерческие названия, даже если распознаны вторичные условия покупки.
    brands=defaultdict(list)
    for r in recent:
        if r["zero"] and r["reason"]=="vocabulary_gap":
            for w in set(re.findall(r"\b[a-z]{4,}\b",r["q"].lower()))-e.lex.words:
                brands[w].append(r)
    for w,g in brands.items():
        if len({r["q"] for r in g})>=2 and len(g)>=12:
            add("add_product",w,f"Уточнить доступность продукта «{w}»",g,dict(kind="ticket",label="Проверить поставку",payload_json=dict(product=w)))
    for cat,g in by_cat.items():
        if not cat:
            continue
        cards=[x for x in gaps["card_defects"] if x["category"]==cat]
        for field,pattern,label in [("platforms","астр|linux|ред ос","совместимость с ОС"),("registry","реестр|ндс|44 фз","данные о реестре"),
                                    ("qty_range",r"\d+ (пк|комп|устройств)","диапазоны лицензирования")]:
            affected=[r for r in g if r["zero"] and re.search(pattern,r["q"].lower())]
            defects=[c for c in cards if field in c["fields"]]
            if field=="qty_range" and affected:
                sizes={int(n) for r in affected for n in re.findall(r"(\d+) (?:пк|комп|устройств)",r["q"].lower())}
                defects=[c for c in defects if any(not any((o.lic.qty_min or 1)<=n<=(o.lic.qty_max or float("inf"))
                         for o in e.catalog.cards[c["card_id"]].offers if o.lic.qty_min or o.lic.qty_max) for n in sizes)]
            if len(affected)>=5 and defects:
                add("fix_card",(cat,field),f"Дополнить {label} в категории «{e.names['category'].get(cat,cat)}»",affected,
                    dict(kind="ticket",label="Поставить задачу контент-менеджеру",payload_json=dict(field=field,card_ids=[c["card_id"] for c in defects])),
                    dict(impressions=sum(c["impressions"] for c in defects)))
    for r in j.rows("""SELECT s.q_raw q,e.card_id,count(*) n,avg(e.position) pos FROM events e JOIN active_history s USING(search_id)
        WHERE e.type='click' AND s.ts>? AND e.position>4 AND s.source IN ('ui','history') GROUP BY 1,2 HAVING count(*)>=2""",(end-30*86400,)):
        if any(r["card_id"] in json.loads(hit["top_cards_json"] or "[]")[:3] for hit in by_q[r["q"]]):
            continue
        if r["card_id"] in e.catalog.cards:
            add("merch_rule",(r["q"],r["card_id"]),f"Поднять «{e.catalog.cards[r['card_id']].title}» по запросу «{r['q']}»",by_q[r["q"]],
                dict(kind="boost",label="Поднять внутри уровня",conditions=dict(phrase=r["q"]),payload_json=dict(card_id=r["card_id"],factor=1.3)),dict(late_clicks=r["n"],mean_position=r["pos"]))
    # После неудачи посетитель уточнил название и кликнул товар в следующей выдаче.
    # Ставим правило только для фразы, где нужной карточки всё ещё нет в первой пятёрке.
    transitions=j.rows("""SELECT s.q_raw q,clicked.card_id,count(distinct s.session_id) sessions
        FROM active_history s JOIN events reform ON reform.search_id=s.search_id AND reform.type='reformulate'
        JOIN active_history nxt ON nxt.session_id=s.session_id AND nxt.q_raw=json_extract(reform.payload_json,'$.to')
            AND nxt.ts>s.ts AND nxt.ts<=s.ts+180
        JOIN events clicked ON clicked.search_id=nxt.search_id AND clicked.type='click'
        WHERE s.ts>? GROUP BY 1,2 HAVING sessions>=4 ORDER BY sessions DESC,q,clicked.card_id""",(end-30*86400,))
    synonym_phrases={q for suggestion in suggestions.values() if suggestion["type"]=="add_synonym"
                     for q in suggestion["evidence"]["sample_queries"]}
    for t in transitions:
        q=t["q"]
        card=e.catalog.cards.get(t["card_id"])
        if not card or q in synonym_phrases or len(tokens(q))<2:
            continue
        current_ids=[c["card_id"] for c in products(probe(q))]
        if card.id in current_ids[:5] or card.id not in [c["card_id"] for c in products(probe(card.title))[:5]]:
            continue
        if t["sessions"]<.10*len({r["session_id"] for r in by_q[q]}):
            continue
        add("merch_rule",(q,card.id),f"Показывать «{card.title}» по запросу «{q}»",by_q[q],
            dict(kind="redirect",label="Перенаправить точную фразу",conditions=dict(phrase=q),payload_json=dict(q=card.title)),
            dict(target_card=card.id,followup_click_sessions=t["sessions"]))
    previous=Counter(r["category"] for r in rows if end-60*86400<r["ts"]<=end-30*86400)
    for cat,g in by_cat.items():
        old=previous[cat]
        if cat and len(g)>=20 and old>=5 and len(g)>=1.5*old:
            add("rising_demand",cat,f"Развить подборку «{e.names['category'].get(cat,cat)}»",g,
                dict(kind="digest",label="Включить в план ассортимента",payload_json=dict(category=cat)),
                dict(previous_searches=old,growth_pct=round(100*(len(g)/old-1),1)))
    # В большой категории общий фон может скрыть растущую задачу покупки.
    # Сравниваем равные окна отдельно по распознанному сценарию.
    previous_scenarios=Counter((r["category"],r["intent"]) for r in rows if end-60*86400<r["ts"]<=end-30*86400)
    for cat,group in by_cat.items():
        if not cat or len(group)>=1.5*max(1,previous[cat]):
            continue
        scenarios=defaultdict(list)
        for r in group:
            scenarios[r["intent"]].append(r)
        for intent,g in scenarios.items():
            old=previous_scenarios[(cat,intent)]
            if old<10 or len(g)<30 or len(g)<1.5*old or len(g)-old<3*(len(g)+old)**.5:
                continue
            from kuznitsa.understand.intent import TITLES
            add("rising_demand",(cat,intent),f"Разобрать растущий спрос · {e.names['category'].get(cat,cat)} · {TITLES.get(intent,intent)}",g,
                dict(kind="digest",label="Проверить подборку по сценарию",payload_json=dict(category=cat,intent=intent)),
                dict(previous_searches=old,growth_pct=round(100*(len(g)/old-1),1)))
    renewal=[]
    renew_clients=[]
    for client,g in by_client.items():
        profile=e.clients.get(client)
        if client=="guest":
            continue
        last=[r for r in g if r["ts"]>=end-72*3600]
        if g[0]["segment"]=="enterprise" and len({r["q"] for r in last if r["zero"]})>=3 and not any(r["leads"] or r["orders"] or r["carts"] for r in last):
            add("hot_lead",client,f"Связаться с клиентом «{profile.title if profile else client}»",last,dict(kind="ticket",label="Передать менеджеру",payload_json=dict(client_id=client)))
    for profile in e.clients.values():
        if imported and profile.client_id not in by_client:
            continue
        contracts=[]
        for own in profile.owned:
            days=own.get("expires_in_days")
            if own.get("expires_at"):
                from datetime import date,datetime
                from zoneinfo import ZoneInfo
                days=(date.fromisoformat(str(own["expires_at"])[:10])-datetime.fromtimestamp(e.clock(),ZoneInfo("Europe/Moscow")).date()).days
            if days is None or not 0<=days<=60:
                continue
            qty=own.get("qty") or 1
            card=e.catalog.cards.get(own.get("card_id"))
            candidates=[o for o in (card.offers if card else []) if o.lic.action=="renewal" and o.available and o.price
                        and o.lic.audience in (None,"business",{"gov":"gov","edu":"edu","individual":"home"}.get(profile.segment,"business"))
                        and not o.price_on_request and (o.lic.qty_min or 1)<=qty<=(o.lic.qty_max or qty)
                        and o.lic.term_months in (12,None) and (not own.get("metric") or o.lic.metric==own["metric"])]
            best=min(candidates,key=lambda o:o.price*ceil(qty/(o.lic.pack or 1)),default=None)
            units=ceil(qty/(best.lic.pack or 1)) if best else None
            price=round(best.price*units,2) if best else None
            review=None
            if not best:
                review="Нет совместимого предложения с открытой ценой"
            elif best.lic.metric=="company" and qty>1 or best.lic.metric=="server" and qty>(profile.fleet.get("servers") or 0):
                review="Сверить количество лицензируемых организаций или серверов"
            elif price>2500000:
                review="Крупная поставка · индивидуальный расчёт"
            contracts.append(dict(product=own.get("product"),expires_in_days=days,seats=qty,units=units,
                             unit_price=best.price if best else None,offer_id=best.offer_id if best else None,
                             rub=price if not review else None,review=review))
        if contracts:
            renew_clients.append(dict(client_id=profile.client_id,licenses=len(contracts),contracts=contracts))
            families={e.catalog.offers_by_id[c["offer_id"]].family_id for c in contracts if c["offer_id"]}
            renewal.extend(r for r in by_client.get(profile.client_id,[]) if r["intent"]=="renewal" and
                           families.intersection(json.loads(r["filters_json"] or "{}").get("family",[])))
    if renew_clients:
        subtotal=sum(c["rub"] or 0 for client in renew_clients for c in client["contracts"])
        unpriced=sum(c["rub"] is None for client in renew_clients for c in client["contracts"])
        add("renewal_campaign","60d","Предложить продление лицензий со сроком до 60 дней",renewal,
            dict(kind="campaign",label="Сформировать список клиентов",payload_json=dict(clients=renew_clients)),
            dict(clients=len(renew_clients),licenses=sum(c["licenses"] for c in renew_clients),manual_review=unpriced),dict(expected_rub=round(subtotal),conservative_rub=0,
            metric_label="Стоимость продлений по каталогу",formula_note="Сумма минимальных цен доступных годовых SKU продления той же редакции × число единиц или пакетов. Онлайн-оценка включает договоры до 2,5 млн ₽ с проверенным количеством. Остальные договоры выделены для расчёта менеджером. Нижняя граница без подтверждённых заказов — 0 ₽."))
    common=[q for q,g in sorted(by_q.items(),key=lambda x:-len(x[1])) if any(r["reason"] not in {"piracy","hardware","gibberish"} for r in g)][:200]
    current=e.controls.weights() or WEIGHTS
    delta=min(.05,current["rel"],current["pop"],(1-current["margin"])/2)
    candidate=dict(current,rel=current["rel"]-delta,pop=current["pop"]-delta,margin=current["margin"]+2*delta)
    test=preview(e,candidate,common)
    gain=sum(x["margin_delta_rub"] for x in test["items"])
    if common and test["moved"] and gain>0 and not test["band_inversions"]:
        add("weights_advice","weights","Увеличить вес маржи", [r for q in common for r in by_q[q]],
            dict(kind="weights",label="Применить веса",payload_json=candidate),dict(tested_weights=candidate,moved=test["moved"],band_inversions=test["band_inversions"],margin_delta_rub=round(gain,2)),
            dict(expected_rub=round(max(0,gain),2),conservative_rub=0,metric_label="Изменение взвешенной маржи на выборке",formula_note=test["formula"]))
    with j.transaction() as db:
        db.executemany("""INSERT INTO insights VALUES (?,?, 'new',?,NULL) ON CONFLICT(id) DO UPDATE SET body=excluded.body WHERE insights.status='new'""",
                       [(k,v["type"],dump(v)) for k,v in suggestions.items()])
        for r in db.execute("SELECT id FROM insights WHERE status='new'").fetchall():
            if r[0] not in suggestions:
                db.execute("DELETE FROM insights WHERE id=?",r)
    return dict(count=len(suggestions),by_type=dict(Counter(v["type"] for v in suggestions.values())))


def listing(j,ident=None):
    sql="SELECT * FROM insights"
    rows=j.rows(sql+" WHERE id=?",(ident,)) if ident else j.rows(sql+""" WHERE coalesce(json_extract(body,'$.dataset'),'mock')=
        coalesce((SELECT value FROM kv WHERE key='settings:history_source'),'mock') ORDER BY type,id""")
    return [json.loads(r["body"])|dict(status=r["status"],verification=json.loads(r["verification"] or "null")) for r in rows]


def transition(e,ident,op):
    e=experiment_engine(e)
    j=e.journal
    with j.transaction() as db:
        items=listing(j,ident)
        if not items:
            raise KeyError(ident)
        item=items[0]
        expected={"apply":"new","reject":"new","verify":"applied"}[op]
        status={"apply":"applied","reject":"rejected","verify":"verified"}[op]
        if item["status"]==status:
            return item
        if item["status"]!=expected:
            raise ValueError("Действие недоступно в текущем состоянии")
        a=item["action"]
        verification=item["verification"] or {}
        if op=="apply":
            verification["before"]={q:compare(e,q) for q in item["evidence"]["sample_queries"]}
            kind=a["kind"]
            if kind in ("ticket","campaign","digest"):
                db.execute("INSERT INTO kv VALUES (?,?,?)",("settings:task:"+ident,dump(a),time()))
                verification["task_id"]=ident
                if item["type"]=="add_product":
                    verification["rule_id"]=e.controls.save("banner",{"phrase":item["evidence"]["sample_queries"][0]},
                        {"text":"Проверяем возможность поставки. Менеджер поможет подобрать доступную замену."})
            elif kind=="weights":
                e.controls.set_weights(a["payload_json"])
            else:
                verification["rule_id"]=e.controls.save(kind,a["conditions"],a["payload_json"])
        if op=="verify":
            after={q:compare(e,q) for q in verification["before"]}
            changed=sum([c["card_id"] for c in r["cards"]]!=[c["card_id"] for c in after[q]["cards"]] or
                        r["banners"]!=after[q]["banners"] for q,r in verification["before"].items())
            regressions=[q for q,b in verification["before"].items() if b["cards"] and not after[q]["cards"]]
            recovered=[q for q,b in verification["before"].items() if not b["cards"] and after[q]["cards"]]
            verification.update(after=after,changed=changed,regressions=regressions,recovered=recovered,verified_at=time(),summary=f"Повторено запросов · {len(after)}. Выдача изменилась · {changed}.")
        db.execute("UPDATE insights SET status=?,verification=? WHERE id=?",(status,dump(verification),ident))
        return listing(j,ident)[0]
