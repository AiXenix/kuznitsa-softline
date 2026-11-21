"""Быстрый подбор строки ведомости по артикулу, полному имени или текстовому индексу."""
import re
from kuznitsa.text import normalize, tokens
from kuznitsa.understand.normalize import lookup_skus
from kuznitsa.rank.variants import select
from kuznitsa.rank.business import ranked


supplier_pattern=re.compile(r"(.+?)\s*[,;]\s*(?:кол[- ]во\s*[:=]?\s*)?(\d{1,9})\s*(ед|шт|мест\w*|уз(?:ел|ла|лов)|устройств\w*|пк)[.]?",re.I)


# Структурная граница строки сохраняется до нормализации текста запроса.
csv_quantity=re.compile(r'([^;|\t\n]+?)\s*[,;|\t]\s*([1-9]\d{0,8})\s*')
lot_pattern=re.compile(r'(.+?)\s*[;|\t]\s*партия\s+([1-9]\d{0,8})\s*(?:рабочи[хе]\s+)?([\w.]+)',re.I)
standard_line=re.compile(r"(.*?)\s*(?:\[([^\[\]]+)\])?\s*[—–-]\s*(\d{1,9})\s*шт[.]?",re.I)
service_words=re.compile(r"поддержк|сопровожд|обучен|курс|установк|внедрен|support|training",re.I)


def structured_line(line):
    return (standard_line.fullmatch(line) or csv_quantity.fullmatch(line) or lot_pattern.fullmatch(line)
            or "/" in line and supplier_pattern.fullmatch(line))


def file_line(engine,line,profile,req,weights,inherited_filters):
    structured=supplier_pattern.fullmatch(line)
    if structured and "/" in structured[1]:
        return supplier_line(engine,structured[1],int(structured[2]),profile,req,weights,inherited_filters,structured[3])
    lot=lot_pattern.fullmatch(line)
    if lot:
        fields=[field.strip() for field in re.split(r"[;|\t]",lot[1])]
        if len(fields)==3:
            return supplier_line(engine," / ".join(fields),int(lot[2]),profile,req,weights,inherited_filters,lot[3],has_vendor=False)
    csv=csv_quantity.fullmatch(line)
    if csv:
        name=csv[1].strip().strip('"').replace('""','"')
        line=f"{name} — {csv[2]} шт"
    match=standard_line.fullmatch(line)
    if not match:return None
    name,article,n=match.groups()
    # Семейство и редакция определяются заново в каждой строке.
    filters={k:v for k,v in inherited_filters.items() if k in ("certs","platform","registry")}
    filters.update(req.filters)
    catalog=engine.catalog
    offer=catalog.offer_names.get(normalize(name))
    if article:
        choices=lookup_skus(catalog,article,quantity=int(n))
        # Общий код без однозначного названия не подтверждает товар для КП.
        if len(choices)>1:
            offer=choices.get(offer.card_id) if offer else None
        else:
            offer=next(iter(choices.values()),None)
    if offer and not offer.lic.pack and not (offer.lic.qty_min or 1)<=int(n)<=(offer.lic.qty_max or float("inf")):
        return dict(understood=dict(intent="sku",qty=dict(value=int(n),metric=offer.lic.metric),filters=filters),
                    blocks=[dict(type="products",items=[])])
    if article or offer:
        ids=[(offer.card_id,1.)] if offer else []
    else:
        scores=catalog.bm.scores(name)
        words=tokens(name)
        families={fid for start,end,matches in engine.lex.match(words) if start==0 and end==len(words)
                  for kind,fid,_ in matches if kind=="family"}
        scoped=set().union(*(catalog.by["family"].get(fid,()) for fid in families))
        ids=[(catalog.ids[i],max(.95,float(scores[i])) if scoped else float(scores[i])) for i in scores.argsort()[::-1]
             if (catalog.ids[i] in scoped if scoped else scores[i]>=.22)][:30]
    qty=dict(value=int(n),metric=offer.lic.metric if offer else None)
    main_license=not (article or offer or service_words.search(name))
    hits=[]
    for cid,score in ids:
        card=catalog.cards[cid]
        row_filters=filters
        if main_license:
            action="renewal" if re.search(r"продл|renew",name,re.I) else filters.get("action","new")
            if card.category in ("tech_support","it_training_courses") or service_words.search(card.title):
                continue
            if any(o.lic.action for o in card.offers):
                row_filters={**filters,"action":action}
        found=select(card,profile,row_filters,req.exclude,qty,offer)
        if found and main_license and found[0].kind in ("service","course"):
            continue
        if found:hits.append(ranked(card,found,score,bool(offer),profile,weights,engine.kb))
        if len(hits)==3:break
    for position,card in enumerate(hits,1):card["position"]=position
    return dict(understood=dict(intent="sku" if article else "product",qty=qty,filters=filters),
                blocks=[dict(type="products",items=hits)])


def field_key(value,field):
    text=normalize(str(value or ""))
    patterns=(("base",r"базов|basic|base"),("standard",r"стандарт|standard"),("pro",r"профессион|professional|^pro$")) if field=="edition" else (
        ("edu",r"образоват|академ|edu"),("gov",r"госучреж|государств|gov"),("crossgrade",r"миграц|переход|crossgrade"),
        ("renewal",r"продл|renew"),("new",r"новая|покупк|^new$"))
    return next((key for key,pattern in patterns if re.search(pattern,text)),text)


def matches_fields(offer,parts,name):
    series,edition,operation=parts
    supplied=offer.attrs
    return (series in (normalize(supplied.get("series","")),normalize(offer.family_name or "")) or
            not supplied.get("series") and series in name) and (
        field_key(edition,"edition")==field_key(supplied.get("edition") or offer.edition,"edition") or
        not supplied.get("edition") and edition in name) and (
        field_key(operation,"operation")==field_key(supplied.get("operation") or offer.lic.action,"operation") or
        field_key(operation,"operation")==offer.lic.audience or not supplied.get("operation") and operation in name)


def supplier_line(engine,text,count,profile,req,weights,inherited,unit="ед",has_vendor=True):
    parts=[normalize(s) for s in text.split("/") if s.strip()]
    vendor=parts[0]
    attributes=parts[1:] if has_vendor else parts
    from kuznitsa.ingest.source_fields import supplier_metric
    seat=unit.lower().startswith("мест")
    metric=None if seat else "device" if unit.lower().startswith(("уз","устройств","пк")) else supplier_metric(unit)
    qty=dict(value=count,metric=metric)
    filters={k:v for k,v in inherited.items() if k in ("certs","registry","platform")}
    filters.update(req.filters)
    hits=[]
    if has_vendor:
        candidates=engine.catalog.by["vendor"].get(engine.source_vendors.get(vendor),())
    else:
        candidates=engine.catalog.supplier.names.get(("family",parts[0]),set())
        if not candidates:
            candidates={cid for fid in engine.catalog.source_names.get(parts[0],()) for cid in engine.catalog.by["family"].get(fid,())}
    for cid in candidates:
        card=engine.catalog.cards[cid]
        for offer in card.offers:
            if metric and offer.lic.metric!=metric or seat and offer.lic.metric not in ("device","user","seat","concurrent"):
                continue
            name=normalize(offer.name)
            # Когда исполнение содержит косую черту, проверяем весь исходный фрагмент.
            match=matches_fields(offer,attributes,name) if len(attributes)==3 else all(s in name for s in attributes)
            if match and (offer.lic.qty_min or 1)<=count<=(offer.lic.qty_max or 10**10):
                chosen=select(card,profile,filters,req.exclude,qty,offer)
                if chosen:hits.append(ranked(card,chosen,1.,True,profile,weights,engine.kb))
                if chosen:break
    hits.sort(key=lambda c:(not c["offer"]["available"],-c["score"]["score"],c["card_id"]))
    for i,c in enumerate(hits,1):c["position"]=i
    return dict(understood=dict(intent="product",qty=qty,filters=filters),blocks=[dict(type="products",items=hits[:3])])
