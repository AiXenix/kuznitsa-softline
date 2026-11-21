from math import ceil

AUDIENCE = {"gov":"gov","edu":"edu","individual":"home"}
AUD_LABEL = dict(gov="государственных учреждений",edu="учебных заведений",business="организаций",home="домашних пользователей")


def values(v):
    return v if isinstance(v,list) else [v]


def select(card,profile,filters,exclude,qty,exact=None,relax_qty=False,prefer_lowest=False):
    owned = next((p for p in profile.owned if p.get("family_id")==card.family and
                  (not p.get("edition") or p["edition"]==card.offers[0].edition)),{})
    audience = filters.get("audience") or AUDIENCE.get(profile.segment,"business")
    renewal = owned and owned.get("expires_in_days") is not None and 0<=owned["expires_in_days"]<=90
    action = filters.get("action") or ("renewal" if renewal else "new")
    n = qty["value"] if qty else owned.get("qty") if action=="renewal" else None
    if n and card.kb.get("max_seats") and n>card.kb["max_seats"] and not exact:
        return None
    best,best_key = None,None
    eligible_packs=[]
    budget=(float("inf") if prefer_lowest else filters.get("price_max")) if n else None
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
        if not len(indices) and not filters.get("action") and action=="renewal":
            action="new"
            n=qty["value"] if qty else None
            indices=card.filters.indices(filters,exclude,audience,action,None if relax_qty else n,n)
        choices=(card.offers[i] for i in indices)
    for o in choices:
        lic=o.lic
        if n and lic.pack:
            eligible_packs.append(o)
            if budget is not None and not exact:
                # Стоимость одного размера пакета не ограничивает смешанный набор.
                continue
        count = ceil((n or 1)/lic.pack) if lic.pack else max(n or 1,lic.qty_min or 1)
        if lic.qty_max and count>lic.qty_max and not lic.pack:
            count = lic.qty_max
        if budget is not None and (o.price is None or o.price_on_request or count*o.price>budget):
            continue
        key = (o.available,lic.action==action,lic.audience==audience,lic.term_months in (None,12),not o.price_on_request,
               -abs(count*(lic.pack or 1)-(n or count)), -(count*(o.price or 0)) if lic.pack and n else 0, o.popularity,-(o.price or 0))
        if prefer_lowest:
            if o.price is None or o.price_on_request:continue
            key=(-(count*o.price),*key)
        if best_key is None or key>best_key:
            best_key,best = key,(o,count if n else None,owned)
    if budget is not None and eligible_packs and not exact:
        from .packs import bundle
        groups={}
        for o in eligible_packs:
            lic=o.lic
            key=(lic.action,lic.audience,lic.term_months,lic.metric,lic.model,o.version,o.delivery)
            groups.setdefault(key,[]).append(o)
        for group in groups.values():
            base_required=card.family=="windows_server" and group[0].lic.metric=="core"
            base=max(card.kb.get("license",{}).get("packs",[]) or [o.lic.pack for o in group])
            packages=bundle(group,n,base_required,base)
            total=sum(o.price*m for o,m in packages)
            if not packages or total>budget:
                continue
            o=packages[0][0]
            covered=sum(item.lic.pack*m for item,m in packages)
            key=(o.available,o.lic.action==action,o.lic.audience==audience,o.lic.term_months in (None,12),
                 True,-abs(covered-n),-total,o.popularity,-o.price)
            if prefer_lowest:key=(-total,*key)
            if best_key is None or key>best_key:
                best_key,best=key,(o,packages,owned)
        return best
    if best and eligible_packs and best[0].lic.pack and not exact:
        from .packs import bundle
        chosen=best[0]
        groups={}
        priority=(chosen.available,chosen.lic.audience,chosen.lic.term_months,chosen.lic.action,chosen.lic.metric)
        for offer in eligible_packs:
            lic=offer.lic
            if (offer.available,lic.audience,lic.term_months,lic.action,lic.metric)!=priority:
                continue
            groups.setdefault((lic.model,offer.version,offer.delivery),[]).append(offer)
        needs_base=card.family=="windows_server" and chosen.lic.metric=="core"
        base=max(card.kb.get("license",{}).get("packs",[]) or [chosen.lic.pack])
        options=[items for group in groups.values() if (items:=bundle(group,n,needs_base,base))]
        if options:
            packages=min(options,key=lambda items:(sum(o.price*m for o,m in items),sum(o.lic.pack*m for o,m in items)))
            best=(packages[0][0],packages,owned)
        elif needs_base:
            return None
    return best


def public_offer(o):
    lic=o.lic
    return dict(offer_id=o.offer_id,sku=o.sku,source_id=o.source_id,source_ids=o.source_ids.copy(),
                name=o.name,price=o.price,price_on_request=o.price_on_request,
                delivery=o.delivery,vat=o.vat,available=o.available,version=o.version,action=lic.action,model=lic.model,
                term_months=lic.term_months,metric=lic.metric,qty_min=lic.qty_min,qty_max=lic.qty_max,pack=lic.pack,audience=lic.audience)


def calculation(o,count):
    if o.price is None or o.price_on_request:
        return None

    def rub(n):
        return f"{n:,.2f}".replace(","," ").removesuffix(".00").replace(".",",")
    if isinstance(count,list):
        if len(count)==1:
            return calculation(count[0][0],count[0][1])
        total=sum(o.price*m for o,m in count)
        text=" + ".join(f"{m} × {rub(o.price)} ₽ ({o.lic.pack} мест)" for o,m in count)
        return dict(qty=sum(m for _,m in count),unit_price=None,total=total,text=f"{text} = {rub(total)} ₽",
                    items=[dict(offer_id=o.offer_id,pack=o.lic.pack,count=m,price=o.price) for o,m in count])
    if count is None:
        units={"device":"устройство","user":"пользователя","core":"ядро","server":"сервер","company":"организацию","mailbox":"ящик"}
        unit=f"пакет на {o.lic.pack} мест" if (o.lic.pack or 1)>1 else units.get(o.lic.metric,"лицензию")
        duration=" в год" if o.lic.term_months==12 else f" на {o.lic.term_months} мес." if o.lic.term_months else ""
        band=f" (при покупке от {o.lic.qty_min})" if (o.lic.qty_min or 1)>1 else ""
        return dict(qty=None,unit_price=o.price,total=None,text=f"от {rub(o.price)} ₽ за {unit}{duration}{band}")
    total=round(count*o.price,2)
    unit=""
    if (o.lic.pack or 1)>1:
        noun="пакетов" if 11<=count%100<=14 else "пакет" if count%10==1 else "пакета" if count%10 in (2,3,4) else "пакетов"
        units={"device":"устр.","user":"польз.","core":"яд.","server":"серв."}
        unit=f" {noun} по {o.lic.pack} {units.get(o.lic.metric,'ед.')}"
    return dict(qty=count,unit_price=o.price,total=total,text=f"{count}{unit} × {rub(o.price)} ₽ = {rub(total)} ₽")


def select_for_workplaces(card,profile,filters,exclude,seats):
    """Рабочие места покрываются лицензиями на людей, устройства или организацию."""
    if not seats:
        return select(card,profile,filters,exclude,None)
    for metrics,quantity in ((["user","device","concurrent","mailbox"],seats),(["company"],{"value":1})):
        found=select(card,profile,{**filters,"metric":metrics},exclude,quantity)
        if found:
            return found
    # Из числа сотрудников нельзя вывести число серверов, ядер или площадок.
    return select(card,profile,filters,exclude,None)
