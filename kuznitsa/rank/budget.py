"""Лимиты покупки в рублях. Каноническая витринная цена уже включает НДС."""
import re
from .variants import calculation

PER_SEAT = re.compile(r"(?:за|на) (?:одно |одного |одну )?(?:место|пользователя|лицензию|устройство|компьютер)\b|/\s*(?:место|пк)\b")


def per_seat(query):
    return bool(PER_SEAT.search(query))


def nearest(cards, pick, filters, exclude, qty, profile, limit, unit=False):
    """Сохраняет все условия, кроме цены. Возвращает три ближайшие суммы сверх лимита."""
    trial = {k:v for k,v in filters.items() if k not in ("price_max","unit_price_max")}
    choices=[]
    for cid,card in cards:
        selected=pick(card,profile,trial,exclude,qty,prefer_lowest=True)
        if not selected:
            continue
        offer,count,_=selected
        calc=calculation(offer,count)
        if not calc:
            continue
        value=calc["total"] if count is not None else offer.price / ((offer.lic.pack or 1) if unit else 1)
        if value>limit:
            choices.append((round(value-limit,2),cid,selected))
    best=sorted(choices,key=lambda x:(x[0],x[1]))[:3]
    return {cid:s for _,cid,s in best},{cid:d for d,cid,_ in best}
