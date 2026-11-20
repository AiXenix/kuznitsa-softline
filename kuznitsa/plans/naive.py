"""Базовый поиск по названиям отдельных предложений."""
from kuznitsa.schema import Offer
from kuznitsa.rank.variants import public_offer, calculation


def match(catalog, q, limit=20) -> list[Offer]:
    words = q.lower().split()
    if not words:
        return []
    matches = []
    for group in catalog.cards.values():
        for offer in group.offers:
            name = offer.name.lower()
            if all(word in name for word in words):
                matches.append(offer)
    matches.sort(key=lambda o: -o.popularity)
    return matches if limit is None else matches[:max(0, limit)]


def card(engine, offer, position):
    group = engine.catalog.cards[offer.card_id]
    return dict(card_id="sku:"+offer.offer_id, position=position, title=offer.name,
                vendor=dict(id=group.vendor, name=offer.vendor),
                category=dict(id=group.category, title=engine.names["category"].get(group.category, group.category)),
                summary=offer.description, badges=[], offer=public_offer(offer),
                calc=calculation(offer, None), variants=[], variants_count=1,
                price_from=offer.price, score=dict(tier=0, score=offer.popularity, parts={"pop":offer.popularity},
                why=["Все слова входят в название предложения", "Позиция определяется популярностью"]))
