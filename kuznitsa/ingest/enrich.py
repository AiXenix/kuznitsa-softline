import hashlib
import json
import math
import re
from dataclasses import replace
from functools import lru_cache

from kuznitsa.schema import License, Offer
from .adapters import category_path
from .mapping import field_for
from .nameparse import Evidence, PATTERNS, TERM, normalize


def stable(prefix, text):
    return prefix+hashlib.blake2s(text.encode(),digest_size=10).hexdigest()


def number(v):
    if v is None or v=="":
        return None
    text=re.sub(r"\s|₽|руб\.?|RUB|%","",str(v),flags=re.I)
    if "," in text and "." in text:
        thousands="," if text.rfind(".")>text.rfind(",") else "."
        text=text.replace(thousands,"")
    text=text.replace(",",".")
    try:
        n=float(text)
        return n if math.isfinite(n) else None
    except ValueError:
        return None


def boolean(v):
    if isinstance(v,bool):
        return v
    key=normalize(v)
    if key in ("нет","0","false","no","недоступен","нет в наличии","отсутствует","под заказ"):
        return False
    if key in ("да","1","true","yes","есть","в наличии","доступен"):
        return True
    raise ValueError(f"Не удалось распознать логическое значение «{v}»")


def sequence(v):
    return [str(s).strip() for s in (v if isinstance(v,list) else re.split(r"[|;>,/]",str(v))) if str(s).strip()]


@lru_cache(2048)
def enum_value(k,v):
    if v in {value for value,_ in PATTERNS[k]}:
        return v
    return next((value for value,regex in PATTERNS[k] if regex.search(v)),v)


def explicit_value(k,v):
    if k in PATTERNS:
        value=enum_value(k,str(v))
        if k=="delivery" and value not in {key for key,_ in PATTERNS[k]}:
            return None
        return value
    if k=="vat":
        v=re.sub("ндс|vat","",str(v),flags=re.I)
    if k=="term_months":
        m=TERM.fullmatch(str(v).strip())
        if m:
            return int(m[1])*(1 if m[2].lower().startswith(("m","мес")) else 12)
    if k in ("registry","available","price_on_request"):
        return boolean(v)
    if k=="certs":
        codes={"фстэк":"fstec","фсб":"fsb","минобороны":"mo"}
        return [codes.get(s.lower(),s.lower()) for s in sequence(v)]
    if k in ("platforms","category_path"):
        return sequence(v)
    if k in ("pack","qty_min","qty_max","term_months","vat","sales_90d","views_90d"):
        if k=="vat" and "без" in str(v).lower():
            return 0
        n=number(v)
        if n is None or not n.is_integer() or n<0:
            raise ValueError(f"Некорректное значение {k} «{v}»")
        return int(n)
    if k in ("margin","popularity"):
        n=number(v)
        if n is None:
            raise ValueError(f"Некорректное значение {k} «{v}»")
        return min(1,max(0,n/100 if n>1 or "%" in str(v) else n))
    return str(v).strip()


def attributes(attrs):
    attrs=attrs or {}
    if isinstance(attrs,str):
        if attrs.lstrip().startswith(("{","[")):
            attrs=json.loads(attrs)
        else:
            attrs=dict(re.split(r"\s*[:=]\s*",part,maxsplit=1) for part in attrs.split(";") if re.search("[:=]",part))
    if isinstance(attrs,list):
        attrs={item["name"]:item.get("value") for item in attrs if isinstance(item,dict) and item.get("name")}
    if not isinstance(attrs,dict):
        raise ValueError("Ожидались характеристики в виде объекта")
    return attrs


class Enricher:
    def __init__(self, parser, categories):
        self.parser=parser
        self.categories=categories
        self.auto={k:{} for k in ("vendors","categories","families")}

    def convert(self, columns):
        evidence={}
        def overlay(values,source):
            for k,v in values.items():
                if v is not None and v!="" and k:
                    evidence[k]=Evidence(v,str(v),source,1 if source=="column" else .99)
        attrs=attributes(columns.get("attrs"))
        overlay({field_for(str(k)):v for k,v in attrs.items()},"attribute")
        overlay(columns.get("lic") or {},"column")
        overlay(columns,"column")
        def raw(k,default=None):
            return evidence[k].value if k in evidence else default
        name=raw("name")
        if not isinstance(name,str) or not name.strip():
            raise ValueError("Нет названия товара")
        name=name.strip()
        if (raw("offer_id") and isinstance(raw("lic"),dict) and
                isinstance(raw("family_id"),str) and raw("family_id") in self.parser.kb["families"] and
                raw("vendor_id") in self.parser.kb["vendors"] and columns.keys() <= Offer.model_fields.keys()):
            # A native Offer export already expresses unknowns through schema defaults.
            offer=Offer.model_validate(columns)
            if (offer.price is None or offer.price > 0) and all(math.isfinite(n) for n in (offer.price or 0,offer.margin,offer.popularity)):
                return offer,evidence,[]
        vendor=str(raw("vendor_id") or raw("vendor") or "").strip()
        hit=self.parser.lookup("vendors",vendor) if vendor else None
        vid=hit.value if hit else stable("auto_v_",normalize(vendor)) if vendor else None
        family=str(raw("family_id") or raw("family_name") or "")
        parsed=self.parser.parse(name,vid,family)
        base={**parsed,**evidence}
        kb=self.parser.kb
        fid=parsed["family_id"].value if "family_id" in parsed else None
        f=kb["families"].get(fid,{})
        vid=vid or f.get("vendor") or (parsed["vendor_id"].value if "vendor_id" in parsed else None)
        vendor_name=raw("vendor") or kb["vendors"].get(vid,{}).get("name") or vendor
        path=sequence(raw("category_path",[]))
        ref=str(raw("category_id",""))
        path=path or category_path(self.categories,ref) or category_path(self.categories,str(raw("category_path","")))
        if len(path)==1 and path[0] in self.categories:
            path=category_path(self.categories,path[0])
        cid=ref if ref in kb["categories"] else None
        pending=[]
        if not cid:
            for title in path:
                hit=self.parser.lookup("categories",title)
                parent=cid
                cid=hit.value if hit else stable("auto_c_",(parent or "")+"|"+normalize(title))
                if not hit:
                    pending.append(("categories",cid,dict(id=cid,title=title,parent=parent,synonyms=[])))
        cid=cid or f.get("category")
        edition=raw("edition")
        if edition and fid:
            hit=self.parser.editions[fid].match(str(edition),True)
            edition=hit.value if hit else str(edition)
        elif not edition:
            edition=parsed.get("edition")
            edition=edition.value if edition else None
        family_name=f.get("name") or raw("family_name") or parsed["core"].value
        if not fid:
            fid=stable("auto_f_",(vid or "")+"|"+normalize(family_name))
            pending.append(("families",fid,dict(id=fid,name=family_name,vendor=vid,category=cid,aliases=[],editions=[],summary="",catalog=True)))
        if vid and vid.startswith("auto_v_"):
            pending.append(("vendors",vid,dict(id=vid,name=vendor_name,aliases=[])))
        data={}
        lic={}
        for k,item in base.items():
            if k in ("action","model","metric","audience","term_months","pack","qty_min","qty_max"):
                lic[k]=explicit_value(k,item.value)
            elif k in ("version","language","delivery","registry","certs","description","kind","platforms",
                       "vat","available","url","image","popularity","margin","sales_90d","views_90d"):
                data[k]=explicit_value(k,item.value)
        if raw("term_months") is not None and raw("model") is None:
            lic["model"]="subscription"
        if lic.get("model")=="perpetual":
            lic.pop("term_months",None)
        if lic.get("qty_min") and lic.get("qty_max") and lic["qty_min"]>lic["qty_max"]:
            raise ValueError("Начало ступени больше её конца")
        if raw("pack") is not None:
            lic.pop("qty_min",None)
            lic.pop("qty_max",None)
        elif raw("qty_min") is not None or raw("qty_max") is not None:
            lic.pop("pack",None)
        price=number(raw("price"))
        price=price if price and price>0 else None
        por=boolean(raw("price_on_request",False)) or price is None
        stock=number(raw("stock"))
        if stock is not None:
            data.setdefault("available",stock>0)
        signals=[number(raw(k)) for k in ("sales_90d","views_90d","rating","stock")]
        data.setdefault("popularity",next((n/(n+1) for n in signals if n is not None and n>=0),.5))
        cost=number(raw("cost"))
        data.setdefault("margin",max(0,min(1,1-cost/price)) if cost is not None and price else .5)
        sku=str(raw("sku") or raw("id") or raw("source_id") or "").strip()
        ident=stable("o_",sku.casefold() or str(raw("offer_id") or json.dumps(columns,ensure_ascii=False,sort_keys=True,default=str)))
        offer=Offer(**data,offer_id=ident,name=name,sku=sku or None,vendor=vendor_name or None,vendor_id=vid,family_id=fid,
                    family_name=family_name,edition=edition,category_id=cid,category_path=path,lic=License(**lic),
                    attrs={str(k):(json.dumps(v,ensure_ascii=False,default=str) if isinstance(v,(list,dict)) else str(v)) for k,v in attrs.items()},price=None if por else price,price_on_request=por)
        # Trace normalized values as returned, retaining the original supplier notation.
        for k in list(base):
            if k in License.model_fields:
                value=getattr(offer.lic,k)
            elif k in Offer.model_fields:
                value=getattr(offer,k)
            else:
                continue
            if value!=base[k].value:
                base[k]=replace(base[k],value=value)
        for k,source_key in [("family_id","family_name"),("vendor_id","vendor"),("category_id","category_path")]:
            src=evidence.get(k) or evidence.get(source_key)
            if src and getattr(offer,k):
                base[k]=replace(src,value=getattr(offer,k))
        if "family_id" not in base:
            base["family_id"]=replace(parsed["core"],value=fid)
        if "category_id" not in base and cid:
            base["category_id"]=Evidence(cid,str(path),"column")
        if raw("term_months") is not None and raw("model") is None:
            base["model"]=replace(evidence["term_months"],value=offer.lic.model)
        if "available" not in base and stock is not None:
            base["available"]=replace(evidence["stock"],value=offer.available)
        for key,inputs in [("popularity",("sales_90d","views_90d","rating","stock")),("margin",("cost",))]:
            if key not in base:
                signal=next((evidence[k] for k in inputs if k in evidence and number(raw(k)) is not None),None)
                value=getattr(offer,key)
                base[key]=replace(signal,value=value) if signal else Evidence(value,"","default",1)
        return offer,base,pending

    def accept(self,offer,pending):
        for group,key,row in pending:
            saved=self.auto[group].setdefault(key,row)
            if group=="families" and offer.edition and all(e["id"]!=offer.edition for e in saved["editions"]):
                saved["editions"].append(dict(id=offer.edition,name=offer.edition,aliases=[]))
