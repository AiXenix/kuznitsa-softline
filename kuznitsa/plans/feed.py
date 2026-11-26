"""Подбор по страницам товаров и классам настоящего магазина."""
import re
from uuid import uuid4
from .feed_query import HOME,HELP,PURPOSES,split_conditions,vendor_class,matching_variants,product_context
from kuznitsa.config import WEIGHTS
from kuznitsa.text import normalize,tokens
from kuznitsa.index.hardware import suitability
from kuznitsa.index.feed import HARDWARE,QUESTION,TASKS,COMPLEX,words
from kuznitsa.rank.business import ranked
from kuznitsa.rank.upsell import interleave, audience as class_audience
from kuznitsa.llm.recovery import cost_summary
from kuznitsa.plans.presentation import profile_info
from kuznitsa.understand.intent import TITLES


def display(engine,cid,profile,preferred=None,selection=None):
    card=engine.catalog.cards[cid]
    audiences={None,"business","home"} if profile.segment=="individual" or profile.client_id=="guest" else {None,"business",profile.segment}
    offer=preferred or next((o for o in card.offers if o.lic.audience in audiences),card.offers[0])
    if selection:offer=selection[0]
    result=ranked(card,selection or (offer,None,None),.92,False,profile,WEIGHTS,engine.kb)
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


def fill(engine,items,profile,popular=False,reserved=(),q="",blocks=None):
    index=engine.catalog.feed
    seen={c["card_id"] for c in items}
    if len(seen)>=4:return []
    pool=[]
    if items:
        anchor=engine.catalog.cards[items[0]["card_id"]]
        o=anchor.offers[0]
        members=index.groups.get(index.card_sections[anchor.id],())
        query_terms=set(words(anchor.title))
        neighbors=index.tree.neighbors(anchor.id,members)
        def related(cid):
            card=index.cat.cards[cid]
            overlap=len(query_terms & set(words(card.title)))
            return (card.vendor==anchor.vendor,overlap,card.category==anchor.category,neighbors.get(cid,0.),index.quality[cid],cid)
        ordered=sorted(members,key=related,reverse=True)
        # Внутри класса сначала показываем соседние линейки того же вендора,
        # затем по одному ближайшему представителю остальных.
        others={}
        for cid in ordered:
            other=index.cat.cards[cid].vendor
            if other==anchor.vendor:pool.append(cid)
            else:others.setdefault(other,cid)
        pool.extend(others.values())
        pool.extend(ordered)
        vendors=engine.catalog.by["vendor"].get(anchor.vendor,())
        pool.extend(sorted((cid for cid in vendors if index.cat.cards[cid].offers[0].domain==o.domain
                            and query_terms.intersection(words(index.cat.cards[cid].title))),key=related,reverse=True))
    eligible=[cid for cid in dict.fromkeys(pool) if cid not in seen and cid not in reserved]
    sections=[]
    if len(eligible)<4-len(seen):
        query=q or (items[0]["title"] if items else "")
        if items:
            section=index.card_sections[items[0]["card_id"]]
            root=anchor.offers[0].category_path[:1]
            query=index.classes[section]+". "+anchor.title
            siblings=[k for k in index.groups if k!=section and root
                      and index.cat.cards[index.groups[k][0]].offers[0].category_path[:1]==root]
            nearest=index.sections(query)
            options=list(dict.fromkeys([*(k for k in nearest if k in siblings),*siblings,*nearest]))
        else:
            options=index.sections(query)
        # Чередуем товары соседних разделов. Ни один раздел не занимает весь добор.
        blocked=seen|set(reserved)|set(eligible)
        candidates=[]
        for k in options:
            remaining=[cid for cid in index.groups[k] if cid not in blocked]
            if remaining:
                sections.append(k)
                candidates.append(remaining)
            if len(sections)>=3 and sum(map(len,candidates))>=4-len(seen)-len(eligible):break
        for pos in range(max((len(g) for g in candidates),default=0)):
            for group in candidates:
                if pos<len(group) and group[pos] not in seen and group[pos] not in eligible and group[pos] not in reserved:
                    eligible.append(group[pos])
            if len(eligible)>=4-len(seen):break
        if blocks is not None and sections:
            blocks[:]=[block for block in blocks if block["type"]!="clarify"]
            blocks.append(dict(type="clarify",title="Уточните раздел",question="В каком разделе продолжить поиск?",
                options=[dict(label=index.classes[k],apply=dict(q=index.classes[k],category=k)) for k in sections[:3]]))
    extra=[]
    for cid in eligible:
        card=display(engine,cid,profile)
        card.update(fill=True,label="Популярное" if popular else "Похожие товары",position=len(seen)+len(extra)+1)
        extra.append(card)
        if len(extra)+len(seen)>=4:break
    return extra


def recommend(engine,q,items,profile,intent,blocked=(),role=None,complete=None):
    """Распределить рекомендации между основной лентой и отдельным блоком."""
    ids=[c["card_id"] for c in items]
    picks=engine.catalog.feed.recommend.picks(engine.journal,q,ids,6+max(len(ids),4)//2,blocked)
    if intent=="product" and len(picks)==1:
        # Если правило предлагает целый класс, отдельному блоку и плитке
        # могут подойти две разные карточки этого класса.
        used_targets=set(blocked)|{picks[0][0]}
        picks+=engine.catalog.feed.recommend.picks(engine.journal,q,ids,2,used_targets)
    if role:
        index=engine.catalog.feed
        role_picks=[]
        used=set(ids)|set(blocked)
        slots=role.get("slots",[])
        if any(s["category"]=="accounting" for s in slots):
            core=("accounting","office_suite","endpoint_security")
            slots=sorted(slots,key=lambda s:core.index(s["category"]) if s["category"] in core else len(core))
        for slot in slots:
            ordered=[]
            for product in slot.get("products",[]):
                ordered.extend(index.products(normalize(product),domain="software")[:3])
            for fid in slot.get("families",[]):
                ordered.extend(sorted(index.tags["families"].get(fid,()),key=index.quality.get,reverse=True))
            if slot["category"]=="accounting":
                ordered.extend(index.products("бухгалтер",domain="software"))
            candidates=index.tags["classes"].get(slot["category"],())
            ordered.extend(sorted(candidates,key=index.quality.get,reverse=True))
            if slot["category"]=="accounting":
                # Общий префикс «1С» встречается также у CRM и систем совместной работы.
                ordered=[i for i in ordered if {"бухгалтер","бухгалтерия","учет"} & set(words(index.cat.cards[i].title))]
            cid=next((i for i in ordered if i not in used and i not in index.recommend.bindings
                      and index.cat.cards[i].offers[0].domain=="software"),None)
            if cid:
                used.add(cid)
                role_picks.append((cid,dict(id="role_"+role["id"]+"_"+slot["category"],
                                            reason=role["title"]+" · "+slot.get("note", "ПО для рабочего места"))))
        picks=role_picks+[(i,r) for i,r in picks if i not in used]
    extra=[]
    picks=picks[:max(0,len(engine.catalog.cards)-4)]
    for cid,rule in picks:
        audience=rule.get("offer",{}).get("audience")
        preferred=engine.catalog.feed.recommend.target_offer(cid,audience) if audience else None
        card=display(engine,cid,profile,preferred)
        card.update(kind="upsell",label="Вам может пригодиться",reason=rule["reason"],rule_id=rule["id"])
        extra.append(card)
    reserved={cid for cid,_ in picks}
    if complete:items.extend(complete(reserved))
    split=min(len(items)//2,len(extra)//2 if intent=="product" else len(extra))
    if split:
        interleave(q,items,extra[-split:] if intent=="product" else extra[:split],start=2 if intent=="product" else 1)
    together=None
    if intent=="product" and len(extra)>split:
        rows=[dict(card=c,reason=c["reason"],rule_id=c["rule_id"]) for c in extra[:min(6,len(extra)-split)]]
        together=dict(type="crosssell",title="Часто покупают вместе",items=rows)
    return together,reserved


def task_sections(engine,q,hint):
    """Одинаковые кандидаты разделов и товаров в поиске и автодополнении."""
    index=engine.catalog.feed
    preferred={}
    focus=()
    note=""
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
    if hint and class_audience(hint)=="business" and not HOME.search(q):
        options=[k for k in options if class_audience(index.classes[k])!="home"] or options
    return options,focus,preferred,note


def search(engine,req,profile,trace,priorities,record):
    index=engine.catalog.feed
    norm=normalize(req.q)
    if req.category and req.category not in index.classes:return
    base,qty,renewal=split_conditions(norm)
    if req.sort or req.weights or req.filters or req.exclude or req.ignore or COMPLEX.search(base) or "\n" in req.q:return
    mapped,_=engine._phrases.apply(base)
    q=index.correct(mapped)
    if req.verbatim:q=base
    hardware=next((w for w in words(q) if w in HARDWARE),None)
    device=index.hardware.get(base)
    role=None
    device_name=norm
    parts=re.split(r"\s+(?:для|в)\s+",norm,maxsplit=1)
    if len(parts)==2 and not re.search(r"\b(?:по|софт|программ\w*|лицензи\w*|антивирус\w*)\b",parts[0]):
        head=parts[0].split()
        for start in range(len(head)):
            name=" ".join(head[start:])
            if name not in index.hardware and name not in HARDWARE:
                continue
            role=next((engine.kb.rows["roles"][key] for _,_,matches in engine.lex.match(tokens(parts[1]))
                       for kind,key,_ in matches if kind=="role"),None)
            if role:
                device_name=name
                device=index.hardware.get(name)
            break
    bare=bool(role or device or hardware and len(q.split())==1)
    hint=next((v for p,v in TASKS if re.search(p,q)),None)
    note=""
    missing=False
    purpose=next((label for pattern,label in PURPOSES if re.search(pattern,q)),None)
    question=bool(QUESTION.search(q) or purpose or HELP.search(q) or any(w.endswith(("ть","ться")) for w in words(q)))
    hint=purpose or hint
    if hardware and not bare and q.startswith("по для "):hint="серверное ПО" if hardware=="сервер" else "операционные системы"
    ids=index.products(q,domain="hardware" if bare else "software" if hardware else None)
    section=req.category if req.category in index.classes else index.class_by_name.get(q) or index.class_match(q)
    vendor,combined=vendor_class(index,base)
    if not combined:vendor,combined=vendor_class(index,q)
    section=combined or section
    if HOME.search(q) and "антивир" in q:
        section=index.class_by_name.get("антивирусы для дома")
    if not ids and not section and not bare and not question and not req.verbatim:
        sounds,corrected=index.sound_products(q)
        if not sounds and q!=base:sounds,corrected=index.sound_products(base)
        if sounds:ids,q=sounds,corrected
    if not section and not bare and not req.verbatim and norm in index.slang and (not ids or index.slang[norm][0]=="vendors"):
        field,ids=index.slang[norm]
        if field=="classes" and not section:
            section=index.cat.cards[ids[0]].offers[0].class_id
    qualified=None
    if not (bare or section or req.verbatim) and (not ids or question):
        qualified=product_context(engine,base)
        if qualified:
            ids,conditions=qualified
            question=False
            hint=None
            note="Варианты указанного продукта с учётом назначения."
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
    if not section and not req.category and (question or hint and not ids):
        options,focus,preferred,note=task_sections(engine,q,hint)
        section=options[0] if options else None
        if options and req.mode=="smart" and engine.decisions:
            model_section=index.decide(engine,q,options,sid,req,calls,focus)
            section=model_section or section
    replacement=index.replacements.get(norm) or index.replacements.get(q)
    unsold=index.unsold_sections.get(q)
    # Упоминание чужой марки в названии модуля не подтверждает продажу самой программы.
    if ids and not qualified and not section and (replacement or q in index.unsold_brands):
        named=tuple(cid for cid in ids if words(index.cat.cards[cid].title)[:len(words(q))]==words(q)
                    or words(index.cat.cards[cid].offers[0].vendor or "")==words(q))
        if named:ids=named
        elif replacement or q in index.unsold_brands:
            ids=()
            parents=index.unsold_brands.get(q)
            if parents and not unsold:
                unsold=max(dict.fromkeys(parents),key=parents.count)
    uncertain=False
    role_reasons={}
    if section:
        members=index.groups[section]
        if vendor:members=[cid for cid in members if index.cat.cards[cid].vendor==vendor]
        if role:
            categories={s["category"] for s in role.get("slots",[])}
            for cid in members:
                card=index.cat.cards[cid]
                choices=[(o,suitability(o,categories,device_name=="мфу")) for o in card.offers]
                offer,reasons=max(choices,key=lambda pair:(len(pair[1]),pair[0].available))
                preferred[cid]=offer
                role_reasons[cid]=reasons
            members=sorted(members,key=lambda cid:(len(role_reasons[cid]),preferred[cid].available),reverse=True)
            note="Рабочее место · "+role["title"]
        if question and not note:
            for key in engine.knowledge.nearest("category",hint or q)[:1]:
                row=engine.kb.rows["categories"][key]
                note=row.get("description") or row.get("title","")
        relevant=[i for i in focus if i in members]
        ids=list(dict.fromkeys([*relevant,*members])) if relevant else members
    elif not ids:
        if not replacement:
            if (not qty and not renewal and not any(t in engine.catalog.source_codes for t in (norm,base))
                    and (unsold or re.fullmatch(r"[a-z][a-z0-9.-]*(?: [a-z0-9.-]+)+",q))):
                options=index.sections(q)
                known=unsold
                if not known and req.mode=="smart" and engine.decisions and options:
                    model_section=index.decide(engine,q,options,sid,req,calls)
                section=known or model_section
                uncertain=section is None
                ids=index.groups[section] if section else []
                missing=True
                note=f"В каталоге нет «{req.q}». "+(f"Варианты из раздела «{index.classes[section]}»."
                        if section else "Уточните назначение программы, чтобы подобрать замену.")
            else:return None
        else:
            ids=list(dict.fromkeys(cid for target in replacement["russian_analogs"]
                for cid in sorted(index.tags["families"].get(target["family"],()),key=index.quality.get,reverse=True)))
            if not ids:return None
            missing=True
            note=f"В каталоге нет «{replacement['product']}». Ниже — доступные замены."
    elif not qualified and len(ids)>1 and len(words(q))>1 and all(w in words(index.cat.cards[ids[0]].title) for w in words(q)):
        # Семейство с несколькими редакциями в одном разделе и общим брендом.
        variants=[index.cat.cards[i] for i in ids[:8]]
        if (len(variants)>=3 and len({c.vendor for c in variants})==1
                and len({c.offers[0].class_id for c in variants})==1
                and all(words(c.title)[:len(words(q))]==words(q) and words(c.title)!=words(q) for c in variants)):
            section=variants[0].offers[0].class_id
    intent="out_of_catalog" if missing else "category" if section else "product"
    selections={}
    if qualified and conditions:
        selections=matching_variants(index,ids,profile,qty,renewal,conditions)
        if selections:ids=list(selections)
        else:note="Линейка найдена. Условия лицензирования для этого назначения нужно уточнить."
    if (qty or renewal) and not selections:
        selections=matching_variants(index,ids,profile,qty,renewal)
        if not selections:
            if not ids:return None
            note="Для выбранной линейки нет предложения с указанными условиями. Ниже близкие варианты."
            missing=True
            intent="out_of_catalog"
        else:
            ids=list(selections)
            if renewal:intent="renewal"
    title=index.classes.get(section) or TITLES[intent]
    trace.add("retrieve","Поиск по фиду",title,candidates=len(ids))
    if question:trace.add("intent","Выбор раздела",title,calls=calls)
    start=(req.page-1)*req.page_size
    items=[display(engine,c,profile,preferred.get(c),selections.get(c)) for c in ids[start:start+req.page_size]]
    for i,c in enumerate(items,1):
        c["position"]=i
        c["score"]["why"].extend(role_reasons.get(c["card_id"],()))
    ctx=dict(q_raw=req.q,q_norm=norm,intent=intent,category_id=section,segment=profile.segment,
             profile_id=profile.client_id,mode=req.mode,channel=req.source,region=profile.region)
    if engine.controls.redirect(ctx):return None
    from kuznitsa.rank.priorities import apply
    applied,moves=apply(items,priorities,ctx,engine.catalog,engine.clock())
    trace.add("business","Порядок карточек","Совпадение названия, наличие и условия поставки",priorities=applied,moves=moves)
    merch=engine.controls.merch(ctx,items)
    items=merch["cards"]
    main=[c["card_id"] for c in items]
    clarify=[]
    def complete(reserved):
        return fill(engine,items,profile,reserved=reserved,q=req.q,blocks=clarify) if req.page==1 else []
    together,recommended=recommend(engine,norm,items,profile,intent,role=role,complete=complete)
    for i,c in enumerate(items,1):c["position"]=i
    blocks=[dict(type="products",title=title,category_id=section,total=len(ids),items=items)]
    if missing:
        blocks=[dict(type="not_in_catalog",title="Нет в каталоге",reason="gap",text=note),
                dict(type="analogs",title="Доступные замены",items=[dict(card=c,reason=note if not c.get("fill") else c["label"]) for c in items])]
    if uncertain:
        blocks=[blocks[0],*clarify,dict(type="products",title="Популярное в ближайших разделах",items=items,total=len(items))]
    else:blocks.extend(clarify)
    if together:blocks.append(together)
    trace.add("upsell","Сопутствующие товары",f"В основной ленте · {sum(c.get('kind')=='upsell' for c in items)}. "
              f"В блоке рекомендаций · {len(together['items']) if together else 0}",status="ok" if recommended else "skip")
    chips=[dict(key="role",label="Роль: "+role["title"],removable=False)] if role else []
    if bare:
        targets=[str(k) for k in (device or {}).get("software_classes",()) if str(k) in index.groups]
        label=(device or {}).get("prompt") or f"Искали ПО для {HARDWARE.get(hardware,norm)}?"
        next_query=index.classes[targets[0]] if targets else f"ПО для {HARDWARE.get(hardware,norm)}"
        apply={"q":next_query}
        if targets:apply["category"]=targets[0]
        chips.append(dict(key="domain",label=label,q=next_query,apply=apply,software_classes=targets,removable=False))
    changes=[{"from":norm,"to":q,"kind":"catalog"}] if base!=q else []
    result=dict(search_id=sid,engine="kuznitsa",engine_version="1.0",mode=req.mode,query=dict(raw=req.q,normalized=norm,corrected=q,corrections=changes,did_you_mean=None),
        understood=dict(intent=intent,intent_title=TITLES[intent],intent_conf=.9,intent_source="jev" if model_section else "rules",filters=dict(category=[section]) if section else {},
        exclude={},qty=qty,entities=[],chips=chips,zero_reason="not_in_catalog" if missing else None,agent_note=note or title),blocks=blocks,facets=[],notes=[],banners=merch["banners"],relax_hints=[],related_queries=[],
        profile=profile_info(profile),cost=cost_summary(calls,engine.usd_rub),trace=trace.steps,timing_ms={})
    if qualified and selections:result["understood"]["filters"].update(conditions)
    if vendor:result["understood"]["filters"]["vendor"]=[vendor]
    if renewal:result["understood"]["filters"]["action"]="renewal"
    if qty:
        chips.append(dict(key="quantity",label=f"Количество · {qty['value']}"))
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
    corrected=norm
    if len(norm)>=2:
        device=index.hardware.get(norm,{})
        hw=next((str(k) for k in device.get("hardware_feed_classes",[]) if str(k) in index.groups),None)
        section=hw or index.class_by_name.get(norm) or index.class_match(norm)
        known=bool(section or norm in index.slang or norm in index.vendor_names or norm in index.aliases)
        mapped,_=engine._phrases.apply(norm)
        query=index.correct(mapped)
        hint=next((label for pattern,label in (*PURPOSES,*TASKS) if re.search(pattern,query)),None)
        task=hint or HELP.search(query) or QUESTION.search(query) or any(w.endswith(("ть","ться")) for w in words(query))
        focus=()
        if HOME.search(query) and "антивир" in query:
            section=index.class_by_name.get("антивирусы для дома") or section
        if not section and task and (len(words(query))>1 or hint and not index.products(query)):
            options,focus,_,_=task_sections(engine,query,hint)
            section=next(iter(options),None)
        if not section:
            section=index.class_by_name.get(query) or index.class_match(query)
            if query=="офисные пакеты":
                section=next((k for k,v in index.class_names.items() if query in v),section)
        if section:
            ids=list(dict.fromkeys([*(i for i in focus if index.card_sections[i]==section),*index.groups[section]]))[:4]
        else:
            hits=index.products(query,prefix=True)
            if norm in index.slang and (not hits or index.slang[norm][0]=="vendors"):
                hits=index.slang[norm][1]
            if not hits:
                hits,sound=index.sound_products(norm)
                if hits and not known:corrected=sound
            if not hits and len(norm)>=3 and not known:
                from kuznitsa.understand.repair import LAYOUT
                layout=norm.translate(LAYOUT)
                hits=index.products(layout,prefix=True)
                if hits:corrected=layout
            ids=list(hits[:4])
            if len(words(norm))==1 and len(hits)>4:
                # Один представитель каждого совпавшего начала линейки.
                prefix=norm
                lines={}
                def prefix_rank(cid):
                    title=normalize(index.cat.cards[cid].title).removeprefix("программа ")
                    return (title.startswith(prefix),index.line_popularity.get(cid,()))
                ordered=sorted(hits,key=prefix_rank,reverse=True)
                for cid in ordered:
                    line=next((t for t in re.findall(r"[\w]+",normalize(index.cat.cards[cid].title)) if t.startswith(prefix)),None)
                    if line:lines.setdefault(line,cid)
                    if len(lines)>=4:break
                ids=list(dict.fromkeys([*lines.values(),*hits[:4]]))[:4]
        if corrected!=norm and not known:
            groups.append(dict(type="corrections",title="Возможно, вы искали",items=[dict(text=corrected,q=corrected,kind="correction",meta="repair")]))
        def entry(cid,preferred=None):
            c=display(engine,cid,profile,preferred)
            return dict(text=c["title"],kind="product",meta=cid,card_id=cid,picture=c["picture"],image=c["picture"],
                        oldprice=c["offer"]["oldprice"],price=c["offer"]["price"],price_on_request=c["offer"]["price_on_request"],badges=c["badges"],q=c["title"])
        if ids:
            groups.append(dict(type="products",title="Товары",items=[entry(i) for i in ids]))
        sections=list(dict.fromkeys(index.card_sections[i] for i in ids))
        matching=[(k,index.classes[k]) for k in sections[:3]]
        if matching:
            groups.append(dict(type="categories",title="Разделы",items=[dict(text=v,q=v,meta=k,kind="category") for k,v in matching]))
        previous=engine.suggestions.prefix(norm,profile.segment,set())
        groups.extend(g for g in previous if g["type"]=="queries")
        picks=index.recommend.picks(engine.journal,norm,ids,2)
        if picks:
            groups.append(dict(type="upsell",title="Возможно, вам понадобится",items=[
                dict(entry(cid,index.recommend.target_offer(cid,rule["offer"]["audience"]) if rule["offer"].get("audience") else None),
                     reason=rule["reason"],rule_id=rule["id"]) for cid,rule in picks]))
    return dict(q=raw,corrected=corrected if corrected!=norm else None,groups=groups,ms=round((perf_counter()-start)*1000,2))
