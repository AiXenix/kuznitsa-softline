"""Supplier identifiers and facts, from explicit cells only."""
import json
import re
from datetime import datetime
from functools import lru_cache


def alias_list(values):
    if isinstance(values,str):
        if values.lstrip().startswith("["):
            try:
                values=json.loads(values)
            except ValueError:
                pass
        if isinstance(values,str):
            values=re.split(r"[|;,]",values)
    if not isinstance(values,(list,tuple)):
        values=[values]
    return list(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))


def flag(value):
    from .enrich import boolean
    try:
        return boolean(value)
    except ValueError:
        return None


@lru_cache(1024)
def added_date(raw):
    for fmt in ("%Y-%m-%d","%d.%m.%Y"):
        try:
            return datetime.strptime(raw[:10],fmt).date().isoformat()
        except ValueError:
            pass
    return None


def withdrawal(row):
    """Only an explicit sales or publication flag can withdraw a product."""
    from .mapping import field_for
    facts=row
    if row.get("attrs"):
        from .enrich import attributes
        try:
            attrs=attributes(row["attrs"])
        except (TypeError,ValueError):
            attrs={}
        facts={**{field_for(str(k)):v for k,v in attrs.items()},**row}
    for field in ("active","sold","withdrawn","status"):
        value=str(facts.get(field,"")).casefold().strip().replace("ё","е")
        if value.startswith("статус:"):
            value=value.partition(":")[2].strip()
        if ((field in ("active","sold") and value in {"0","false","n","no","нет"})
            or (field=="withdrawn" and value in {"1","true","y","yes","да"})
            or value in {"архив","архивный","снято","снят с продажи","снята с продажи","снято с продажи",
                          "не продается","discontinued","archived","inactive"}):
            return field,str(facts[field])
    return None


@lru_cache(1024)
def description_text(text):
    if not re.search(r"</?[a-zA-Z][^>]*>",text):
        return text
    from lxml import html
    root=html.fragment_fromstring(text,create_parent="div")
    for node in root.xpath(".//script|.//style"):
        node.drop_tree()
    return " ".join(" ".join(root.itertext()).split())


@lru_cache(512)
def supplier_metric(unit):
    from .nameparse import PATTERNS
    from .enrich import enum_value
    text=unit.strip().casefold()
    if "одновр" in text:
        return "concurrent"
    if text in {"час","часы","часов","чел.-ч","hour","hours"}:
        return "other"
    metric=enum_value("metric",text)
    return metric if any(key==metric for key,_ in PATTERNS["metric"]) else None


# Explicit offer properties which are copied from columns to attrs.
SUPPLIER_ATTRS = ("status","warehouse","stock","period","country","analog_of","registry_no","certs",
                  "operation","unit","qty_min","qty_max","term_months","delivery","series","edition",
                  "fstec","fsb","barcode")


def attribute_usage(row,attrs,extra):
    """Count populated input names before decorate adds canonical copies."""
    from .mapping import attribute_key
    mapped=[]
    unknown=set(extra)
    for name,value in attrs.items():
        if value in (None,"",[],{}):
            continue
        key=attribute_key(name)
        if key:
            mapped.append(key)
        elif row.get("prices") and (name=="Тип цены" or name.startswith("Цена · ")):
            continue
        else:
            unknown.add(name)
    # Some adapters also expose the same attribute as a top-level column.
    columns=(k for k in (*SUPPLIER_ATTRS,"task","aliases","prices") if row.get(k) not in (None,"",[],{}))
    mapped.extend(set(columns).difference(mapped))
    return mapped,unknown


def decorate(row,raw_attrs):
    from .enrich import number
    attrs=dict(raw_attrs)
    from .mapping import attribute_key
    quantity=None
    tags=[]
    for header,value in list(attrs.items()):
        key=attribute_key(header)
        if key=="quantity":
            quantity=re.sub(r"\s*(?:шт|лиц)\.?$", "", str(value).strip(), flags=re.I).strip()
        elif key=="aliases" and value:
            tags.extend(alias_list(value))
        elif key and value not in (None,"",[]):
            row.setdefault(key,value)
    if tags:
        row.setdefault("aliases",list(dict.fromkeys(tags)))
    if quantity and not any(k in row for k in ("pack","qty_min","qty_max")):
        band=re.fullmatch(r"(?:от\s+)?(\d+)\s*(?:[-–—]|до)\s*(\d+)",quantity,re.I)
        if band:
            row.update(qty_min=band[1],qty_max=band[2])
        elif quantity.isdecimal() and int(quantity)>0:
            row["pack"]=quantity
    if "registry" in row and flag(row["registry"]) is None and re.fullmatch(r"№?\s*\d[\d./-]*",str(row["registry"])):
        row.setdefault("registry_no",str(row["registry"]))
        row["registry"]=True
    if isinstance(row.get("description"),str):
        row["description"]=description_text(row["description"])
    if row.get("series"):
        row.setdefault("family_name",row["series"])
    period=str(row.get("period","")).casefold()
    if "бессроч" in period or "бессроч" in str(row.get("term_months","")).casefold():
        row.setdefault("model","perpetual")
    else:
        months=re.search(r"(\d+)\s*(мес|год|лет|year|month)",period)
        if months:
            row.setdefault("term_months",int(months[1])*(1 if months[2] in ("мес","month") else 12))
        elif period=="учебный год":
            row.setdefault("term_months",12)
    certs=[k for k in ("fstec","fsb") if row.get(k) and flag(row[k]) is not False]
    if any(k in row for k in ("fstec","fsb")) and "certs" not in row:
        row["certs"]=certs
    if row.get("registry_no"):
        row.setdefault("registry",flag(row["registry_no"]) is not False)
    operation=str(row.get("operation","")).casefold().replace("ё","е")
    for fragment,key,value in [("продлен","action","renewal"),("миграц","action","crossgrade"),
            ("новая","action","new"),("первич","action","new"),("академ","audience","edu"),("госучреж","audience","gov")]:
        if fragment in operation:
            row.setdefault(key,value)
    if operation and "action" not in row:
        from .enrich import enum_value
        from .nameparse import RULES
        action=enum_value("action",operation)
        if action in RULES["action"]:
            row["action"]=action
    if isinstance(row.get("analog_of"),list):
        row["analog_of"]="; ".join(map(str,row["analog_of"]))
    if row.get("unit"):
        metric=supplier_metric(str(row["unit"]))
        if metric:
            row.setdefault("metric",metric)
    stock=number(row.get("stock"))
    availability=flag(row.get("in_stock",row.get("available")))
    country=str(row.get("country","")).strip().casefold()
    days=str(row.get("delivery_days","")).casefold()
    nums=re.findall(r"\d+",days)
    added=added_date(str(row["added_at"])) if row.get("added_at") else None
    priority=dict(in_stock=stock>0 if stock is not None else availability,
                  delivery_days=int(nums[-1]) if nums else 0 if days in ("сегодня","today") else None,
                  added_at=added,promo=flag(row.get("promo")),domestic=flag(row.get("domestic")))
    if priority["in_stock"] is not None:
        row.setdefault("available",priority["in_stock"])
    if priority["domestic"] is None:
        priority["domestic"]=True if flag(row.get("registry")) else country in ("ru","rus","россия","рф","russia") if country else None
    from .join import identifiers
    if not row.get("source_id"):
        strong_id=next((row[k] for k in ("id","guid","store_id") if row.get(k)),None)
        if strong_id is not None:
            row["source_id"]=strong_id
    ids=identifiers(row)
    if not row.get("sku") and ids:
        row["sku"]=row.get("supplier_sku") or ids[0]
    if attrs:
        for key in ("vendor","registry","metric","pack"):
            if key in row:
                attrs[key]=row[key]
    for k in SUPPLIER_ATTRS:
        if k in row:
            attrs[k]=row[k]
    if "term_months" in attrs:
        from .enrich import explicit_value
        term=explicit_value("term_months",attrs["term_months"])
        if term is None:
            attrs.pop("term_months")
        else:
            attrs["term_months"]=term
    if row.get("prices"):
        attrs["prices"]=row["prices"]
    if row.get("task"):
        attrs["task"]=row["task"]
        row.setdefault("description",row["task"])
    if row.get("aliases"):
        attrs["aliases"]=json.dumps(alias_list(row["aliases"]),ensure_ascii=False)
    if ids:
        attrs["source_id"]=ids[0]
        attrs["source_ids"]=json.dumps(ids,ensure_ascii=False)
    for k,v in priority.items():
        if v is not None:
            attrs[k]=json.dumps(v) if isinstance(v,bool) else str(v)
    if "certs" in attrs:
        from .enrich import explicit_value
        attrs["certs"]=json.dumps(explicit_value("certs",attrs["certs"]),ensure_ascii=False)
    if str(row.get("delivery","")).casefold() in {"дистанционно","очно","на площадке","выезд","remote","on site"}:
        row["delivery"]="service"
    row["attrs"]=attrs
    return dict(source_id=ids[0] if ids else None,source_ids=ids,**priority)


def prices_with_keys(named):
    from .mapping import price_key,primary_retail
    result=dict(named)
    retail=primary_retail(named)
    if retail is not None:
        result.setdefault("retail",named[retail])
    for label,amount in named.items():
        key=price_key(label)
        if key:
            result.setdefault(key,amount)
    return result


def wire_attrs(attrs):
    """Use structured values as soon as the shared Offer reader supports them."""
    from kuznitsa.schema import Offer
    if Offer.model_fields["attrs"].annotation==dict[str,str]:
        return attrs
    result=dict(attrs)
    for key in ("extra","aliases","certs","source_ids","prices"):
        value=result.get(key)
        if isinstance(value,str):
            try:
                parsed=json.loads(value)
            except ValueError:
                continue
            if isinstance(parsed,(list,dict)):
                result[key]=parsed
    if isinstance(result.get("prices"),dict):
        result["prices"]=prices_with_keys(result["prices"])
    return result
