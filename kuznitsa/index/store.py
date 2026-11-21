import re
from collections import defaultdict
from dataclasses import dataclass
import numpy as np
from kuznitsa.schema import Offer
from kuznitsa.text import sku_key
from .cache import lexical
from .filters import OfferFilters
from scipy.stats import rankdata
from .dense import Dense


@dataclass
class Card:
    id: str
    title: str
    family: str
    vendor: str
    category: str
    offers: list
    kb: dict
    price_from: float | None
    filters: OfferFilters
    commercial: dict


class Catalog:
    def __init__(self,cfg,kb):
        groups = defaultdict(list)
        self.skus = {}
        self.offers_by_id = {}
        regional = defaultdict(list)
        with (cfg.data/"catalog.jsonl").open() as stream:
            for line in stream:
                o = Offer.model_validate_json(line)
                groups[o.card_id].append(o)
                self.offers_by_id[o.offer_id] = o
                if o.sku:
                    self.skus[sku_key(o.sku)] = o
                    base=re.sub(r"[-/](?:ru|rus|russia|en|eu)$","",o.sku,flags=re.I)
                    if base!=o.sku:
                        regional[sku_key(base)].append(o)
        self.sorted_codes=sorted(self.skus)
        self.regional={k:rows[0] for k,rows in regional.items() if len(rows)==1}
        self.cards = {}
        self.by = {k:defaultdict(set) for k in ("family","vendor","category")}
        docs = []
        for ident,offers in groups.items():
            o = offers[0]
            f = kb.rows["families"].get(o.family_id,{})
            ed = next((x.get("title",x.get("name")) for x in f.get("editions",[]) if x["id"]==o.edition),o.edition)
            title = " ".join(filter(None,[f.get("title") or o.family_name or o.name,ed]))
            vendor = kb.rows["vendors"].get(o.vendor_id,{})
            card = Card(ident,title,o.family_id or ident,o.vendor_id,o.category_id,offers,f,
                        min((x.price for x in offers if x.price is not None),default=None),
                        OfferFilters(offers,f,vendor),{})
            self.cards[ident] = card
            for key in self.by:
                self.by[key][getattr(card,key)].add(ident)
            docs.append(dict(title=title,aliases=" ".join(map(str,f.get("aliases",[]))),vendor=o.vendor or "",
                             category=kb.rows["categories"].get(o.category_id,{}).get("title",""),
                             keywords=" ".join(map(str,f.get("use_cases",[])+f.get("roles",[])+f.get("formats",[]))),
                             summary=o.description,names=" ".join(dict.fromkeys(w for x in offers for w in x.name.split()))))
        for ids in self.by["category"].values():
            choices=[o for ident in sorted(ids) for o in self.cards[ident].offers]
            popular=rankdata([o.popularity for o in choices])/len(choices)
            margins=rankdata([o.margin for o in choices])/len(choices)
            for o,p,m in zip(choices,popular,margins):
                self.cards[o.card_id].commercial[o.offer_id]=(float(p),float(m))
        from functools import lru_cache
        self.scores=lru_cache(512)(self.scores)
        self.ids = list(self.cards)
        self.bm,self.char,self.matrix = lexical(cfg,docs)
        knowledge=[]
        for kind,group in [("category","categories"),("use_case","use_cases"),("role","roles"),("industry","industries"),("faq","faq")]:
            for ident,row in kb.rows[group].items():
                text=". ".join([row.get("title",ident),*map(str,row.get("phrases",[])[:3]+row.get("questions",[])[:3]+row.get("synonyms",[])[:3])])
                knowledge.append(((kind,ident),text))
        self.dense = Dense(cfg,[". ".join(d[k] for k in ("title","vendor","category","summary","keywords")) for d in docs],knowledge)

    def prefix_skus(self,text,limit=8):
        from bisect import bisect_left
        prefix=sku_key(text)
        start=bisect_left(self.sorted_codes,prefix)
        return [self.skus[key] for key in self.sorted_codes[start:start+limit] if key.startswith(prefix)]

    def scores(self,q,semantic=True):
        if self.matrix is None:
            return {}
        ch = (self.matrix @ self.char.transform([q]).T).toarray().ravel()
        lexical_scores=.75*self.bm.scores(q)+.25*ch
        scores=.6*lexical_scores+.4*self.dense.scores(q,len(self.ids)) if semantic else lexical_scores
        return dict(zip(self.ids,scores))
