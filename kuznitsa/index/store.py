import re
import json
from collections import defaultdict
from dataclasses import dataclass
import numpy as np
from kuznitsa.schema import Offer
from kuznitsa.plans.procurement import offer_codes
from kuznitsa.text import sku_key,normalize
from .cache import lexical
from .filters import OfferFilters
from .hardware import model_title
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
        hardware_models={}
        title_vendors=defaultdict(set)
        self.card_aliases={}
        self.offer_names={}
        self.source_codes={}
        self.source_variants={}
        source_offers=defaultdict(dict)
        self.registry_codes=defaultdict(dict)
        self.replacements=defaultdict(set)
        self.source_classes=defaultdict(set)
        self.source_names=defaultdict(set)
        from .source import read_offer,identifiers,replacements,strings,source_key
        self.procurement=defaultdict(set)
        self.skus = {}
        self.offers_by_id = {}
        regional = defaultdict(list)
        self.retired={}
        def archive(name,keys,category=None,vendor=None,family=None):
            for key in keys:
                if key:self.retired[normalize(str(key))]=(name,category,vendor,family)
        archived=cfg.data/"inactive_offers.jsonl"
        if archived.is_file():
            with archived.open() as retired_stream:
                for line in retired_stream:
                    row=json.loads(line)
                    name=row.get("name","")
                    archive(name,[name,row.get("source_id"),*strings(row.get("source_ids"))],
                            row.get("category_id"),row.get("vendor_id"),row.get("family_id"))
        with (cfg.data/"catalog.jsonl").open() as stream:
            for line in stream:
                o = read_offer(line)
                if any(str(o.attrs.get(k,"")).lower() in ("false","нет","no","0") for k in ("active","sold")):
                    archive(o.name,[o.name,o.family_name,*identifiers(o),*strings(o.attrs.get("aliases"))],o.category_id,o.vendor_id,o.family_id)
                    continue
                if o.domain=="hardware" and not o.group_id and o.vendor:
                    key=(normalize(o.vendor),normalize(model_title(o)))
                    original=o.card_id
                    title_vendors[key[1]].add(key[0])
                    primary=hardware_models.setdefault(key,original)
                    if primary!=original:
                        self.card_aliases[original]=primary
                        o._hardware_card=primary
                for code in o.source_ids:
                    source_offers[code.casefold()][o.offer_id]=o
                for code in identifiers(o):
                    if code:
                        self.source_codes.setdefault(str(code).casefold(),o)
                        key=source_key(str(code))
                        previous=self.source_variants.setdefault(key,o)
                        if previous is not o:self.source_variants[key]=None
                if o.attrs.get("registry_no"):
                    self.registry_codes[o.attrs["registry_no"]][o.card_id]=o
                for name in replacements(o):self.replacements[name].add(o.card_id)
                if o.category_id:
                    for name in o.category_path:self.source_classes[name].add(o.category_id)
                for alias in strings(o.attrs.get("aliases")):
                    self.source_names[alias].add(o.family_id)
                if o.attrs.get("series"):self.source_names[o.attrs["series"]].add(o.family_id)
                if " / " in o.name and "," in o.name:
                    base=o.name.partition(",")[0].split("(")[0].strip()
                    if base:self.source_names[base].add(o.family_id)
                for key in offer_codes(o):
                    self.procurement[key].add(o.card_id)
                self.offer_names.setdefault(normalize(o.name),o)
                groups[o.card_id].append(o)
                self.offers_by_id[o.offer_id] = o
                if o.sku:
                    self.skus[sku_key(o.sku)] = o
                    base=re.sub(r"[-/](?:ru|rus|russia|en|eu)$","",o.sku,flags=re.I)
                    if base!=o.sku:
                        regional[sku_key(base)].append(o)
        # Один родительский код может обозначать несколько редакций или ступеней.
        self.shared_sources={}
        for key, variants in source_offers.items():
            if len(variants)>1:
                ordered=sorted(variants.values(),key=lambda v:(not v.available,v.lic.qty_min or 1,
                               v.price is None,v.price or 0,v.offer_id))
                self.shared_sources[key]=ordered
                self.source_codes[key]=ordered[0]
        self.sorted_codes=sorted(self.skus)
        self.sorted_source_codes=sorted(self.source_codes)
        self.regional={k:rows[0] for k,rows in regional.items() if len(rows)==1}
        self.cards = {}
        self.by = {k:defaultdict(set) for k in ("family","vendor","category")}
        docs = []
        for ident,offers in groups.items():
            o = offers[0]
            f = kb.rows["families"].get(o.family_id,{})
            if o.domain:
                offers.sort(key=lambda x:(not x.available,x.price is None,x.lic.action not in (None,"new"),x.price or 0,x.offer_id))
                o=offers[0]
            ed = next((x.get("title",x.get("name")) for x in f.get("editions",[]) if x["id"]==o.edition),o.edition)
            title = " ".join(filter(None,[f.get("title") or o.family_name or o.name,ed]))
            if o.domain:
                title=o.family_name or (o.category_path or [o.name])[-1]
            if o.domain=="hardware" and not o.group_id:
                title=model_title(o)
                if len(title_vendors[normalize(title)])>1 and o.vendor:
                    title=f"{title} · {o.vendor}"
            vendor = kb.rows["vendors"].get(o.vendor_id,{})
            card = Card(ident,title,o.family_id or ident,o.vendor_id,o.category_id,offers,f,
                        min((x.price for x in offers if x.price is not None),default=None),
                        OfferFilters(offers,f,vendor),{})
            self.cards[ident] = card
            for key in self.by:
                self.by[key][getattr(card,key)].add(ident)
            aliases=dict.fromkeys([*map(str,f.get("aliases",[])),*(s for x in offers for s in strings(x.attrs.get("aliases")))])
            tasks=dict.fromkeys(s for x in offers for s in strings(x.attrs.get("task")))
            docs.append(dict(title=title,aliases=" ".join(aliases),vendor=o.vendor or "",
                             category=kb.rows["categories"].get(o.category_id,{}).get("title") or " ".join(o.category_path),
                             keywords=" ".join(map(str,f.get("use_cases",[])+f.get("roles",[])+f.get("formats",[])+list(tasks))),
                             summary=o.description,names=" ".join(dict.fromkeys(w for x in offers for w in x.name.split()))))
        from .source import SupplierNames
        self.supplier = SupplierNames(self.cards)
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
        self.is_feed=any(c.offers[0].domain for c in self.cards.values())
        self.dense = Dense(cfg,[] if self.is_feed else [". ".join(d[k] for k in ("title","vendor","category","summary","keywords")) for d in docs],knowledge)

        from .sections import Sections
        self.sections=Sections(self,cfg)
        if self.is_feed:
            from .feed import FeedIndex
            self.feed=FeedIndex(self,kb,cfg)

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
