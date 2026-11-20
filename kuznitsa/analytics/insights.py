"""Предложения строятся по наблюдаемым фразам, действиям и карточкам."""
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
            moved=sum(x["card_id"]!=y["card_id"] for x,y in zip(before,after)),
            band_inversions=sum(x["tier"]>y["tier"] for i,x in enumerate(after) for y in after[i+1:]),
            margin_delta_rub=sum(x["margin_rub"]/(i+1) for i,x in enumerate(after[:5]))-
                             sum(x["margin_rub"]/(i+1) for i,x in enumerate(before[:5]))))
    return dict(items=items,moved=sum(x["moved"] for x in items),band_inversions=sum(x["band_inversions"] for x in items),
                formula="Сумма удельной маржи первых пяти позиций с весом 1 / позиция")


def discover(e):
    j=e.journal
    rows=[r for r in facts(j) if r["source"] in ("ui","history")]
    end=max((r["ts"] for r in rows),default=e.clock())
    recent=[r for r in rows if r["ts"]>end-30*86400]
    losses,_=loss_by_search(rows)
    suggestions={}
    def add(kind,key,title,g,action,extra=None,impact=None):
        if not g:
            return
        samples=Counter(r["q"] for r in g)
        sessions={r["session_id"] for r in g}
        ident=kind+"-"+hashlib.sha256(str(key).encode()).hexdigest()[:12]
        evidence=dict(searches_30d=len(g),sessions_30d=len(sessions),sample_queries=[q for q,_ in samples.most_common(8)],
                      sample_sessions=sorted(sessions)[:6],segments=dict(Counter(r["segment"] for r in g)),
                      metric_before=dict(zero=sum(r["zero"] for r in g),orders=sum(r["orders"] for r in g)),
                      **(extra or {}))
        sums=[round(sum(losses.get(r["search_id"],(0,0))[i] for r in g)) for i in range(2)]
        suggestions[ident]=dict(id=ident,type=kind,role=ROLES[kind],title=title,status="new",
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
       FROM events e JOIN searches s USING(search_id) WHERE e.type='reformulate' AND s.zero=1 AND s.ts>?
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
            add("add_product",item["key"],f"Проверить поставку «{item['title']}»",[r for q in item["queries"] for r in by_q[q]],
                dict(kind="ticket",label="Завести товар",payload_json=dict(product=item["key"],category=item["category"])))
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
                defects=[c for c in cards if any(not any((o.lic.qty_min or 1)<=n<=(o.lic.qty_max or float("inf"))
                         for o in e.catalog.cards[c["card_id"]].offers if o.lic.qty_min or o.lic.qty_max) for n in sizes)]
            if len(affected)>=5 and defects:
                add("fix_card",(cat,field),f"Дополнить {label} в категории «{e.names['category'].get(cat,cat)}»",affected,
                    dict(kind="ticket",label="Поставить задачу контент-менеджеру",payload_json=dict(field=field,card_ids=[c["card_id"] for c in defects])),
                    dict(impressions=sum(c["impressions"] for c in defects)))
    for r in j.rows("""SELECT s.q_raw q,e.card_id,count(*) n,avg(e.position) pos FROM events e JOIN searches s USING(search_id)
        WHERE e.type='click' AND s.ts>? AND e.position>4 AND s.source IN ('ui','history') GROUP BY 1,2 HAVING count(*)>=2""",(end-30*86400,)):
        if any(r["card_id"] in json.loads(hit["top_cards_json"] or "[]")[:3] for hit in by_q[r["q"]]):
            continue
        if r["card_id"] in e.catalog.cards:
            add("merch_rule",(r["q"],r["card_id"]),f"Поднять «{e.catalog.cards[r['card_id']].title}» по запросу «{r['q']}»",by_q[r["q"]],
                dict(kind="boost",label="Поднять внутри уровня",conditions=dict(phrase=r["q"]),payload_json=dict(card_id=r["card_id"],factor=1.3)),dict(late_clicks=r["n"],mean_position=r["pos"]))
    for item in gaps["departed"]:
        if item["sessions"]>=10:
            add("merch_rule",item["key"],f"Предложить подбор замены для {item['title']}",[r for q in item["queries"] for r in by_q[q]],
                dict(kind="banner",label="Показать предложение замены",conditions=dict(phrase=item["queries"][0]),
                     payload_json=dict(text="Нужна совместимая замена? Запросите подбор у менеджера.")))
    previous=Counter(r["category"] for r in rows if end-60*86400<r["ts"]<=end-30*86400)
    for cat,g in by_cat.items():
        old=previous[cat]
        if cat and len(g)>=20 and old>=5 and len(g)>=1.5*old:
            add("rising_demand",cat,f"Развить подборку «{e.names['category'].get(cat,cat)}»",g,
                dict(kind="digest",label="Включить в план ассортимента",payload_json=dict(category=cat)),
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
        if not profile:
            continue
        owned=[p for p in profile.owned if p.get("expires_in_days") is not None and 0<=p["expires_in_days"]<=30]
        if owned and not any(r["orders"] and r["intent"]=="renewal" for r in g):
            renew_clients.append(dict(client_id=client,licenses=len(owned)))
            renewal.extend(g)
    add("renewal_campaign","30d","Предложить продление до окончания лицензии",renewal,
        dict(kind="campaign",label="Сформировать список клиентов",payload_json=dict(clients=renew_clients)))
    common=[q for q,g in sorted(by_q.items(),key=lambda x:-len(x[1])) if any(r["reason"] not in {"piracy","hardware","gibberish"} for r in g)][:200]
    current=e.controls.weights() or WEIGHTS
    delta=min(.02,current["rel"],current["pop"],(1-current["margin"])/2)
    candidate=dict(current,rel=current["rel"]-delta,pop=current["pop"]-delta,margin=current["margin"]+2*delta)
    test=preview(e,candidate,common)
    gain=sum(x["margin_delta_rub"] for x in test["items"])
    if common and not test["band_inversions"]:
        add("weights_advice","weights","Увеличить вес маржи" if gain>0 else "Сохранить текущие веса ранжирования", [r for q in common for r in by_q[q]],
            dict(kind="weights",label="Применить веса",payload_json=candidate if gain>0 else current),dict(tested_weights=candidate,moved=test["moved"],band_inversions=test["band_inversions"],margin_delta_rub=round(gain,2)),
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
    rows=j.rows(sql+" WHERE id=?",(ident,)) if ident else j.rows(sql+" ORDER BY type,id")
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
