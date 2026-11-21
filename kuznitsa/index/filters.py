import numpy as np


def values(value):
    return value if isinstance(value,list) else [value]


class OfferFilters:
    """Таблица столбцов одной карточки. Строки соответствуют порядку её предложений."""
    def __init__(self,offers,knowledge,vendor):
        self.masks={}
        self.size=len(offers)
        self.columns={}
        for field in ("action","model","metric","audience","term_months"):
            self.columns[field]=np.array([getattr(o.lic,field) for o in offers],dtype=object)
        for field in ("delivery","version","registry","edition","family_id","vendor_id","category_id"):
            key={"family_id":"family","vendor_id":"vendor","category_id":"category"}.get(field,field)
            self.columns[key]=np.array([getattr(o,field) for o in offers],dtype=object)
        # Для предложения без флага можно использовать однозначное сведение о всём семействе.
        if isinstance(knowledge.get("registry"),bool):
            self.columns["registry"]=np.array([knowledge["registry"] if o.registry is None else o.registry for o in offers],dtype=object)
        self.columns["origin"]=np.array([
            ("russian" if o.attrs["country"].casefold() in {"россия","рф","ru","russia"} else "foreign")
            if o.attrs.get("country") else vendor.get("origin") for o in offers],dtype=object)
        self.columns["promo"]=np.array([o.attrs.get("promo")=="true" for o in offers])
        self.price=np.array([o.price if o.price is not None and not o.price_on_request else np.nan for o in offers])
        self.unit_prices=self.price/np.array([o.lic.pack or 1 for o in offers])
        self.minimum=np.array([o.lic.qty_min or 1 for o in offers])
        self.maximum=np.array([o.lic.qty_max or np.inf for o in offers])
        self.package_capacity=np.array([bool(o.lic.pack and o.lic.qty_max==o.lic.pack) for o in offers])
        domestic=np.array([bool(o.domestic or o.registry or (o.attrs.get("country") or "").lower() in ("россия","рф","ru","russia") or
                                not o.attrs.get("country") and vendor.get("origin")=="russian") for o in offers])
        self.sets={"domestic_supply":{True:domestic}}
        from .source import strings
        from kuznitsa.text import normalize
        for field in ("aliases","task"):
            masks={}
            for i,o in enumerate(offers):
                for term in strings(o.attrs.get(field)):
                    key=normalize(term)
                    if key not in masks:masks[key]=np.zeros(self.size,dtype=bool)
                    masks[key][i]=True
            self.sets["supplier_"+field]=masks
        for key,attr in [("platform","platforms"),("certs","certs")]:
            sets=[set(getattr(o,attr)) for o in offers]
            self.sets[key]={v:np.fromiter((v in s for s in sets),bool) for v in set().union(*sets)}
        from kuznitsa.plans.procurement import offer_codes
        procurement={}
        for i,offer in enumerate(offers):
            for kind,code in offer_codes(offer):
                masks=procurement.setdefault(kind,{})
                if code not in masks:
                    masks[code]=np.zeros(self.size,dtype=bool)
                masks[code][i]=True
        self.sets.update(procurement)
        self.constants=dict(deployment=knowledge.get("deployment",[]),origin=vendor.get("origin"))

    def mask(self,key,expected):
        if key in ("price_min","price_max"):
            return self._mask(key,expected)
        token=(key,tuple(values(expected)))
        mask=self.masks.get(token)
        if mask is None:
            mask=self._mask(key,expected)
            if len(self.masks)<128:
                self.masks[token]=mask
        return mask

    def _mask(self,key,expected):
        if key=="unit_price_max":
            return self.unit_prices<=expected
        if key=="price_min":
            return self.price>=expected
        if key=="price_max":
            return self.price<=expected
        if key in self.columns:
            return np.isin(self.columns[key],values(expected))
        if key in self.sets:
            masks=[self.sets[key].get(v,np.zeros(self.size,dtype=bool)) for v in values(expected)]
            if not masks:
                return np.zeros(self.size,dtype=bool)
            return np.logical_and.reduce(masks) if key=="certs" else np.logical_or.reduce(masks)
        return np.full(self.size,any(v in values(self.constants.get(key)) for v in values(expected)))

    def indices(self,filters,exclude,audience,action,n,upper):
        mask=self.mask("audience",[None,audience,"business"]) & self.mask("action",[action,None])
        if n:
            mask &= ((self.minimum<=n) & (self.maximum>=upper)) | self.package_capacity
        for key,expected in filters.items():
            mask &= self.mask(key,expected)
        for key,expected in exclude.items():
            mask &= ~self.mask(key,expected)
        return np.flatnonzero(mask)
