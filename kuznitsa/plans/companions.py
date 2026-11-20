"""Связи из KB. Цена и объяснение берутся тем же способом, что у основной выдачи."""
from kuznitsa.rank.business import ranked
from kuznitsa.rank.variants import select


def companions(engine, intent, cards, profile, weights, filters, exclude):
    if not cards or intent not in ("sku","product","renewal","role_kit"):
        return None
    rules=engine.kb.rows.get("crosssell",{})
    anchor=engine.catalog.cards[cards[0]["card_id"]]
    occupied={engine.catalog.cards[c["card_id"]].family for c in cards}
    occupied.update(p.get("family_id") for p in profile.owned)
    offers={}
    required={k:v for k,v in filters.items() if k in ("registry","certs","audience")}
    required["action"]="new"
    for rule in rules.values():
        when=rule["when"]
        if anchor.family not in when.get("families",[]) and anchor.category not in when.get("categories",[]):
            continue
        for suggestion in rule["suggest"]:
            ids={cid for fid in suggestion.get("families",[]) for cid in engine.catalog.by["family"].get(fid,())}
            if not ids:
                ids=engine.catalog.by["category"].get(suggestion.get("category"),())
            for cid in ids:
                card=engine.catalog.cards[cid]
                if card.family in occupied or cid in offers:
                    continue
                selected=select(card,profile,required,exclude,None)
                if selected:
                    item=ranked(card,selected,.8,False,profile,weights,engine.kb)
                    offers[cid]=dict(card=item,reason=suggestion["reason"])
    items=[]
    for item in sorted(offers.values(),key=lambda x:(-x["card"]["score"]["score"],x["card"]["card_id"])):
        family=engine.catalog.cards[item["card"]["card_id"]].family
        if family not in occupied:
            item["card"]["position"]=len(items)+1
            items.append(item)
            occupied.add(family)
        if len(items)==4:
            break
    if items:
        return dict(type="crosssell",title="С этим обычно берут",items=items)
