"""Вид цены из прайса для расчёта и проверки бюджета одного запроса."""
import re
import math
from copy import copy
from dataclasses import replace
import numpy as np

TERMS={"project":r"проектн|project","partner":r"партнер|дилер|partner|dealer","gov":r"госзаказ|государств|government|^gov$","retail":r"розни|retail"}
LABELS={"project":"проектная","partner":"партнёрская","gov":"для госзаказчика","retail":"розничная"}


PRICE_CUE = re.compile(
    r"\b(?:(?P<retail>в розницу|по розничной цене)|(?P<project>по проектной цене)"
    r"|(?P<partner>по партнерской цене|для партнера)|(?P<gov>для госзаказчика))(?=\s+до\b)"
)


def split_tariff(query):
    match = PRICE_CUE.search(query)
    if not match:
        return None, query
    # «До» и сумма остаются для разбора бюджета, адресат тарифа уже учтён.
    return match.lastgroup, (query[:match.start()] + query[match.end():].lstrip()).strip()


def value(offer,kind):
    prices=offer.attrs.get("prices")
    found={}
    if isinstance(prices,dict):
        for label,amount in prices.items():
            try:number=float(amount)
            except (TypeError,ValueError):continue
            if not math.isfinite(number) or number<=0:continue
            if label in TERMS:
                found[label]=number
                continue
            for key,pattern in TERMS.items():
                if re.search(pattern,label.lower().replace("ё","е")):
                    found.setdefault(key,number)
    return found.get(kind,found.get("retail",offer.price)),kind!="retail" and kind not in found


class PriceView:
    def __init__(self,kind):
        self.kind=kind
        self.cards={}
        self.fallback=set()

    def card(self,card):
        if card.id not in self.cards:
            offers=[]
            for offer in card.offers:
                price,fallback=value(offer,self.kind)
                if fallback:self.fallback.add(offer.offer_id)
                offers.append(offer.model_copy(update={"price":price,"price_on_request":price is None or offer.price_on_request and price==offer.price}))
            filters=copy(card.filters)
            filters.price=np.array([o.price if o.price is not None and not o.price_on_request else np.nan for o in offers])
            filters.unit_prices=filters.price/np.array([o.lic.pack or 1 for o in offers])
            self.cards[card.id]=replace(card,offers=offers,filters=filters,price_from=min((o.price for o in offers if o.price is not None),default=None))
        return self.cards[card.id]
