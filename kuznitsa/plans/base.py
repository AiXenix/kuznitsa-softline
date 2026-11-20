from kuznitsa.understand.intent import base_plan
from kuznitsa.rank.variants import values


def descendants(kb,ids):
    result = set(values(ids))
    while True:
        more = {k for k,c in kb.rows["categories"].items() if c.get("parent") in result}-result
        if not more:
            return result
        result.update(more)


def candidates(cat,kb,plan,f,scores,sku):
    if plan=="sku":
        return {sku.card_id:1.} if sku else {}
    if plan=="off_topic":
        return {}
    if plan=="out_of_catalog":
        matches = {}
        for fid in f.get("family",[]):
            row = kb.rows["families"].get(fid,{})
            targets = row.get("analogs",[]) + [v.get("family") for v in kb.rows["analogs"].get(fid,{}).get("russian_analogs",[]) if isinstance(v,dict)]
            for a in targets:
                matches.update(dict.fromkeys(cat.by["family"].get(a,[]),.85))
            for cid in cat.by["category"].get(row.get("category"),[]):
                matches.setdefault(cid,.55)
        return matches
    ids = None
    floor = 0
    for k,v in [("family",.88),("vendor",.50),("category",.55)]:
        if f.get(k):
            allowed = descendants(kb,f[k]) if k=="category" else values(f[k])
            group = set().union(*(cat.by[k].get(key,set()) for key in allowed))
            ids = group if ids is None else ids & group
            floor = max(floor,v)
    if ids is None:
        ids = cat.cards.keys()
        if f:
            floor = .42
    result = {c:max(scores.get(c,0),floor) for c in ids}
    return dict(sorted(((k,v) for k,v in result.items() if v>=.22),key=lambda item:(-item[1],item[0]))[:300])
