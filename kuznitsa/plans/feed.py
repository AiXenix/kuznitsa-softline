"""Подбор по страницам товаров и классам настоящего магазина."""
import re
from uuid import uuid4
from . import feed_analogs, feed_compare, feed_conditions, feed_guard, feed_noise
from .feed_query import HOME,HELP,PURPOSES,split_conditions,vendor_class,matching_variants,product_context,license_request,split_budget,product_subject,named_subject,software_scope
from .feed_query import purchase_subject, supplier_clause, mixed_subject, software_for_class, strip_question, resolve_solution
from kuznitsa.config import WEIGHTS
from kuznitsa.index.feed_language import version_forms,edition_form,sold_as,spoken_initials
from kuznitsa.index.feed_repair import identity_terms
from kuznitsa.understand.quantities import spoken_numbers
from kuznitsa.text import normalize,tokens
from kuznitsa.index.hardware import suitability,hardware_head,resolve_hardware_section,rank_hardware_section
from kuznitsa.index.feed import HARDWARE,QUESTION,TASKS,COMPLEX,words,class_words
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


def fill(engine,items,profile,reserved=(),q="",blocks=None):
    index=engine.catalog.feed
    seen={c["card_id"] for c in items}
    if len(seen)>=4:return []
    pool=[]
    if items:
        anchor=engine.catalog.cards[items[0]["card_id"]]
        o=anchor.offers[0]
        members=index.groups.get(index.card_sections[anchor.id],())
        query_terms={w for w in words(anchor.title) if not w.isdecimal()}
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
        label="Похожие товары"
        if not items and sections:
            label="Из раздела «"+index.classes[index.card_sections[cid]]+"»"
        card.update(fill=True,label=label,position=len(seen)+len(extra)+1)
        extra.append(card)
        if len(extra)+len(seen)>=4:break
    return extra


def recommend(engine,q,items,profile,intent,blocked=(),role=None,complete=None,price_max=None,edition_audience=None):
    """Распределить рекомендации между основной лентой и отдельным блоком."""
    ids=[c["card_id"] for c in items]
    picks=engine.catalog.feed.recommend.picks(engine.journal,q,ids,6+max(len(ids),4)//2,blocked,edition_audience)
    if intent=="product" and len(picks)==1:
        # Если правило предлагает целый класс, отдельному блоку и плитке
        # могут подойти две разные карточки этого класса.
        used_targets=set(blocked)|{picks[0][0]}
        picks+=engine.catalog.feed.recommend.picks(engine.journal,q,ids,2,used_targets,edition_audience)
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
        preferred=engine.catalog.feed.recommend.target_offer(cid,audience,price_max) if audience or price_max is not None else None
        if price_max is not None and preferred is None:continue
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
    hit=index.solutions.match(q)
    if hit:
        return list(hit.sections),hit.cards,{},hit.note
    task=index.task_class(q)
    if task:
        # Формулировки задачи в словаре уже связаны с разделами этого снимка.
        return [task],(),{},f"Для этой задачи подойдёт раздел «{index.classes[task]}»."
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


def _search_solution(engine,req,profile,trace,priorities,record,norm,base,qty,budget,solution):
    index=engine.catalog.feed
    sid="s_"+uuid4().hex
    section=solution.sections[0] if solution.sections else None
    ids=list(solution.cards)
    note=solution.note
    title=solution.title
    intent="category" if section else "product"
    selections={}
    constraints={"price_max":budget} if budget is not None else {}
    use_qty=None if solution.kit else qty
    if ids and (use_qty or constraints):
        nodes=bool(re.search(r"\bуз(?:ел|л\w*)\b",norm))
        selections=matching_variants(index,ids,profile,use_qty,False,constraints,nodes=nodes)
        if selections:
            ordered=[cid for cid in ids if cid in selections]
            if use_qty and budget is None:
                others=[cid for cid in ids if cid not in selections]
                if others:
                    note=note or "Тираж учтён при подборе лицензий. Варианты без подтверждения количества отмечены отдельно."
                ordered.extend(others)
            ids=ordered
        elif budget is not None:
            ids=[]
            note="В указанном бюджете предложений с подтверждённой ценой нет."
    trace.add("retrieve","Поиск по задаче",title,candidates=len(ids))
    trace.add("intent","Выбор решения",title)
    start=(req.page-1)*req.page_size
    items=[display(engine,c,profile,None,selections.get(c)) for c in ids[start:start+req.page_size]]
    for i,c in enumerate(items,1):
        c["position"]=i
        if use_qty and c["card_id"] not in selections:
            c["badges"].append(dict(kind="quantity",label="Тираж требует уточнения"))
            c["score"]["why"].append("Количество по этой лицензии требует уточнения у поставщика")
    merch=order(engine,req,profile,trace,priorities,intent,section,items)
    if merch is None:return None
    items=merch["cards"]
    main=[c["card_id"] for c in items]
    clarify=[]
    def complete(reserved):
        if budget is not None or req.page!=1:return []
        return fill(engine,items,profile,reserved=reserved,q=req.q,blocks=clarify)
    together,recommended=recommend(engine,norm,items,profile,intent,complete=complete,price_max=budget)
    for i,c in enumerate(items,1):c["position"]=i
    blocks=[dict(type="products",title=title,category_id=section,total=len(ids),items=items)]
    blocks.extend(clarify)
    if together:blocks.append(together)
    chips=[]
    if budget is not None:
        chips.append(dict(key="price_max",label=f"До {budget:g} ₽",removable=True))
    if qty:
        chips.append(dict(key="quantity",label=f"Количество · {qty['value']}"))
    result=dict(search_id=sid,engine="kuznitsa",engine_version="1.0",mode=req.mode,
        query=dict(raw=req.q,normalized=norm,corrected=base,corrections=[],did_you_mean=None),
        understood=dict(intent=intent,intent_title=TITLES[intent],intent_conf=.9,intent_source="rules",
                        filters=dict(category=[section]) if section else {},
                        exclude={},qty=qty,entities=[],chips=chips,
                        zero_reason="filters_too_strict" if (budget is not None and not ids) else None,
                        agent_note=note or title),
        blocks=blocks,facets=[],notes=[],banners=merch["banners"],relax_hints=[],related_queries=[],
        profile=profile_info(profile),cost=cost_summary([],engine.usd_rub),trace=trace.steps,timing_ms={})
    if budget is not None:
        result["understood"]["filters"]["price_max"]=budget
    return finish(engine,req,trace,record,result,items,len(main),[])


def search(engine,req,profile,trace,priorities,record):
    index=engine.catalog.feed
    norm=normalize(req.q)
    if norm in {"про","pro"} and not req.verbatim and not req.category:
        question="У какого продукта нужна редакция Pro?"
        trace.add("intent","Уточнение продукта",question)
        groups=list(dict.fromkeys(index.card_sections[c] for c in index.products("pro",domain="software",fuzzy=False)))
        options=[dict(label=index.classes[k],apply=dict(q=index.classes[k],category=k)) for k in groups[:3]]
        result=dict(search_id="s_"+uuid4().hex,engine="kuznitsa",engine_version="1.0",mode=req.mode,
            query=dict(raw=req.q,normalized=norm,corrected=norm,corrections=[],did_you_mean=None),
            understood=dict(intent="broad",intent_title=TITLES["broad"],intent_conf=.9,intent_source="rules",
                            filters={},exclude={},qty=None,entities=[],chips=[],zero_reason=None,agent_note=question),
            blocks=[dict(type="clarify",title="Уточните продукт",question=question,options=options)],
            facets=[],notes=[],banners=[],relax_hints=[],related_queries=[],profile=profile_info(profile),
            cost=cost_summary([],engine.usd_rub),trace=trace.steps,timing_ms={})
        return finish(engine,req,trace,record,result,[],0,[])
    if req.category and req.category not in index.classes:return
    if not req.category and not req.filters and feed_noise.is_garbage_syntax(req.q,norm,index,engine.catalog):
        result=feed_guard.build_garbage_result(engine,req,profile,trace,norm)
        return finish(engine,req,trace,record,result,[],0,[],profile=profile)
    if not (req.verbatim or req.category or req.filters or req.exclude or req.sort or req.weights or "\n" in req.q):
        vendor_hit=feed_noise.detect_vendor_catalog(index,engine,norm)
        if vendor_hit:
            return feed_guard.build_vendor_result(engine,req,profile,trace,priorities,record,norm,*vendor_hit)
    compared=feed_compare.search(engine,req,profile,trace,priorities,record,norm)
    if compared is not None:return compared
    cond=feed_conditions.extract(engine,norm,req)
    subject,budget=cond.subject,cond.price_max
    # «Дешевле N» в тексте — мягкий потолок: при пустом пересечении остаются самые доступные варианты.
    soft_budget=budget is not None and req.filters.get("price_max") is None and bool(re.search(r"\bдешевле\b",norm))
    parsed=subject if req.verbatim else version_forms(spoken_numbers(spoken_initials(index,subject)))
    if parsed!=subject and index.recovery.full_name(subject)[0]:
        parsed=subject
    base,qty,renewal=split_conditions(parsed)
    original_subject=base
    solution=resolve_solution(engine,req,norm,base,renewal=renewal)
    if solution:
        return _search_solution(engine,req,profile,trace,priorities,record,norm,base,qty,budget,solution)
    if not req.verbatim:
        cleaned=strip_question(base)
        if cleaned!=base:
            base=cleaned
            original_subject=base
    replacement_for=feed_analogs.requested(base)
    if replacement_for:
        replacement_for=feed_noise.clean_analog_subject(replacement_for)
    noise_clean=None
    if not replacement_for and not req.verbatim and not req.category and not feed_noise.FEED_COMPLEX.search(base):
        noise_clean=feed_noise.extract_conditions_and_noise(engine,index,base,existing_qty=qty)
        if noise_clean.changed:
            base=noise_clean.subject
            qty=noise_clean.qty
    edition=index.edition(base) if not (req.verbatim or req.category or replacement_for) else None
    row=index.analogs.lookup(replacement_for or base, fuzzy=not req.verbatim)
    if not edition and (replacement_for or row and not row["in_catalog"]) and not (
            req.exclude or req.filters.keys()-{"price_max","registry","audience","category"} or "\n" in req.q):
        analog_target=replacement_for or (cond.raw_for_analogs if cond.platform else base)
        return feed_analogs.search(engine,req,profile,trace,priorities,record,analog_target,
                                  row,explicit=bool(replacement_for),qty=qty,budget=budget)
    if not (req.verbatim or req.category or edition or replacement_for):
        missing_gen=feed_guard.check_missing_generation(index,base)
        if missing_gen:
            return feed_guard.build_missing_generation_result(engine,req,profile,trace,priorities,record,norm,*missing_gen)
    literal=index.recovery.full_name(base) if not req.verbatim else ((),base,None)
    supplier=None
    if not req.verbatim and not literal[0]:
        base,supplier=supplier_clause(index,purchase_subject(base))
    if (req.sort and req.sort not in ("price_asc","price_desc")) or req.weights or req.filters.keys()-{"price_max","price_min","origin","registry"} or req.exclude or set(req.ignore)-{"price_max","price_min","sort","exclude","origin","registry","platform","action"} or (feed_noise.FEED_COMPLEX.search(base) and not (literal[0] and literal[2]=="layout")) or "\n" in req.q:return
    absent_acronym=None
    acronym=()
    device_name=hardware_head(index,base)
    if not (literal[0] or req.verbatim or req.category or device_name):
        acronym=index.language.acronym_cards(index,base)
        absent_acronym=next((index.language.absent_acronyms[w] for w in words(base)
                             if not acronym and w in index.language.absent_acronyms),None)
        if absent_acronym:base=normalize(absent_acronym[0])
    server_section=software_scope(index,base) if not literal[0] else None
    explicit_class=index.class_match(base)
    if supplier and not explicit_class:
        subject_class=re.split(r"\s+для\s+",base,maxsplit=1)[0]
        explicit_class=index.class_match(subject_class)
        if not explicit_class and re.fullmatch(r"антивирус\w*",subject_class):
            explicit_class=index.class_by_name.get("антивирусы для организаций")
    if not (explicit_class or literal[0] or req.verbatim):
        explicit_class=index.language.qualified_class(index,base)
    identity=identity_terms(base) if not (literal[0] or explicit_class or req.category or device_name) else ()
    identity_pool=index.recovery.identity_cards(identity) if identity else None
    unknown_name=identity_pool is not None and not identity_pool
    if not (req.verbatim or literal[0] or server_section or req.category or explicit_class or device_name or unknown_name):
        direct=index.products(base,fuzzy=False)
        if not direct or not set(words(base))<=set(words(index.cat.cards[direct[0]].title)):
            candidate_base=named_subject(engine,product_subject(index,base))
            if candidate_base and not feed_noise.is_edition_only(candidate_base):
                base=candidate_base
        base=mixed_subject(index,base)
    mapped,_=engine._phrases.apply(base)
    q=edition_form(index,index.correct(mapped))
    if req.verbatim:q=base
    hardware=next((w for w in words(q) if w in HARDWARE),None)
    device=index.hardware.get(device_name)
    role=None
    parts=re.split(r"\s+(?:для|в)\s+",base,maxsplit=1)
    if device and len(parts)==2:
        role=next((engine.kb.rows["roles"][key] for _,_,matches in engine.lex.match(tokens(parts[1]))
                   for kind,key,_ in matches if kind=="role"),None)
    bare=bool(role or device or hardware and len(q.split())==1)
    hint=next((v for p,v in TASKS if re.search(p,q)),None)
    note=""
    missing=False
    task_section=index.task_class(q)
    purpose=next((label for pattern,label in PURPOSES if re.search(pattern,q)),None)
    question=bool(task_section or QUESTION.search(q) or purpose or HELP.search(q) or any(w.endswith(("ть","ться")) for w in words(q)))
    hint=purpose or hint
    if hardware and not bare and q.startswith("по для "):hint="серверное ПО" if hardware=="сервер" else "операционные системы"
    ids=index.products(q,domain="hardware" if bare else "software" if hardware else None,fuzzy=False,segment=profile.segment)
    section=req.category or server_section or explicit_class or index.class_match(base) or index.class_match(q)
    vendor,combined=vendor_class(index,base)
    if not combined:vendor,combined=vendor_class(index,q)
    vendor=supplier or vendor
    section=combined or section
    if supplier and not section:
        supplier_ids=[cid for cid in ids if index.card_vendors[cid]==supplier]
        if supplier_ids:
            ids=supplier_ids
            bare=question=False
            hint=None
    license_filter=license_request(engine,norm)
    license_hits=index.license_offers.get(license_filter,{})
    if license_filter:
        ids=sorted(license_hits,key=index.quality.get,reverse=True)
        section=vendor=device=None
        hint=hardware=None
        bare=question=False
        if not ids:
            note="В фиде нет предложений с такими подтверждёнными условиями лицензирования."
    if q=="офисные пакеты" and not section:
        section=next((k for k,v in index.class_names.items() if q in v),None)
    if hint and q in ("антивирус","антивирусы"):
        section=index.class_by_name.get(hint) or section
    if not section and HOME.search(q) and "антивир" in q:
        section=index.class_by_name.get("антивирусы для дома")
    repaired_kind=None
    if literal[0] and not section and not bare and not license_filter and not ids:
        ids,q,repaired_kind=literal
        question=False
        hint=None
    if not license_filter and not ids and not section and not bare and not question and not req.verbatim and not unknown_name:
        sounds,corrected=index.sound_products(q)
        if not sounds and q!=base:sounds,corrected=index.sound_products(base)
        if sounds and not feed_guard.is_destructive_repair(index,base,corrected,sounds,kind="sound"):
            ids,q=sounds,corrected
    if not ids and not section and not bare and not license_filter and not req.verbatim and not (question or hint or unknown_name):
        recovered,spelling,repaired_kind=index.recovery.lookup(engine,base)
        if recovered and not feed_guard.is_destructive_repair(index,base,spelling,recovered,kind=repaired_kind):
            ids,q=recovered,spelling
        elif recovered:
            repaired_kind=None
    if not repaired_kind and not section and not bare and not req.verbatim and base in index.slang and (not ids or index.slang[base][0] in {"vendors","families"}):
        field,ids=index.slang[base]
        if field=="classes" and not section:
            section=index.cat.cards[ids[0]].offers[0].class_id
    qualified=None
    class_alias=frozenset(words(base)) in index.section_phrases
    if acronym and not license_filter and not class_alias:
        # Явные версия и редакция продолжают определять порядок внутри семейства.
        family=set(acronym)
        ids=[cid for cid in ids if cid in family] or acronym
        section=server_section=hint=device=role=None
        bare=question=False
    from kuznitsa.understand.audience import audience as buyer_audience,PURPOSE
    if not section and not acronym and buyer_audience(norm)=="micro_office":
        brand=parts[0]
        field,brand_ids=index.slang.get(brand,(None,()))
        vid=index.vendor_names.get(brand)
        pool=index.tags["vendors"].get(brand)
        if not pool and vid:pool=index.cat.by["vendor"].get(vid,())
        if not pool and field=="vendors":pool=brand_ids
        if pool:
            fitting=[cid for cid in pool if re.search(PURPOSE["micro_office"],normalize(index.cat.cards[cid].title))]
            if fitting:
                ids=sorted(fitting,key=lambda cid:(len(index.cat.cards[cid].title),cid))
                question=False
                hint=None
                note="Линейка производителя для малого офиса."
    if not (bare or section or req.verbatim or unknown_name) and (not ids or question):
        qualified=product_context(engine,base)
        if qualified:
            ids,conditions=qualified
            question=False
            hint=None
            note="Варианты указанного продукта с учётом назначения."
    resolved_from_feed=False
    if not (ids or section or bare or license_filter or edition or req.verbatim or absent_acronym or question or hint):
        resolved=feed_guard.resolve_feed_product(engine,base,segment=profile.segment)
        if resolved:
            ids,q,resolved_note=resolved
            if resolved_note and not note:note=resolved_note
            unknown_name=False
            identity_pool=None
            resolved_from_feed=True
    if edition:
        ids,q,note=edition.cards,edition.query,edition.note
        section=server_section=hint=role=device=qualified=absent_acronym=identity_pool=vendor=None
        bare=question=False
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
    focus=()
    preferred=dict(license_hits)
    if not section and not req.category and not absent_acronym and not unknown_name and (question or hint and not ids):
        options,focus,preferred,note=task_sections(engine,q,hint)
        section=options[0] if options else None
        if options and req.mode=="smart" and engine.decisions and len(options)>1:
            model_section=index.decide(engine,q,options,sid,req,calls,focus)
            section=model_section or section
    replacement=index.replacements.get(norm) or index.replacements.get(q)
    unsold=index.unsold_sections.get(q)
    unsupported=False
    if identity_pool is not None and not (section or bare or license_filter or absent_acronym):
        ids=[cid for cid in ids if cid in identity_pool]
        unsupported=not ids
        if unsupported:
            q=original_subject
            unsold=index.unsold_sections.get(q)
    # Упоминание чужой марки в названии модуля не подтверждает продажу самой программы.
    if ids and not edition and not resolved_from_feed and not qualified and not section and (replacement or q in index.unsold_brands):
        named=tuple(cid for cid in ids if sold_as(index.cat.cards[cid],q))
        if named:ids=named
        elif replacement or q in index.unsold_brands:
            ids=()
            parents=index.unsold_brands.get(q)
            if parents and not unsold:
                unsold=max(dict.fromkeys(parents),key=parents.count)
    if not ids and not (section or bare or license_filter or edition or req.verbatim or absent_acronym or question or hint):
        resolved=feed_guard.resolve_feed_product(engine,base,segment=profile.segment)
        if resolved:
            ids,q,resolved_note=resolved
            if resolved_note and not note:note=resolved_note
            unknown_name=False
            unsupported=False
            identity_pool=None
            resolved_from_feed=True
    if ids and not section:
        ids=feed_guard.prefer_suite_for_office_year(index,q,ids)
        ids=feed_guard.prefer_software_over_courses(index,q,ids)
    role_reasons={}
    vendor_gap=False
    if supplier and ids and not section:
        confirmed=[cid for cid in ids if index.card_vendors[cid]==supplier]
        if confirmed:
            ids=confirmed
        else:
            # Издатель в условии обязателен и после исправления названия.
            section=index.card_sections[ids[0]]
            vendor=supplier
    if section and vendor and not req.category:
        section=resolve_hardware_section(index,q,section,vendor)
    if absent_acronym:
        name,vendor=absent_acronym
        section=None
        ids=sorted(index.language.vendor_cards[vendor],key=index.quality.get,reverse=True)
        note=f"Отдельной лицензии «{name}» в каталоге нет. Ниже другие продукты производителя."
        missing=True
    elif section:
        members=index.groups[section]
        if qty and not vendor:
            members=sorted(members,key=index.browse_quality.get,reverse=True)
        if server_section:
            members=sorted(members,key=lambda cid:index.server_offers.get(cid,(0,None))[0],reverse=True)
            for cid in members:
                if cid in index.server_offers:preferred[cid]=index.server_offers[cid][1]
            note=("Сначала лицензии на сервер и предложения с указанием сервера в названии."
                  if preferred else "Класс ПО найден. Серверное исполнение нужно уточнить у поставщика.")
        if vendor:
            matches=[cid for cid in members if index.card_vendors[cid]==vendor]
            if not matches and not req.category and index.cat.cards[members[0]].offers[0].domain=="hardware":
                software=software_for_class(engine,vendor,index.classes[section])
                if software:
                    section=index.card_sections[software[0]]
                    matches=[cid for cid in software if index.card_sections[cid]==section]
                    note="Программы этого издателя для указанной задачи."
            vendor_gap=not matches
            if vendor_gap:
                options=index.language.vendor_cards[vendor]
                root=index.cat.cards[members[0]].offers[0]
                label=index.classes[section]
                nearby=index.sections(label)
                similarity=index.tree.similarity(index.cat.dense.encode(label),options) if index.tree.matrix is not None else {}
                class_terms=index.class_terms[section]
                def closeness(cid):
                    other=index.cat.cards[cid].offers[0]
                    key=index.card_sections[cid]
                    return (other.domain==root.domain,other.category_path[:1]==root.category_path[:1],
                            len(nearby)-nearby.index(key) if key in nearby else 0,
                            len(class_terms & index.terms[cid]),similarity.get(cid,0.),index.quality[cid])
                members=sorted(options,key=closeness,reverse=True)

            else:
                members=matches
                if supplier and buyer_audience(norm)=="business":
                    purpose=set(words(norm))|{"business","бизнес"}
                    if "офис" in purpose:purpose.add("office")
                    members=sorted(members,key=lambda cid:len(set(words(index.cat.cards[cid].title)) & purpose),
                                   reverse=True)
        if not vendor_gap:
            members=rank_hardware_section(index,section,q,members)
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
    elif not ids and not license_filter:
        safe_row=None if (row and row.get("in_catalog")) else row
        if (replacement or not qty and not renewal and not any(t in engine.catalog.source_codes for t in (norm,base))
                and (unsold or unsupported or re.fullmatch(r"[a-z][a-z0-9.-]*(?: [a-z0-9.-]+)+",q)
                     or re.fullmatch(r"[A-Z][A-Za-z]{3,}",req.q.strip()) and re.search("[aeiou]",q))):
            known=unsold or (index.unsold_sections.get(" ".join(identity)) if identity else None)
            return feed_analogs.search(engine,req,profile,trace,priorities,record,
                                      cond.raw_for_analogs if cond.platform else original_subject,
                                      known=known,row=safe_row,qty=qty,budget=budget)
        if not qty and not renewal and not any(t in engine.catalog.source_codes for t in (norm,base)) and feed_guard.is_plausible_absent_brand(req.q,base):
            missing_note=f"«{req.q.strip()}» в каталоге нет."
            result=feed_guard.build_garbage_result(
                engine,req,profile,trace,norm,zero_reason="not_in_catalog",intent="out_of_catalog",
                note=missing_note,
                missing_block=dict(type="not_in_catalog",title="Нет в каталоге",reason="not_in_catalog",text=missing_note),
            )
            return finish(engine,req,trace,record,result,[],0,[],profile=profile)
        return None
    elif not edition and base==original_subject and not acronym and not renewal and not repaired_kind and not qualified and len(ids)>1 and len(words(q))>1 and all(w in words(index.cat.cards[ids[0]].title) for w in words(q)):
        # Семейство с несколькими редакциями в одном разделе и общим брендом.
        variants=[index.cat.cards[i] for i in ids[:8]]
        if (len(variants)>=3 and len({c.vendor for c in variants})==1
                and len({c.offers[0].class_id for c in variants})==1
                and all(words(c.title)[:len(words(q))]==words(q) and words(c.title)!=words(q) for c in variants)):
            section=variants[0].offers[0].class_id
    intent="out_of_catalog" if missing else "category" if section else "product"
    selections={}
    budget_relaxed=False
    constraints={"price_max":budget} if budget is not None else {}
    if qualified and conditions:
        selections=matching_variants(index,ids,profile,qty,renewal,conditions|constraints)
        if selections:ids=list(selections)
        else:note="Линейка найдена. Условия лицензирования для этого назначения нужно уточнить."
    if ids and (qty or renewal) and not selections:
        nodes=bool(re.search(r"\bуз(?:ел|л\w*)\b",norm))
        selections=matching_variants(index,ids,profile,qty,renewal,constraints,nodes=nodes)
        if (qty and not selections and section and not (req.category or server_section or vendor_gap)
                and frozenset(words(base)) not in index.section_phrases and not index.language.qualified_class(index,base)
                and class_words(base) not in index.class_aliases):
            for other in index.matching_sections(q):
                if other==section:continue
                candidates=[cid for cid in index.groups[other] if not vendor or index.card_vendors[cid]==vendor]
                selections=matching_variants(index,candidates,profile,qty,renewal,constraints,nodes=nodes)
                if selections:
                    section=other
                    ids=candidates
                    break
        if selections:
            # В широком классе оставляем порядок популярных линеек. Наличие
            # цены у отдельной ступени не делает редкий продукт основным.
            ordered=list(selections) if section else sorted(selections,key=lambda cid:selections[cid][0].price is None)
            if qty and section and budget is None and not renewal:
                others=[cid for cid in ids if cid not in selections and (vendor_gap or index.card_sections[cid]==section)]
                if others:
                    note="Тираж учтён при подборе лицензий. Варианты без подтверждения количества отмечены отдельно."
                ordered.extend(others)
                if not vendor:
                    ordered.sort(key=lambda cid:(index.browse_quality[cid][0],cid in selections),reverse=True)
            ids=ordered
            if renewal:intent="renewal"
        elif budget is not None:
            if soft_budget or (not section and req.filters.get("price_max") is None):
                ids=sorted(ids,key=lambda cid:(min((o.price for o in index.cat.cards[cid].offers if o.price),default=float("inf")),cid))
                note=f"Предложений дешевле {budget:g} ₽ нет. Показаны самые доступные варианты линейки."
                budget_relaxed=True
            else:
                ids=[]
                note="В указанном бюджете предложений с подтверждённой ценой нет."
        elif qty and not renewal:
            note="Товары найдены. В фиде нет лицензии с подтверждёнными условиями на указанное количество."
        else:
            note="Для выбранной линейки нет предложения с указанными условиями. Ниже близкие варианты."
            missing=True
            intent="out_of_catalog"
    if ids and (cond.active or cond.price_min is not None or cond.price_max is not None):
        ids,section,note,_=feed_conditions.apply_conditions(
            engine,req,profile,cond,ids,section,preferred,selections,qty,renewal,note)
    title=index.classes.get(section) or TITLES[intent]
    if vendor_gap:
        gap=f"В разделе «{index.classes[section]}» товаров этого производителя нет."
        note=" ".join(filter(None,(gap,note)))
        if ids:
            vendor_name=index.cat.cards[ids[0]].offers[0].vendor
            title=f"Ближайшие товары производителя {vendor_name}"
    trace.add("retrieve","Поиск по фиду",title,candidates=len(ids))
    if question:trace.add("intent","Выбор раздела",title,calls=calls)
    start=(req.page-1)*req.page_size
    items=[display(engine,c,profile,preferred.get(c),selections.get(c)) for c in ids[start:start+req.page_size]]
    for i,c in enumerate(items,1):
        c["position"]=i
        if qty and c["card_id"] not in selections and not renewal:
            c["badges"].append(dict(kind="quantity",label="Тираж требует уточнения"))
            c["score"]["why"].append("Количество по этой лицензии требует уточнения у поставщика")
        if vendor_gap:
            c.update(fill=True,label="Другой раздел этого производителя")
            c["score"]["why"].append(note)
        c["score"]["why"].extend(role_reasons.get(c["card_id"],()))
    merch=order(engine,req,profile,trace,priorities,intent,section,items)
    if merch is None:return None
    items=merch["cards"]
    if cond.sort in ("price_asc","price_desc") and items:
        rev=cond.sort=="price_desc"
        items.sort(key=lambda c:(c.get("price_from") is None,(-c["price_from"] if rev else c["price_from"]) if c.get("price_from") is not None else 0.0))
    main=[c["card_id"] for c in items]
    clarify=[]
    nearby=[]
    def complete(reserved):
        if license_filter or (budget is not None and not budget_relaxed) or cond.price_min is not None or cond.sort or cond.exclude_vendors or cond.exclude_terms or cond.origin or req.page!=1:return []
        if edition:
            anchor=index.card_sections[edition.cards[0]]
            shown=set(main)|set(reserved)
            extra=[]
            for cid in dict.fromkeys([*edition.neighbors,*index.groups[anchor]]):
                if len(main)+len(extra)>=4:break
                if cid in shown:continue
                card=display(engine,cid,profile)
                card.update(fill=True,label="Близкие варианты продукта" if cid in edition.neighbors else "Другие товары этого раздела")
                extra.append(card)
            return extra
        extra=fill(engine,items,profile,reserved=reserved,q=req.q,blocks=clarify)
        if intent=="renewal":
            nearby.extend(extra)
            return []
        return extra
    together,recommended=recommend(engine,edition.query if edition else norm,items,profile,intent,role=role,complete=complete,price_max=None if budget_relaxed else budget,edition_audience=edition.audience if edition else None)
    for i,c in enumerate(items,1):c["position"]=i
    blocks=[dict(type="products",title=title,category_id=section,total=len(ids),items=items)]
    if missing:
        blocks=[dict(type="not_in_catalog",title="Нет в каталоге",reason="gap",text=note),
                dict(type="analogs",title="Доступные замены",items=[dict(card=c,reason=note if not c.get("fill") else c["label"]) for c in items])]
        if absent_acronym:
            blocks[1]=dict(type="products",title="Другие продукты производителя",items=items,total=len(ids))
    blocks.extend(clarify)
    if nearby:
        blocks.append(dict(type="products",title="Другие товары из близких разделов",items=nearby,total=len(nearby)))
    if together:blocks.append(together)
    trace.add("upsell","Сопутствующие товары",f"В основной ленте · {sum(c.get('kind')=='upsell' for c in items)}. "
              f"В блоке рекомендаций · {len(together['items']) if together else 0}",status="ok" if recommended else "skip")
    chips=[dict(key="role",label="Роль: "+role["title"],removable=False)] if role else []
    if server_section:
        chips.append(dict(key="platform",label="ПО для сервера",removable=False))
    if bare:
        targets=[str(k) for k in (device or {}).get("software_classes",()) if str(k) in index.groups]
        label=(device or {}).get("prompt") or f"Искали ПО для {HARDWARE.get(hardware,norm)}?"
        next_query=index.classes[targets[0]] if targets else f"ПО для {HARDWARE.get(hardware,norm)}"
        apply={"q":next_query}
        if targets:apply["category"]=targets[0]
        chips.append(dict(key="domain",label=label,q=next_query,apply=apply,software_classes=targets,removable=False))
    changes=[{"from":norm,"to":q,"kind":repaired_kind or "catalog"}] if base!=q or (base!=original_subject and not (noise_clean and noise_clean.changed)) else []
    result=dict(search_id=sid,engine="kuznitsa",engine_version="1.0",mode=req.mode,query=dict(raw=req.q,normalized=norm,corrected=q,corrections=changes,did_you_mean=None),
        understood=dict(intent=intent,intent_title=TITLES[intent],intent_conf=.9,intent_source="jev" if model_section else "rules",filters=dict(category=[section]) if section else {},
        exclude={},qty=qty,entities=[],chips=chips,zero_reason="not_in_catalog" if missing else None,agent_note=note or title),blocks=blocks,facets=[],notes=[],banners=merch["banners"],relax_hints=[],related_queries=[],
        profile=profile_info(profile),cost=cost_summary(calls,engine.usd_rub),trace=trace.steps,timing_ms={})
    if edition and edition.audience:result["understood"]["filters"]["audience"]=edition.audience
    if qualified and selections:result["understood"]["filters"].update(conditions)
    if vendor:result["understood"]["filters"]["vendor"]=[vendor]
    if license_filter:result["understood"]["filters"][license_filter[0]]=license_filter[1]
    feed_conditions.populate_result(cond,result,chips)
    if budget is not None and not ids:result["understood"]["zero_reason"]="filters_too_strict"
    if renewal:result["understood"]["filters"]["action"]="renewal"
    if noise_clean and noise_clean.changed:
        for k,v in noise_clean.filters.items():
            result["understood"]["filters"].setdefault(k,v)
        seen_chips={c.get("key") for c in chips}
        for chip in noise_clean.chips:
            if chip.get("key") not in seen_chips:
                chips.append(chip)
    if qty:
        chips.append(dict(key="quantity",label=f"Количество · {qty['value']}"))
    return finish(engine,req,trace,record,result,items,len(main),calls,profile=profile)


def order(engine,req,profile,trace,priorities,intent,section,items):
    ctx=dict(q_raw=req.q,q_norm=normalize(req.q),intent=intent,category_id=section,segment=profile.segment,
             profile_id=profile.client_id,mode=req.mode,channel=req.source,region=profile.region)
    if engine.controls.redirect(ctx):return None
    from kuznitsa.rank.priorities import apply
    applied,moves=apply(items,priorities,ctx,engine.catalog,engine.clock())
    trace.add("business","Порядок карточек","Совпадение названия, наличие и условия поставки",priorities=applied,moves=moves)
    return engine.controls.merch(ctx,items)


def finish(engine,req,trace,record,result,items,count,calls,profile=None):
    from .response_guard import guard
    guard(engine,req,result)
    if engine.catalog.is_feed:
        if profile is None:
            profile=engine.clients["guest" if "profile" in req.ignore else req.profile_id]
        feed_guard.verify_response(engine,req,profile,result,from_legacy=False)
    if calls and not calls[-1].get("ok"):
        result["mode"]="fast"
        result["notes"].append("Раздел выбран быстрым поиском: категоризатор недоступен.")
    result["timing_ms"]["total"]=round(1000*(engine.timer()-trace.start),2)
    if record:
        if engine.sessions:engine.sessions.save(req,result,items)
        engine.journal.search(engine.clock(),req,result,count,result["understood"]["zero_reason"],False)
    if not req.explain:result["trace"]=[]
    return result


def suggestions(engine,raw,norm,profile,start):
    from time import perf_counter
    index=engine.catalog.feed
    groups=[]
    corrected=norm
    def entry(cid,preferred=None):
        c=display(engine,cid,profile,preferred)
        return dict(text=c["title"],kind="product",meta=cid,card_id=cid,picture=c["picture"],image=c["picture"],
                    oldprice=c["offer"]["oldprice"],price=c["offer"]["price"],price_on_request=c["offer"]["price_on_request"],badges=c["badges"],q=c["title"])
    if norm in {"про","pro"}:
        return dict(q=raw,corrected=None,groups=[],ms=round((perf_counter()-start)*1000,2))
    edition=index.edition(norm)
    row=index.analogs.lookup(norm)
    if not edition and row and not row["in_catalog"]:
        sections,seeds=feed_analogs.row_candidates(index,row)
        choices=feed_analogs.choose(index,norm,row,sections,seeds,[],False)
        if choices:
            groups.append(dict(type="analogs",title="Аналоги в каталоге",items=[entry(cid) for cid,_ in choices[:3]]))
        return dict(q=raw,corrected=None,groups=groups,ms=round((perf_counter()-start)*1000,2))
    if len(norm)>=2:
        license_filter=license_request(engine,norm)
        license_hits=index.license_offers.get(license_filter,{})
        device=index.hardware.get(hardware_head(index,norm),{})
        hw=next((str(k) for k in device.get("hardware_feed_classes",[]) if str(k) in index.groups),None)
        section=hw or index.class_by_name.get(norm) or index.class_match(norm)
        known=bool(section or norm in index.slang or norm in index.vendor_names or norm in index.aliases)
        mapped,_=engine._phrases.apply(norm)
        query=index.correct(mapped)
        hint=next((label for pattern,label in (*PURPOSES,*TASKS) if re.search(pattern,query)),None)
        task=index.task_class(query) or hint or HELP.search(query) or QUESTION.search(query) or any(w.endswith(("ть","ться")) for w in words(query))
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
        if edition:
            ids=list(edition.cards[:4])
            known=True
        elif license_filter:
            ids=sorted(license_hits,key=index.quality.get,reverse=True)[:4]
            known=True
        elif section:
            sol=index.solutions.match(query)
            ids=list(dict.fromkeys([*(focus if sol else (i for i in focus if index.card_sections[i]==section)),*index.groups[section]]))[:4]
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
        if ids:
            groups.append(dict(type="products",title="Товары",items=[entry(i,license_hits.get(i)) for i in ids]))
        sections=list(dict.fromkeys(index.card_sections[i] for i in ids))
        matching=[(k,index.classes[k]) for k in sections[:3]]
        if matching:
            groups.append(dict(type="categories",title="Разделы",items=[dict(text=v,q=v,meta=k,kind="category") for k,v in matching]))
        previous=engine.suggestions.prefix(norm,profile.segment,set())
        groups.extend(g for g in previous if g["type"]=="queries")
        picks=index.recommend.picks(engine.journal,edition.query if edition else norm,ids,2,edition_audience=edition.audience if edition else None)
        if picks:
            groups.append(dict(type="upsell",title="Возможно, вам понадобится",items=[
                dict(entry(cid,index.recommend.target_offer(cid,rule["offer"]["audience"]) if rule["offer"].get("audience") else None),
                     reason=rule["reason"],rule_id=rule["id"]) for cid,rule in picks]))
    return dict(q=raw,corrected=corrected if corrected!=norm else None,groups=groups,ms=round((perf_counter()-start)*1000,2))
