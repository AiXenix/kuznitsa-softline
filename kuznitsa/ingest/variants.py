"""Expand card/variant API payloads and CommerceML 2 classifiers and offers."""
from pathlib import Path
from lxml import etree

from .mapping import field_for, primary_retail
from .nameparse import normalize


def local(node):
    return etree.QName(node).localname if isinstance(node.tag,str) else ""


def children(node,name):
    return (c for c in node if local(c)==name)


def scalar(node,name):
    return next(((c.text or "").strip() for c in children(node,name)),"")


def nodes(node,path):
    parents=[node]
    for name in path.split("/"):
        parents=[c for p in parents for c in children(p,name)]
    return parents


def is_commerce(path):
    if Path(path).suffix.lower() not in {".xml",".yml"}:
        return False
    with open(path,"rb") as stream:
        first=next(iter(etree.iterparse(stream,events=("start",),resolve_entities=False,no_network=True)),None)
    return first is not None and local(first[1])=="КоммерческаяИнформация"


class Commerce:
    def __init__(self):
        self.groups={}
        self.properties={}
        self.values={}
        self.price_types={}

    def metadata(self,node):
        kind=local(node)
        key=scalar(node,"Ид")
        title=scalar(node,"Наименование")
        if not key:
            return
        if kind=="Группа":
            parent=next((scalar(p,"Ид") for p in node.iterancestors() if local(p)=="Группа"),None)
            self.groups[key]=(title,parent)
        elif kind=="Свойство":
            self.properties[key]=title
            for opt in nodes(node,"ВариантыЗначений/Справочник"):
                self.values[key,scalar(opt,"ИдЗначения")]=scalar(opt,"Значение")
        elif kind=="ТипЦены":
            self.price_types[key]=title

    def record(self,node):
        product=local(node)=="Товар"
        ident=scalar(node,"Ид")
        row={"source_id":ident,"name":scalar(node,"Наименование"),"sku":scalar(node,"Артикул"),
             "description":scalar(node,"Описание"),"barcode":scalar(node,"Штрихкод")}
        attrs={}
        for path in ("ЗначенияРеквизитов/ЗначениеРеквизита","ХарактеристикиТовара/ХарактеристикаТовара"):
            for req in nodes(node,path):
                attrs[scalar(req,"Наименование")]=scalar(req,"Значение")
        for prop in nodes(node,"ЗначенияСвойств/ЗначенияСвойства"):
            key=scalar(prop,"Ид")
            values=[(v.text or "").strip() for v in children(prop,"Значение")]
            attrs[self.properties.get(key,key)]="; ".join(self.values.get((key,v),v) for v in values)
        row["source_ids"]=[v for v in [scalar(node,"Код"),*(value for name,value in attrs.items()
                           if field_for(name) in ID_FIELDS)] if v]
        for name,value in attrs.items():
            key=field_for(name)
            if key and value and not row.get(key):
                row[key]=value
        row["attrs"]=attrs
        row["vendor"]=row.get("vendor") or next((scalar(v,"Наименование") for v in children(node,"Изготовитель")),"")
        unit=next(children(node,"БазоваяЕдиница"),None)
        if unit is not None:
            row["unit"]=unit.get("НаименованиеПолное") or unit.text
        groups=nodes(node,"Группы/Ид")
        if groups:
            from .adapters import category_path
            row["category_path"]=category_path(self.groups,groups[0].text)
        if product:
            row["_product"]=True
        else:
            row["_parent_id"]=ident.split("#",1)[0]
            stock=scalar(node,"Количество")
            if not stock:
                from .enrich import number
                counts=[number(s.get("КоличествоНаСкладе") or scalar(s,"Количество") or scalar(s,"КоличествоНаСкладе"))
                        for s in node.iter() if local(s) in {"Склад","Остаток"}]
                valid=[q for q in counts if q is not None]
                stock=sum(valid) if valid else None
            row["stock"]=stock
            prices=nodes(node,"Цены/Цена")
            def title(price):
                key=scalar(price,"ИдТипаЦены")
                return self.price_types.get(key) or scalar(price,"Представление") or key
            if prices:
                retail=primary_retail(title(p) for p in prices)
                price=next((p for p in prices if title(p)==retail),prices[0])
                row.update(price=scalar(price,"ЦенаЗаЕдиницу"),currency=scalar(price,"Валюта"))
                attrs["Тип цены"]=title(price)
                row["prices"]={}
                row["_field_currency"]={}
                for p in prices:
                    row["prices"][title(p)] = scalar(p,"ЦенаЗаЕдиницу")
                    row["_field_currency"][title(p)]=scalar(p,"Валюта").upper()
                    attrs["Цена · "+title(p)]=" ".join(filter(None,[scalar(p,"ЦенаЗаЕдиницу"),scalar(p,"Валюта")]))
        return {k:v for k,v in row.items() if v not in (None,"")}

    def read(self,path,metadata_only=False):
        tags=["Группа","Свойство","ТипЦены","Товар","Предложение"]
        with open(path,"rb") as stream:
            for _,node in etree.iterparse(stream,events=("end",),tag=["{*}"+t for t in tags],
                                          resolve_entities=False,no_network=True):
                kind=local(node)
                if kind in {"Свойство","Группа","ТипЦены"}:
                    self.metadata(node)
                elif metadata_only:
                    break
                else:
                    yield node.sourceline,self.record(node)
                node.clear()
                # Ancestor groups still need their Ид and Наименование until their end tag.
                if kind in {"Товар","Предложение"}:
                    while node.getprevious() is not None:
                        del node.getparent()[0]


VARIANTS={"variants","skus","offers","варианты","предложения","modifications","вариации"}
ID_FIELDS=("source_id","id","sku","guid","store_id","supplier_sku","barcode")
LABELS=("name","title","label","value","display name","название","наименование","значение","id","ид")


def flatten(obj):
    result={}
    def visit(container):
        for key,value in container.items():
            field=field_for(key)
            if isinstance(value,dict):
                if field=="attrs":
                    attrs=result.setdefault("attrs",{})
                    attrs.update(value)
                    visit(value)
                elif field=="prices":
                    result[key]=value
                elif field in {"vendor","family_name","category_path","name","edition",*ID_FIELDS}:
                    labels={normalize(k):v for k,v in value.items()}
                    chosen=next((labels[k] for k in LABELS if isinstance(labels.get(k),(int,str))),None)
                    if chosen is not None:
                        result.setdefault(key,chosen)
                    else:
                        visit(value)
                else:
                    if field=="price" and "amount" in value:
                        result[key]=value["amount"]
                        visit({k:v for k,v in value.items() if k!="amount"})
                    else:
                        visit(value)
            elif not isinstance(value,list) or field:
                result.setdefault(key,value)
    visit(obj)
    return result


def variant_values(base,child):
    """An explicit variant unit or band takes precedence over the parent licence."""
    row={**base,**child}
    if child.get("unit") and "metric" not in child:
        from .source_fields import supplier_metric
        metric=supplier_metric(str(child["unit"]))
        if metric:
            row["metric"]=metric
    bounds={"qty_min","qty_max","pack"}
    omitted=bounds-child.keys() if bounds.intersection(child) else set()
    for field in omitted:
        row.pop(field,None)
    attrs=base.get("attrs",{})
    extra=child.get("attrs",{})
    if isinstance(attrs,dict) and isinstance(extra,dict) and (attrs or extra):
        row["attrs"]={**{k:v for k,v in attrs.items() if field_for(k) not in omitted},**extra}
    return row


def nested_records(obj):
    if not isinstance(obj,dict):
        yield None
        return
    if "offer_id" in obj and isinstance(obj.get("lic"),dict):
        yield obj
        return
    def collections(node):
        for key,value in node.items():
            if normalize(key) in VARIANTS and isinstance(value,list):
                yield value
            elif isinstance(value,dict):
                yield from collections(value)
    base=flatten(obj)
    variants=list(collections(obj))
    if not variants:
        yield base
        return
    base={field_for(k) or k:v for k,v in base.items()}
    inherited=[base[k] for k in ID_FIELDS if base.get(k)]
    for items in variants:
        for child in items:
            for option in nested_records(child):
                if not option:
                    yield None
                    continue
                option={field_for(k) or k:v for k,v in option.items()}
                ids=[option[k] for k in ID_FIELDS if option.get(k)]
                row=variant_values(base,option)
                if base.get("name"):
                    row.setdefault("family_name",base["name"])
                    if option.get("name") and base["name"].casefold() not in str(option["name"]).casefold():
                        row["name"]=base["name"]+" "+str(option["name"])
                row["source_ids"]=[*ids,*option.get("source_ids",[]),*inherited]
                row["source_id"]=next(iter(ids),None)
                if not ids:
                    import json
                    row["_variant_identity"]=json.dumps([inherited,option],sort_keys=True,ensure_ascii=False)
                yield row
