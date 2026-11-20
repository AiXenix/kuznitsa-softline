from math import ceil

AUDIENCE = {"gov":"gov","edu":"edu","individual":"home"}
AUD_LABEL = dict(gov="государственных учреждений",edu="учебных заведений",business="организаций",home="домашних пользователей")


def values(v):
    return v if isinstance(v,list) else [v]


def select(card,profile,filters,exclude,qty,exact=None,relax_qty=False):
    owned = next((p for p in profile.owned if p.get("family_id")==card.family and
                  (not p.get("edition") or p["edition"]==card.offers[0].edition)),{})
    audience = filters.get("audience") or AUDIENCE.get(profile.segment,"business")
    renewal = owned and owned.get("expires_in_days") is not None and 0<=owned["expires_in_days"]<=90
    action = filters.get("action") or ("renewal" if renewal else "new")
    n = qty["value"] if qty else owned.get("qty") if action=="renewal" else None
    best,best_key = None,None
    upper = qty.get("max",n) if qty else n
    if exact:
        index=card.offers.index(exact)
        if any(card.filters.mask(k,v)[index] for k,v in exclude.items()):
            return None
        if any(not card.filters.mask(k,v)[index] for k,v in filters.items()):
            return None
        choices = [exact]
    else:
        indices=card.filters.indices(filters,exclude,audience,action,None if relax_qty else n,upper)
        choices=(card.offers[i] for i in indices)
    for o in choices:
        lic=o.lic
        count = ceil((n or 1)/lic.pack) if lic.pack else max(n or 1,lic.qty_min or 1)
        if lic.qty_max and count>lic.qty_max and not lic.pack:
            count = lic.qty_max
        key = (o.available,lic.action==action,lic.audience==audience,lic.term_months in (None,12),not o.price_on_request,
               -abs(count*(lic.pack or 1)-(n or count)), -(count*(o.price or 0)) if lic.pack and n else 0, o.popularity,-(o.price or 0))
        if best_key is None or key>best_key:
            best_key,best = key,(o,count,owned)
    return best


def public_offer(o):
    return {**o.model_dump(include={"offer_id","sku","name","price","price_on_request","delivery","vat","available","version"}),**o.lic.model_dump()}


def calculation(o,count):
    if o.price is None or o.price_on_request:
        return None
    total = round(count*o.price,2)
    def rub(n):
        return f"{n:,.2f}".replace(","," ").removesuffix(".00").replace(".",",")
    unit = f" пак. по {o.lic.pack}" if o.lic.pack else ""
    return dict(qty=count,unit_price=o.price,total=total,text=f"{count}{unit} × {rub(o.price)} ₽ = {rub(total)} ₽")
