import re


def profile_info(client):
    quoted=re.search("«([^»]+)»",client.title)
    short=quoted[1] if quoted else client.title.split(" — ")[0]
    labels=dict(smb="Малый бизнес",mid="Средний бизнес",enterprise="Крупный бизнес",gov="Госсектор",edu="Образование",individual="Частный клиент")
    return dict(id=client.client_id,title=client.title,segment=client.segment,short=short if len(short)<=24 else short[:23].rstrip()+"…",
                segment_title="Гость" if client.client_id=="guest" else labels[client.segment])


def next_queries(engine,cards,query,blocks=()):
    if not cards:
        return []
    card=engine.catalog.cards[cards[0]["card_id"]]
    offer=engine.catalog.offers_by_id[cards[0]["offer"]["offer_id"]]
    family=engine.names["family"].get(card.family)
    category=engine.names["category"].get(card.category)
    queries=[]
    if family:
        if any(o.lic.action=="renewal" for o in card.offers):
            queries.append(f"{family} продление")
        ed=next((e.get("title") or e.get("name") for e in card.kb.get("editions",[]) if e["id"]==offer.edition),None)
        if ed and offer.lic.term_months:
            queries.append(f"{family} {ed} на {offer.lic.term_months} мес")
    analogs=card.kb.get("analogs",[])+[a["family"] for a in engine.kb.rows["analogs"].get(card.family,{}).get("russian_analogs",[])]
    if family and any(engine.catalog.by["family"].get(fid) and engine.kb.rows["families"].get(fid,{}).get("vendor")!=card.vendor for fid in analogs):
        queries.append(f"Аналог {family}")
    companion=next((i["card"] for b in blocks if b["type"]=="crosssell" for i in b["items"]),None)
    if companion:
        related=engine.catalog.cards[companion["card_id"]]
        name=engine.names["family"].get(related.family)
        if name:
            queries.append(f"Купить {name}")
    if category:
        if offer.registry:
            queries.append(f"{category} из реестра")
        if offer.lic.qty_min and offer.lic.metric in ("device","user"):
            unit="пк" if offer.lic.metric=="device" else "пользователей"
            queries.append(f"{category} на {offer.lic.qty_min} {unit}")
        queries.append(category)
    return list(dict.fromkeys(q for q in queries if q.casefold()!=query))[:6]
