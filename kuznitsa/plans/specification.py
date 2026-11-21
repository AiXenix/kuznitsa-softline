"""Быстрый подбор строки ведомости по артикулу, полному имени или текстовому индексу."""
import re
from kuznitsa.text import normalize
from kuznitsa.understand.normalize import lookup_skus
from kuznitsa.rank.variants import select
from kuznitsa.rank.business import ranked


def file_line(engine,line,profile,req,weights,inherited_filters):
    match=re.fullmatch(r"(.*?)\s*(?:\[([^\[\]]+)\])?\s*[—–-]\s*(\d{1,9})\s*шт[.]?",line,re.I)
    if not match:return None
    name,article,n=match.groups()
    # Семейство и редакция определяются заново в каждой строке.
    filters={k:v for k,v in inherited_filters.items() if k in ("certs","platform","registry")}
    filters.update(req.filters)
    catalog=engine.catalog
    offer=(next(iter(lookup_skus(catalog,article).values()),None) if article else
           catalog.offer_names.get(normalize(name)))
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
