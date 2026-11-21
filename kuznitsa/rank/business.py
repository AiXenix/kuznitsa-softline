from itertools import islice
from .fit import TIERS
from kuznitsa.rank.variants import AUD_LABEL, public_offer, calculation


def ranked(card,selection,rel,exact,profile,weights,kb,ignored=()):
    o,count,owned = selection
    why = []
    badges = []
    pers = 0.
    if owned:
        pers+=.75
        why.append("Эта редакция уже куплена вашей организацией")
        badges.append(dict(kind="owned",label="У вас куплено"))
        if o.lic.action=="renewal" and owned.get("expires_in_days") is not None:
            why.append(f"До окончания лицензии {owned['expires_in_days']} дн.")
    if not owned and any(kb.rows["families"].get(item.get("family_id"),{}).get("vendor")==card.vendor for item in profile.owned):
        pers+=.35
        why.append("У вашей организации уже есть ПО этого вендора")
    if profile.segment=="smb" and profile.client_id!="guest" and (o.lic.qty_min or 1)<=max(50,profile.size_seats):
        pers+=.18
        why.append("Подходит для закупки небольшой партией")
    if o.lic.audience in {"gov","edu"}:
        pers+=.55
        why.append("Лицензия для "+AUD_LABEL[o.lic.audience])
        badges.append(dict(kind="edu_only" if o.lic.audience=="edu" else "audience",label=why[-1]))
    if "registry" not in ignored and profile.segment=="gov" and o.registry:
        pers+=.35
        why.append("Учтено предпочтение госзаказчика к ПО в реестре")
    if o.attrs.get("promo")=="true":
        badges.append(dict(kind="promo",label="Специальное предложение"))
    if o.registry or o.registry is None and card.kb.get("registry") is True:
        badges.append(dict(kind="registry",label="В реестре ПО" if o.registry else "В реестре по данным семейства"))
        if o.registry is None:
            why.append("Включение в реестр указано в базе знаний для всего семейства")
    if o.vat==0:
        badges.append(dict(kind="vat",label="Без НДС"))
    if "platform" not in ignored and profile.client_id!="guest" and set(profile.fleet.get("os",[])).intersection(o.platforms):
        pers+=.18
        why.append("Подходит для парка ОС клиента")
    if o.lic.qty_min:
        why.append(f"Диапазон от {o.lic.qty_min}"+(f" до {o.lic.qty_max}" if o.lic.qty_max else "")+" мест")
    pop,margin = card.commercial[o.offer_id]
    parts = {k:round(weights[k]*v,5) for k,v in dict(rel=rel,pop=pop,margin=margin,
             pers=min(1,pers) if profile.client_id!="guest" else 0).items()}
    tier = 0 if exact else 1 if rel>=.62 else 2 if rel>=.4 else 3
    why.insert(0,"Точное совпадение" if exact else "Совпадает с условиями поиска")
    score = sum(parts.values())*(1 if o.available else .6)*(.95 if o.price_on_request else 1)
    audiences={None,"business",o.lic.audience,profile.segment}
    return dict(card_id=card.id,title=card.title,vendor=dict(id=card.vendor,name=o.vendor),category=dict(id=card.category,
                title=kb.rows["categories"].get(card.category,{}).get("title", (o.category_path or ["ПО"])[-1])),
                summary=o.description,badges=badges,offer=public_offer(o),calc=calculation(o,count),
                variants=[public_offer(x) for x in islice((v for v in card.offers if v!=o and v.lic.audience in audiences),5)],variants_count=len(card.offers),
                price_from=card.price_from,score=dict(tier=tier,tier_label=TIERS[tier],score=score,parts=parts,why=why))
