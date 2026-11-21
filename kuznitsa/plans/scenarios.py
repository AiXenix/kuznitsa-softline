import re
from .knowledge import GROUPS
from kuznitsa.config import WEIGHTS
from kuznitsa.rank.business import ranked
from kuznitsa.rank.variants import public_offer,select


def entity(entities,kind):
    return next((e["id"] for e in entities if e["type"]==kind),None)


def reference(engine,kind,text,entities):
    fid=entity(entities,kind)
    if not fid:
        near=engine.knowledge.nearest(kind,text)
        fid=near[0] if near else None
    return engine.kb.rows[GROUPS[kind]].get(fid,{})


def spec_lines(raw):
    if re.search(r"(?:расчет|рассчитать|подбор) кп",raw,re.I) and " и " in raw:
        lines=re.split(r"\s+и\s+",re.sub(r"^.*?\bкп\s*", "",raw,flags=re.I))
        seats=re.search(r"\d+\s+рабочих мест",raw,re.I)
        if seats:
            lines=[line if seats[0] in line else line+" "+seats[0] for line in lines]
    elif re.search(r"[;\n]",raw):
        lines=re.split(r"[;\n]+",raw)
    elif len(re.findall(r"\d+\s*(?:шт|пк|узл|мест|лиценз)",raw,re.I))>=2:
        lines=raw.split(",")
    else:
        # Одна позиция ТЗ с несколькими требованиями через запятую.
        lines=[raw]
    return [re.sub(r"^\s*(?:[-•]|\d+[.)])\s*","",s).strip() for s in lines
            if s.strip() and not re.search("добрый день|прошу выставить|выставьте счет",s,re.I)]


def scope(engine,intent,f,entities,text,profile,qty):
    """Выбрать товары по связям KB. None передаёт выбор общему гибридному поиску."""
    c=engine.catalog
    def ids(k,values,score):
        return {cid:score for v in values for cid in c.by[k].get(v,())}
    if intent in ("spec_list","account","off_topic"):
        return {}
    if intent in ("role_kit","industry","task","question"):
        kind={"role_kit":"role","industry":"industry","task":"use_case","question":"faq"}[intent]
        row=reference(engine,kind,text,entities)
        result={}
        for slot in row.get("slots",[row]):
            cats=slot.get("categories",[]) + slot.get("related_categories",[])+([slot["category"]] if slot.get("category") else [])
            families=ids("family",slot.get("families",[])+slot.get("related_families",[]),.85)
            if not families or kind not in ("role","industry"):
                result.update(ids("category",cats,.65))
            result.update(families)
        links=engine.kb.import_links.get(GROUPS[kind],{})
        result.update(ids("family",links.get(row.get("id"),[]),.85))
        if intent=="question":
            explicit=ids("family",f.get("family",[]),.98) or ids("vendor",f.get("vendor",[]),.96)
            return explicit or result
        return result or None
    if intent=="product" and re.search(r"с техподдержкой|коммерческ\w+ верси",text):
        name=text.split()[0]
        related=[r for r in engine.kb.rows["families"].values() if name in r.get("summary","").lower().split()]
        if related:
            from collections import Counter
            category=Counter(r.get("category") for r in related).most_common(1)[0][0]
            f["category"]=[category]
            return ids("family",[r["id"] for r in related if r.get("category")==category],.85) or ids("category",[category],.57)
    if intent=="analog":
        source=f.get("family",[]) or [fid for fid,r in engine.kb.rows["families"].items() if r.get("vendor") in f.get("vendor",[])]
        result={}
        for fid in source:
            row=engine.kb.rows["families"].get(fid,{})
            result.update(ids("category",[row.get("category")],.55))
            analogs=row.get("analogs",[])+[v["family"] for v in engine.kb.rows["analogs"].get(fid,{}).get("russian_analogs",[])]
            result.update(ids("family",analogs+engine.kb.import_links["analogs"].get(fid,[]),.85))
        for cid in ids("family",source,1):
            result.pop(cid,None)
        return result or ids("category",f.get("category",[]),.7)
    if intent=="compare":
        return {**ids("category",f.get("category",[]),.7),**ids("vendor",f.get("vendor",[]),.65),**ids("family",f.get("family",[]),.9)}
    if intent=="promo" and not any(f.get(k) for k in ("family","vendor","category")):
        return {cid:.65 for cid,card in c.cards.items() if any(o.attrs.get("promo")=="true" for o in card.offers)}
    if intent=="service":
        training=bool(re.search("курсы|обучени",text))
        security=training and "безопасност" in text
        services=ids("category",["security_awareness" if security else "it_training_courses" if training else "tech_support"],.72)
        vendors=set(f.get("vendor",[]))|{r.get("vendor") for fid in f.get("family",[]) if (r:=engine.kb.rows["families"].get(fid))}
        return {cid:(.98 if c.cards[cid].vendor in vendors else score) for cid,score in services.items()}
    return None


def compose(engine,intent,req,f,entities,qty,cards,profile,blocks,run_line,reason):
    by_type=lambda key: [b for b in blocks if b["type"]==key]
    def options(row):
        by_family=[c for c in cards if engine.catalog.cards[c["card_id"]].family in row.get("families",[])]
        priority={fid:i for i,fid in enumerate(row.get("families",[]))}
        by_family.sort(key=lambda c:priority[engine.catalog.cards[c["card_id"]].family])
        imported=[c for c in cards if c["category"]["id"]==row.get("category") and engine.catalog.cards[c["card_id"]].family in imported_matches and c not in by_family]
        return by_family+imported or [c for c in cards if c["category"]["id"]==row.get("category")]
    if intent=="account":
        items=[]
        for p in sorted(profile.owned,key=lambda p:p.get("expires_in_days") if p.get("expires_in_days") is not None else float("inf")):
            renewal=None
            if p.get("card_id") in engine.catalog.cards and p.get("expires_in_days") is not None:
                found=select(engine.catalog.cards[p["card_id"]],profile,{"action":"renewal"},{},dict(value=p["qty"]) if p.get("qty") else None)
                renewal=public_offer(found[0]) if found else None
            title=p.get("product") or engine.names["family"].get(p.get("family_id"),"Лицензия")
            items.append(dict(title=title,qty=p.get("qty"),expires_in_days=p.get("expires_in_days"),renew_offer=renewal))
        result=[dict(type="my_licenses",title="Лицензии организации",items=items)] if items else [dict(type="clarify",title="Личный кабинет",question="Выберите профиль организации, чтобы посмотреть покупки.",options=[])]
        if re.search("заказ",req.q,re.I) and not profile.orders:
            result.insert(0,dict(type="answer",title="История заказов",text="У выбранного профиля пока нет заказов.",source="profile",links=[]))
        if re.search("заказ",req.q,re.I) and profile.orders:
            last=max(profile.orders,key=lambda o:o.get("date",""))
            result.insert(0,dict(type="answer",title="Заказы организации",text=f"Заказов в истории: {len(profile.orders)}. Дата последнего заказа: {last.get('date','не указана')}.",source="profile",links=[]))
        if re.search("повтор",req.q,re.I):
            for order in sorted(profile.orders,key=lambda v:v.get("date",""),reverse=True):
                items=[]
                for line in order.get("items",[]):
                    o=engine.catalog.offers_by_id.get(line.get("offer_id"))
                    if not o or f.get("category") and o.category_id not in f["category"]:continue
                    product=engine.catalog.cards[o.card_id]
                    quantity={"value":line["qty"]} if line.get("qty") else None
                    selection=select(product,profile,{}, {},quantity,exact=o)
                    card=ranked(product,selection,1.,True,profile,WEIGHTS,engine.kb)
                    card["action"]={"type":"repeat_order","label":"Повторить","order_id":order.get("order_id")}
                    card["position"]=len(items)+1
                    items.append(card)
                if items:
                    result.insert(0,dict(type="products",title="Повторить прошлый заказ",action="repeat_order",order_id=order.get("order_id"),items=items,total=len(items)))
                    break
        return result
    if intent=="spec_list":
        lines=[]
        for i,raw in enumerate(spec_lines(req.q),1):
            r=run_line(raw)
            matches=[c for b in r["blocks"] if b["type"]=="products" for c in b["items"]]
            card=matches[0] if matches else None
            calc=(card or {}).get("calc") or {}
            lines.append(dict(n=i,raw=raw,understood=r["understood"],status="matched" if card else "not_found",card=card,
                              qty=(r["understood"]["qty"] or {}).get("value"),unit_price=calc.get("unit_price"),total=calc.get("total"),alternatives=matches[1:3]))
        return [dict(type="spec",title="Подбор по спецификации",lines=lines,total=sum(x["total"] for x in lines) if lines and all(x["total"] is not None for x in lines) else None,unresolved=[x["n"] for x in lines if not x["card"]])]
    if intent in ("role_kit","industry"):
        row=reference(engine,"role" if intent=="role_kit" else "industry",req.q,entities)
        group="roles" if intent=="role_kit" else "industries"
        imported_matches=engine.kb.import_links[group].get(row.get("id"),[])
        parent=engine.kb.rows[group].get(row.get("parent"))
        parent_field={"parent":dict(id=parent["id"],title=parent["title"],q=parent["title"])} if parent else {}
        industry_families={fid for e in entities if e["type"]=="industry" and intent=="role_kit"
                           for slot in engine.kb.rows["industries"].get(e["id"],{}).get("slots",[])
                           for fid in slot.get("families",[])}
        slots=[]
        for spec in row.get("slots",[]):
            found=options(spec)
            if industry_families:
                found.sort(key=lambda c:engine.catalog.cards[c["card_id"]].family not in industry_families)
            if qty:
                found=sorted(found,key=lambda c:(
                    (c.get("calc") or {}).get("total") is None,
                    c["offer"]["metric"] not in ("user","device","company","concurrent","mailbox"),
                    not c["offer"]["available"]))
            slots.append(dict(title=engine.names["category"].get(spec.get("category"),"Программное обеспечение"),must=spec.get("must",False),
                              card=found[0] if found else None,alternatives=found[1:3],note=spec.get("note","")))
        if slots:
            totals=[((s["card"] or {}).get("calc") or {}).get("total") for s in slots if s["must"] or s["card"]]
            return [dict(**parent_field,type="kit",title=row.get("title","Комплект программ"),role=row["id"],seats=(qty or {}).get("value"),
                         slots=slots,total=sum(totals) if totals and all(v is not None for v in totals) else None)]
    if intent=="compare":
        targets=f.get("family",[]) or f.get("vendor",[])
        columns=[]
        for target in targets:
            hit=next((c for c in cards if target in (engine.catalog.cards[c["card_id"]].family,c["vendor"]["id"])),None)
            if hit:
                if hit not in columns:
                    columns.append(hit)
        if len(f.get("edition",[]))>=2 and len(targets)==1:
            columns=[next((c for c in cards if engine.catalog.cards[c["card_id"]].offers[0].edition==ed),None) for ed in f["edition"]]
            columns=[c for c in columns if c]
        if len(columns)<2:
            columns=(columns+[c for c in cards if c not in columns])[:2]
        if columns:
            rows=[dict(title="Производитель",values=[c["vendor"]["name"] for c in columns]),dict(title="Цена от, ₽",values=[c["price_from"] for c in columns]),
                  dict(title="Срок, мес.",values=[c["offer"]["term_months"] for c in columns])]
            for label,key in [("В реестре ПО","registry"),("Сертификаты","certs"),("Платформы","platforms")]:
                values=[]
                for card in columns:
                    o=engine.catalog.offers_by_id[card["offer"]["offer_id"]]
                    v=getattr(o,key)
                    values.append(("Да" if v else "Нет") if isinstance(v,bool) else ", ".join(v) if v else "Нет сведений")
                rows.append(dict(title=label,values=values))
            return [dict(type="compare",title="Сравнение программ",columns=columns[:4],rows=[{**r,"values":r["values"][:4]} for r in rows])]
    if intent=="broad" and cards:
        from collections import Counter
        counts=Counter(c["vendor"]["id"] for c in cards)
        blocks.append(dict(type="vendors",title="Вендоры",items=[dict(id=k,title=engine.names["vendor"].get(k,k),count=n) for k,n in counts.most_common(6) if k]))
    if intent=="analog" and cards:
        src=", ".join(engine.names["family"].get(k,k) for k in f.get("family",[])) or req.q
        notes={a["family"]:a.get("note","Аналог из базы знаний") for fid in f.get("family",[])
               for a in engine.kb.rows["analogs"].get(fid,{}).get("russian_analogs",[])}
        return [dict(type="analogs",title="Варианты замены",source=dict(title=src,status="available" if any(engine.catalog.by["family"].get(k) for k in f.get("family",[])) else "unavailable",note=""),
                     items=[dict(card=c,note=notes.get(engine.catalog.cards[c["card_id"]].family,"Альтернатива по назначению")) for c in cards[:req.page_size]])]
    if intent=="question" or intent=="license_ops" and re.search("можно ли|разрешен",req.q,re.I):
        row=reference(engine,"faq",req.q,entities)
        if row and row["id"] in engine.knowledge.nearest("faq",req.q):
            return [dict(type="answer",title=row["questions"][0].capitalize(),text=row["answer"],source="faq:"+row["id"],links=[]),*by_type("products")]
    if intent=="compliance":
        row=engine.kb.rows["compliance"].get(entity(entities,"compliance"),{})
        return [dict(type="answer",title=row.get("title","Условия закупки"),text=row.get("explain") or "Проверены явно указанные характеристики предложений.",source="kb",links=[]),*blocks]
    if intent=="off_topic" and reason=="piracy":
        return [dict(type="answer",title="Лицензионные варианты",text="Подберём легальную лицензию или пробную редакцию. Укажите название программы.",source="catalog",links=[]),*by_type("categories")]
    if intent=="service" and cards and f.get("category")==["security_awareness"]:
        return by_type("products")
    if intent=="service" and cards:
        return [dict(type="services",title="Услуги и обучение",items=next((b["items"] for b in by_type("products")),[]))]
    if intent=="service":
        return [dict(type="answer",title="Подбор услуги",text="Готового предложения по заданным условиям нет. Запросите расчёт у специалиста.",source="catalog",links=[]),
                *by_type("lead")]
    if intent=="promo":
        # Льготное предложение подтверждается аудиторией SKU. Остальные цены остаются обычными.
        promos=[c for c in cards if any(b["kind"]=="promo" for b in c["badges"])]
        return ([dict(type="promo",title="Специальные предложения",items=[c for b in by_type("products") for c in b["items"] if c in promos])] if promos else
                [dict(type="answer",title="Специальные предложения",text="Подтверждённой акции в каталоге нет. Доступны стандартные условия покупки.",source="catalog",links=[])]+blocks)
    return blocks
