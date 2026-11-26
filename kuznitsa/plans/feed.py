"""Подбор по страницам товаров и классам настоящего магазина."""
import re
from uuid import uuid4
from itertools import chain
from kuznitsa.config import WEIGHTS
from kuznitsa.text import normalize
from kuznitsa.index.feed import HARDWARE,QUESTION,TASKS,COMPLEX,words
from kuznitsa.rank.business import ranked
from kuznitsa.rank.upsell import interleave
from kuznitsa.llm.recovery import cost_summary
from kuznitsa.plans.presentation import profile_info
from kuznitsa.understand.intent import TITLES


def display(engine,cid,profile,preferred=None):
    card=engine.catalog.cards[cid]
    audiences={None,"business","home"} if profile.segment=="individual" or profile.client_id=="guest" else {None,"business",profile.segment}
    offer=preferred or next((o for o in card.offers if o.lic.audience in audiences),card.offers[0])
    result=ranked(card,(offer,None,None),.92,False,profile,WEIGHTS,engine.kb)
    decorate(result,offer)
    return result


def decorate(card,offer):
    price=card["offer"]
    card.update(domain=offer.domain,picture=offer.image,image=offer.image,url=offer.url)
    price.update(picture=offer.image,url=offer.url,oldprice=offer.oldprice if offer.price and offer.oldprice and offer.oldprice>offer.price else None)
    badges=card["badges"]
    badges[:]=[b for b in badges if b.get("kind") not in ("promo","on_request","on_order")]
    if offer.price and offer.oldprice and 0<offer.price<offer.oldprice:
        percent=round(100*(1-offer.price/offer.oldprice))
        badges.append(dict(kind="promo",label=f"Акция −{percent} %"))
        card.update(oldprice=offer.oldprice,discount_pct=percent)
    if not offer.price:badges.append(dict(kind="on_request",label="Цена по запросу"))
    if not offer.available:badges.append(dict(kind="on_order",label="Под заказ"))


def fill(engine,items,profile,popular=False,reserved=()):
    index=engine.catalog.feed
    seen={c["card_id"] for c in items}
    if len(seen)>=4:return []
    pool=[]
    if items:
        anchor=engine.catalog.cards[items[0]["card_id"]]
        o=anchor.offers[0]
        pool.extend(index.groups.get(o.class_id or anchor.category,()))
        pool.extend(sorted(engine.catalog.by["vendor"].get(anchor.vendor,()),key=index.quality.get,reverse=True))
        if len(seen.union(pool))<4:
            scores=engine.catalog.bm.scores(anchor.title+" "+index.classes.get(o.class_id,""))
            pool.extend(engine.catalog.ids[i] for i in scores.argsort()[::-1][:12] if scores[i]>0)
    extra=[]
    for cid in chain((i for i in chain(pool,index.popular) if i not in reserved),reserved):
        if cid in seen:continue
        seen.add(cid)
        card=display(engine,cid,profile)
        card.update(fill=True,label="Популярное" if popular else "Похожие товары",position=len(seen))
        extra.append(card)
        if len(seen)>=4:break
    return extra


def recommend(engine,q,items,profile,intent,blocked=()):
    """Распределить рекомендации между основной лентой и отдельным блоком."""
    ids=[c["card_id"] for c in items]
    picks=engine.catalog.feed.recommend.picks(engine.journal,q,[*ids,*blocked],6+len(ids)//2)
    extra=[]
    picks=picks[:max(0,len(engine.catalog.cards)-4)]
    for cid,rule in picks:
        card=display(engine,cid,profile)
        card.update(kind="upsell",label="Вам может пригодиться",reason=rule["reason"],rule_id=rule["id"])
        extra.append(card)
    split=min(len(ids)//2,len(extra)//2 if intent=="product" else len(extra))
    if split:interleave(q,items,extra[-split:])
    together=None
    if intent=="product" and len(extra)>split:
        rows=[dict(card=c,reason=c["reason"],rule_id=c["rule_id"]) for c in extra[:min(6,len(extra)-split)]]
        together=dict(type="crosssell",title="Часто покупают вместе",items=rows)
    return together,{cid for cid,rule in picks}


def search(engine,req,profile,trace,priorities,record):
    index=engine.catalog.feed
    norm=normalize(req.q)
    if req.category and req.category not in index.classes:return
    if req.sort or req.weights or req.filters or req.exclude or req.ignore or COMPLEX.search(norm) or "\n" in req.q:return
    mapped,_=engine._phrases.apply(norm)
    q=index.correct(mapped)
    if req.verbatim:q=norm
    hardware=next((w for w in words(q) if w in HARDWARE),None)
    device=index.hardware.get(norm)
    bare=bool(device or hardware and len(q.split())==1)
    hint=next((v for p,v in TASKS if re.search(p,q)),None)
    note=""
    missing=False
    question=bool(QUESTION.search(q))
    if hardware and not bare and q.startswith("по для "):hint="серверное ПО" if hardware=="сервер" else "операционные системы"
    ids=index.products(q,domain="hardware" if bare else "software" if hardware else None)
    section=req.category if req.category in index.classes else index.class_by_name.get(q)
    if not ids and not section and not bare and not req.verbatim and norm in index.slang:
        field,ids=index.slang[norm]
        if field=="classes" and not section:
            section=index.cat.cards[ids[0]].offers[0].class_id
    calls=[]
    model_section=None
    sid="s_"+uuid4().hex
    if bare:
        trace.add("domain","Оборудование или ПО","Ищем в разделах оборудования")
        choices=[k for k,v in index.classes.items() if hardware and hardware in words(v) and index.cat.cards[index.groups[k][0]].offers[0].domain=="hardware"]
        if choices:section=min(choices,key=lambda k:len(index.classes[k]))
        if device:
            section=next((str(k) for k in device["hardware_feed_classes"] if str(k) in index.groups),section)
    if not ids and hardware and not bare and not hint:
        system=" ".join(w for w in words(q) if w!=hardware)
        ids=index.products(system,domain="software")
        if hardware=="сервер" and system:
            compatible=[i for i in ids if "для "+system in normalize(index.cat.cards[i].title)]
            if compatible:
                ids=compatible
                note="Найдены серверные продукты, в названии которых указана совместимость с системой."
    if q=="офисные пакеты":
        section=next((k for k,v in index.classes.items() if "офисные пакеты" in v.lower()),None)
    focus=()
    preferred={}
    if hint and q in ("антивирус","антивирусы"):
        section=next((k for k,v in index.class_names.items() if v==hint),None)
    if not req.category and (question or hint and not ids):
        options=index.sections(q,hint or "")
        for pattern,terms in [(r"почт","mail security"),(r"чертеж","cad"),(r"контрагент","контрагент"),(r"сервер","server security")]:
            if re.search(pattern,q):
                needle=set(words(terms))
                focus=tuple(i for i in index.products(terms,domain="software")
                            if needle<=set(words(index.cat.cards[i].title)))
                if not focus:
                    scores=engine.catalog.bm.scores(terms)
                    for i in scores.argsort()[::-1][:30]:
                        if scores[i]<=0:break
                        cid=engine.catalog.ids[i]
                        c=engine.catalog.cards[cid]
                        if c.offers[0].domain!="software":continue
                        offer=next((o for o in c.offers if needle<=set(words(o.name))),None)
                        if offer:preferred[cid]=offer
                    focus=tuple(preferred)
                break
        if hint and focus:
            expected=index.class_by_name.get(hint)
            if expected:
                focus=tuple(sorted(focus,key=lambda i:index.cat.cards[i].offers[0].class_id!=expected))
        direct_focus=focus
        tasks=engine.knowledge.nearest("use_case",q)
        for key in tasks[:3]:
            row=index.task_rows[key]
            important=set(words(q))-{"программа","использовать","против","что","как","чем"}
            if not important or not any(important<=set(words(s)) for s in row.get("phrases",[])):continue
            matches=set().union(*(index.tags["families"].get(f,()) for f in row.get("families",[])))
            if matches:
                focus=tuple(dict.fromkeys([*focus,*sorted(matches,key=index.quality.get,reverse=True)]))
                note=row.get("title") or next(iter(row.get("features",[])),"")
                break
        options=list(dict.fromkeys([*(index.cat.cards[i].offers[0].class_id for i in focus[:5]),*options]))[:8]
        if direct_focus:
            # Варианты разделов должны содержать товары для указанной задачи.
            options=list(dict.fromkeys(index.cat.cards[i].offers[0].class_id for i in direct_focus[:12]))[:8]
        section=options[0] if options else None
        if options and req.mode=="smart" and engine.decisions:
            model_section=index.decide(engine,q,options,sid,req,calls,focus)
            section=model_section or section
    if section:
        members=index.groups[section]
        if question and not note:
            for key in engine.knowledge.nearest("category",hint or q)[:1]:
                row=engine.kb.rows["categories"][key]
                note=row.get("description") or row.get("title","")
        relevant=[i for i in focus if i in members]
        ids=list(dict.fromkeys([*relevant,*members])) if relevant else members
    elif not ids:
        replacement=index.replacements.get(norm)
        if not replacement:return None
        ids=list(dict.fromkeys(cid for target in replacement["russian_analogs"]
            for cid in sorted(index.tags["families"].get(target["family"],()),key=index.quality.get,reverse=True)))
        if not ids:return None
        missing=True
        note=f"В каталоге нет «{replacement['product']}». Ниже — доступные замены."
    elif len(ids)>1 and len(words(q))>1 and all(w in words(index.cat.cards[ids[0]].title) for w in words(q)):
        # Семейство с несколькими редакциями в одном разделе и общим брендом.
        variants=[index.cat.cards[i] for i in ids[:8]]
        if (len(variants)>=3 and len({c.vendor for c in variants})==1
                and len({c.offers[0].class_id for c in variants})==1
                and all(words(c.title)[:len(words(q))]==words(q) and words(c.title)!=words(q) for c in variants)):
            section=variants[0].offers[0].class_id
    intent="out_of_catalog" if missing else "category" if section else "product"
    title=index.classes.get(section) or TITLES[intent]
    trace.add("retrieve","Поиск по фиду",title,candidates=len(ids))
    if question:trace.add("intent","Выбор раздела",title,calls=calls)
    start=(req.page-1)*req.page_size
    items=[display(engine,c,profile,preferred.get(c)) for c in ids[start:start+req.page_size]]
    for i,c in enumerate(items,1):c["position"]=i
    ctx=dict(q_raw=req.q,q_norm=norm,intent=intent,category_id=section,segment=profile.segment,
             profile_id=profile.client_id,mode=req.mode,channel=req.source,region=profile.region)
    if engine.controls.redirect(ctx):return None
    from kuznitsa.rank.priorities import apply
    applied,moves=apply(items,priorities,ctx,engine.catalog,engine.clock())
    trace.add("business","Порядок карточек","Совпадение названия, наличие и условия поставки",priorities=applied,moves=moves)
    merch=engine.controls.merch(ctx,items)
    items=merch["cards"]
    main=[c["card_id"] for c in items]
    together,recommended=recommend(engine,q,items,profile,intent)
    more=fill(engine,[c for c in items if c.get("kind")!="upsell"],profile,reserved=recommended) if req.page==1 else []
    items.extend(more)
    for i,c in enumerate(items,1):c["position"]=i
    blocks=[dict(type="products",title=title,category_id=section,total=len(ids),items=items)]
    if missing:
        blocks=[dict(type="not_in_catalog",title="Нет в каталоге",reason="gap",text=note),
                dict(type="analogs",title="Доступные замены",items=[dict(card=c,reason=note if not c.get("fill") else c["label"]) for c in items])]
    if together:blocks.append(together)
    trace.add("upsell","Сопутствующие товары",f"В основной ленте · {sum(c.get('kind')=='upsell' for c in items)}. "
              f"В блоке рекомендаций · {len(together['items']) if together else 0}",status="ok" if recommended else "skip")
    chips=[]
    if bare:
        targets=[str(k) for k in (device or {}).get("software_classes",()) if str(k) in index.groups]
        label=(device or {}).get("prompt") or f"Искали ПО для {HARDWARE.get(hardware,norm)}?"
        next_query=index.classes[targets[0]] if targets else f"ПО для {HARDWARE.get(hardware,norm)}"
        apply={"q":next_query}
        if targets:apply["category"]=targets[0]
        chips.append(dict(key="domain",label=label,q=next_query,apply=apply,software_classes=targets,removable=False))
    changes=[{"from":norm,"to":q,"kind":"catalog"}] if norm!=q else []
    result=dict(search_id=sid,engine="kuznitsa",engine_version="1.0",mode=req.mode,query=dict(raw=req.q,normalized=norm,corrected=q,corrections=changes,did_you_mean=None),
        understood=dict(intent=intent,intent_title=TITLES[intent],intent_conf=.9,intent_source="jev" if model_section else "rules",filters=dict(category=[section]) if section else {},
        exclude={},qty=None,entities=[],chips=chips,zero_reason="not_in_catalog" if missing else None,agent_note=note or title),blocks=blocks,facets=[],notes=[],banners=merch["banners"],relax_hints=[],related_queries=[],
        profile=profile_info(profile),cost=cost_summary(calls,engine.usd_rub),trace=trace.steps,timing_ms={})
    if calls and not calls[-1].get("ok"):
        result["mode"]="fast"
        result["notes"].append("Раздел выбран быстрым поиском: категоризатор недоступен.")
    result["timing_ms"]["total"]=round(1000*(engine.timer()-trace.start),2)
    if record:
        if engine.sessions:engine.sessions.save(req,result,items)
        engine.journal.search(engine.clock(),req,result,len(main),result["understood"]["zero_reason"],False)
    if not req.explain:result["trace"]=[]
    return result


def suggestions(engine,raw,norm,profile,start):
    from time import perf_counter
    index=engine.catalog.feed
    groups=[]
    corrected=index.correct(norm)
    if len(norm)>=2:
        device=index.hardware.get(norm,{})
        hardware_sections=[str(k) for k in device.get("hardware_feed_classes",[]) if str(k) in index.groups]
        ids=(index.groups[hardware_sections[0]] if hardware_sections else index.products(corrected,prefix=True))[:4]
        if not ids and norm in index.slang:
            ids=index.slang[norm][1][:4]
        if not ids and len(norm)>=3:
            from kuznitsa.understand.repair import LAYOUT
            layout=norm.translate(LAYOUT)
            ids=index.products(layout,prefix=True)[:4]
            if ids:corrected=layout
        if corrected!=norm:
            groups.append(dict(type="corrections",title="Возможно, вы искали",items=[dict(text=corrected,q=corrected,kind="correction",meta="repair")]))
        def entry(cid):
            c=display(engine,cid,profile)
            return dict(text=c["title"],kind="product",meta=cid,card_id=cid,picture=c["picture"],image=c["picture"],
                        oldprice=c["offer"]["oldprice"],price=c["offer"]["price"],price_on_request=c["offer"]["price_on_request"],badges=c["badges"],q=c["title"])
        if ids:
            groups.append(dict(type="products",title="Товары",items=[entry(i) for i in ids]))
        sections=list(dict.fromkeys([*hardware_sections,*(k for k,v in index.classes.items() if norm in v.casefold())]))
        matching=[(k,index.classes[k]) for k in sections[:3]]
        if matching:
            groups.append(dict(type="categories",title="Разделы",items=[dict(text=v,q=v,meta=k,kind="category") for k,v in matching]))
        previous=engine.suggestions.prefix(norm,profile.segment,set())
        groups.extend(g for g in previous if g["type"]=="queries")
        picks=index.recommend.picks(engine.journal,norm,ids or (index.groups[matching[0][0]] if matching else []),2)
        if picks:
            groups.append(dict(type="upsell",title="Возможно, вам понадобится",items=[
                dict(entry(cid),reason=rule["reason"],rule_id=rule["id"]) for cid,rule in picks]))
    return dict(q=raw,corrected=corrected if corrected!=norm else None,groups=groups,ms=round((perf_counter()-start)*1000,2))
