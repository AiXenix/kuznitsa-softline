"""Быстрый подбор строки ведомости по артикулу, полному имени или текстовому индексу."""
import re
from kuznitsa.text import normalize
from kuznitsa.understand.normalize import lookup_skus
from kuznitsa.rank.variants import select
from kuznitsa.rank.business import ranked


supplier_pattern=re.compile(r"(.+?)\s*[,;]\s*(?:кол[- ]во\s*[:=]?\s*)?(\d{1,9})\s*(ед|шт|мест\w*|уз(?:ел|ла|лов)|устройств\w*|пк)[.]?",re.I)


def file_line(engine,line,profile,req,weights,inherited_filters):
    structured=supplier_pattern.fullmatch(line)
    if structured and "/" in structured[1]:
        return supplier_line(engine,structured[1],int(structured[2]),profile,req,weights,inherited_filters,structured[3])
    match=re.fullmatch(r"(.*?)\s*(?:\[([^\[\]]+)\])?\s*[—–-]\s*(\d{1,9})\s*шт[.]?",line,re.I)
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
        ids=[(catalog.ids[i],float(scores[i])) for i in scores.argsort()[::-1][:10] if scores[i]>=.22]
    qty=dict(value=int(n),metric=offer.lic.metric if offer else None)
    hits=[]
    for cid,score in ids:
        card=catalog.cards[cid]
        found=select(card,profile,filters,req.exclude,qty,offer)
        if found:hits.append(ranked(card,found,score,bool(offer),profile,weights,engine.kb))
        if len(hits)==3:break
    for position,card in enumerate(hits,1):card["position"]=position
    return dict(understood=dict(intent="sku" if article else "product",qty=qty,filters=filters),
                blocks=[dict(type="products",items=hits)])


def supplier_line(engine,text,count,profile,req,weights,inherited,unit="ед"):
    parts=[normalize(s) for s in text.split("/") if s.strip()]
    vendor=parts[0]
    attributes=parts[1:]
    device=unit.lower().startswith(("уз","устройств","пк"))
    seat=unit.lower().startswith("мест")
    qty=dict(value=count,metric="device" if device else None)
    filters={k:v for k,v in inherited.items() if k in ("certs","registry","platform")}
    filters.update(req.filters)
    hits=[]
    for cid in engine.catalog.by["vendor"].get(engine.source_vendors.get(vendor),()):
        card=engine.catalog.cards[cid]
        for offer in card.offers:
            if device and offer.lic.metric!="device" or seat and offer.lic.metric not in ("device","user","seat"):
                continue
            name=normalize(offer.name)
            # Когда исполнение содержит косую черту, проверяем весь исходный фрагмент.
            fields=("series","edition","operation")
            match=all(s==normalize(offer.attrs[field]) if offer.attrs.get(field) else s in name
                      for s,field in zip(attributes,fields)) if len(attributes)==3 else all(s in name for s in attributes)
            if not match and len(attributes)==3:
                series,edition,op=attributes
                operation=next((v for pattern,v in ((r"образоват|академ","edu"),(r"госучреж|государств","gov"),(r"миграц|переход","crossgrade")) if re.search(pattern,op)),None)
                match=bool(operation and operation in (offer.lic.audience,offer.lic.action) and
                           all(normalize(offer.attrs.get(k) or "")==v or v in name for k,v in (("series",series),("edition",edition))))
            if match and (offer.lic.qty_min or 1)<=count<=(offer.lic.qty_max or 10**10):
                chosen=select(card,profile,filters,req.exclude,qty,offer)
                if chosen:hits.append(ranked(card,chosen,1.,True,profile,weights,engine.kb))
                if chosen:break
    hits.sort(key=lambda c:(not c["offer"]["available"],-c["score"]["score"],c["card_id"]))
    for i,c in enumerate(hits,1):c["position"]=i
    return dict(understood=dict(intent="product",qty=qty,filters=filters),blocks=[dict(type="products",items=hits[:3])])
