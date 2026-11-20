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
        self.columns["promo"]=np.array([o.attrs.get("promo")=="true" for o in offers])
        self.price=np.array([o.price if o.price is not None and not o.price_on_request else np.nan for o in offers])
        self.minimum=np.array([o.lic.qty_min or 1 for o in offers])
        self.maximum=np.array([o.lic.qty_max or np.inf for o in offers])
        self.sets={}
        for key,attr in [("platform","platforms"),("certs","certs")]:
            sets=[set(getattr(o,attr)) for o in offers]
            self.sets[key]={v:np.fromiter((v in s for s in sets),bool) for v in set().union(*sets)}
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
            mask &= (self.minimum<=n) & (self.maximum>=upper)
        for key,expected in filters.items():
            mask &= self.mask(key,expected)
        for key,expected in exclude.items():
            mask &= ~self.mask(key,expected)
        return np.flatnonzero(mask)
