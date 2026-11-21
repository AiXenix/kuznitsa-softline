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


def labels(engine):
    from kuznitsa.understand.intent import TITLES
    from kuznitsa.rank.fit import TIERS
    from kuznitsa.rank.priorities import CRITERIA,TAGS
    return dict(criteria=CRITERIA,tags=TAGS,categories={k:dict(title=r["title"],parent=r.get("parent")) for k,r in engine.kb.rows["categories"].items()},
                vendors=engine.names["vendor"],roles=engine.names["role"],industries=engine.names["industry"],
                intents=TITLES,tiers=dict(enumerate(TIERS)),segments=dict(smb="Малый бизнес",mid="Средний бизнес",enterprise="Крупный бизнес",gov="Госсектор",edu="Образование",individual="Частный клиент"),
                zero_reasons=dict(off_topic="Вне ассортимента",unknown_term="Неизвестное название",not_in_catalog="Нет в каталоге",vendor_left="Поставки прекращены",filters_too_strict="Строгие условия",qty_out_of_range="Нет диапазона количества",no_available_offer="Нет доступного предложения"),
                blocks=dict(products="Продукты",kit="Комплект",spec="Спецификация",compare="Сравнение",answer="Ответ",services="Услуги",promo="Акции",lead="Заявка",analogs="Замены",my_licenses="Ваши лицензии",clarify="Уточнение",vendors="Вендоры",categories="Категории",crosssell="Сопутствующие товары",not_in_catalog="Нет в каталоге"))
