from kuznitsa.rank.business import ranked
from kuznitsa.rank.variants import select
from kuznitsa.rank.fit import is_module,edition_rank


def restricted(engine,cards,profile,filters,exclude,weights):
    first=engine.catalog.cards[cards[0]["card_id"]]
    vendor=engine.kb.rows["vendors"].get(first.vendor,{})
    if vendor.get("market_status") not in ("restricted","left"):
        return None
    ids=list(first.kb.get("analogs",[]))
    ids.extend(a["family"] for a in engine.kb.rows["analogs"].get(first.family,{}).get("russian_analogs",[]))
    ids.extend(f for f,row in engine.kb.rows["families"].items() if first.family in row.get("replaces",[]))
    options=[]
    for fid in dict.fromkeys(ids):
        available=[]
        for cid in engine.catalog.by["family"].get(fid,()):
            group=engine.catalog.cards[cid]
            v=engine.kb.rows["vendors"].get(group.vendor,{})
            if is_module(group) or v.get("origin")!="russian":
                continue
            condition={k:v for k,v in filters.items() if k in ("audience","certs","registry")}
            found=select(group,profile,{**condition,"action":"new"},exclude,None)
            if found and found[0].available:
                available.append((edition_rank(group),cid,group,found))
        if available:
            _,_,group,found=min(available,key=lambda x:x[:2])
            options.append(ranked(group,found,.8,False,profile,weights,engine.kb))
    if options:
        note=f"У {vendor['name']} действуют ограничения поставки. Доступность указанной редакции следует подтвердить."
        return dict(type="analogs",title="Российские альтернативы",source=dict(title=first.title,status="restricted",note=note),
                    items=[dict(card=c,note="Замена по назначению") for c in options])


def merch_secondary(engine,ctx,block,merch,trace):
    """У связанных карточек сохраняются пояснения и собственные позиции в блоке."""
    by_id={entry["card"]["card_id"]:entry for entry in block["items"]}
    decision=engine.controls.merch(ctx,[entry["card"] for entry in by_id.values()])
    block["items"]=[]
    for position,card in enumerate(decision["cards"][:4],1):
        card["position"]=position
        block["items"].append({**by_id[card["card_id"]],"card":card})
    for key in ("fired","banners"):
        for rule in decision[key]:
            if rule not in merch[key]:
                merch[key].append(rule)
    if decision["fired"]:
        step=next(s for s in trace.steps if s["step"]=="merch")
        step.update(status="ok",summary=" · ".join(item["summary"] for item in merch["fired"]))
    return bool(block["items"])
