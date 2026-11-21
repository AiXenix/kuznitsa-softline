"""Exact source-code lookup. Preserve punctuation and Unicode supplier codes."""
import json
from kuznitsa.text import normalize


def codes(offer):
    ids=getattr(offer,"source_ids",None) or offer.attrs.get("source_ids",[])
    if isinstance(ids,str):
        try:
            ids=json.loads(ids)
        except ValueError:
            ids=[]
    return [str(v) for v in ids] if isinstance(ids,list) else []


def install(catalog):
    sources={}
    for offer in catalog.offers_by_id.values():
        for code in codes(offer):
            key=normalize(code)
            if key:
                sources.setdefault(key,{}).setdefault(offer.offer_id,offer)
    catalog.source_offers={k:tuple(v.values()) for k,v in sources.items()}
    for key,offers in catalog.source_offers.items():
        # A shared card/parent code identifies a group. Start with its entry
        # variant. Never silently resolve an alias shared by unrelated families.
        if len({o.family_id or o.offer_id for o in offers})==1:
            catalog.offer_names.setdefault(key,min(offers,key=lambda o:(not o.available,o.lic.qty_min or 1,o.price is None,o.price or 0,o.offer_id)))


def search_terms(offer):
    aliases=offer.attrs.get("aliases",[])
    if isinstance(aliases,str):
        try:
            aliases=json.loads(aliases)
        except ValueError:
            aliases=[aliases]
    result=[str(a) for a in aliases] if isinstance(aliases,list) else []
    if offer.attrs.get("task"):
        result.append(str(offer.attrs["task"]))
    return result
