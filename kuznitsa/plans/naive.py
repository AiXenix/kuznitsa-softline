"""Базовый поиск по названиям отдельных предложений."""
from kuznitsa.schema import Offer
from kuznitsa.rank.variants import public_offer, calculation


from collections import defaultdict
from functools import lru_cache
import re
from threading import Lock
from kuznitsa.text import lemma

_LOCK=Lock()
_STOP={"для","и","на","в","из","по","купить","цена","лицензия"}


@lru_cache(32768)
def words(text):
    return frozenset(lemma(w) for w in re.findall(r"[a-zа-я0-9]+",text.lower().replace("ё","е")) if w not in _STOP)


class StoreIndex:
    def __init__(self,catalog):
        self.offers=[]
        self.postings=defaultdict(set)
        categories=getattr(catalog,"legacy_category_names",None)
        if categories is None:
            from kuznitsa.config import Config
            import yaml
            path=Config().kb/"categories.yaml"
            categories={r["id"]:r.get("title","") for r in yaml.safe_load(path.read_text()) or []} if path.is_file() else {}
        for c in catalog.cards.values():
            category=words(categories.get(c.category,""))
            for o in c.offers:
                i=len(self.offers)
                self.offers.append(o)
                for word in words(o.name)|words(c.title)|words(o.family_name or "")|words(o.vendor or "")|words(o.sku or "")|category|words(" ".join(o.category_path)):
                    self.postings[word].add(i)
                    if len(word)>3 and word.isascii() and word.isalpha():
                        self.postings[word[:3]].add(i)

    def match(self,q,limit):
        terms=sorted((self.postings.get(w,set()) for w in words(q)),key=len)
        ids=terms[0].intersection(*terms[1:]) if terms else ()
        found=sorted((self.offers[i] for i in ids),key=lambda o:(-o.popularity,o.offer_id))
        return found if limit is None else found[:max(0,limit)]


def prepare(catalog):
    with _LOCK:
        if not hasattr(catalog,"legacy_index"):
            catalog.legacy_index=StoreIndex(catalog)
    return catalog.legacy_index


def match(catalog,q,limit=20) -> list[Offer]:
    return prepare(catalog).match(q,limit)


def card(engine, offer, position):
    group = engine.catalog.cards[offer.card_id]
    return dict(card_id="sku:"+offer.offer_id,card_ref=offer.card_id, position=position, title=offer.name,
                vendor=dict(id=group.vendor, name=offer.vendor),
                category=dict(id=group.category, title=engine.names["category"].get(group.category, group.category)),
                summary=offer.description, badges=[], offer=public_offer(offer),
                calc=calculation(offer, None), variants=[], variants_count=1,
                price_from=offer.price, score=dict(tier=0, score=offer.popularity, parts={"pop":offer.popularity},
                why=["Совпадение слов в названии, категории, вендоре или артикуле", "Позиция определяется популярностью"]))
