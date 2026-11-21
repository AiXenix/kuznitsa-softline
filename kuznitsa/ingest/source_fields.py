"""Supplier identifiers and facts, from explicit cells only."""
import json
import re
from datetime import datetime
from functools import lru_cache


HEADERS={
    "source_id":"code|код|код ут|номенклатура код|код учетной системы|код учётной системы|код 1с|erp id|item id|internal code|erpId|код элемента|внутренний код",
    "description":"detail text|preview text|детальное описание|описание для анонса","name":"display name|displayName|label|caption","guid":"uuid|uid|ид guid","store_id":"код витрины|store id|web id|storefront code|storeCode|storefrontId|код сайта","supplier_sku":"артикул поставщика|supplier sku|supplier part number|supplierSku",
    "active":"активность|активен|is active|активность элемента","sold":"продается|в продаже|is sold",
    "withdrawn":"снят с продажи|снята с продажи|снято с продажи|discontinued",
    "source_ids":"source ids","aliases":"также ищут|жаргон|синонимы|ключевые слова|keywords|synonyms|search tag|tags",
    "task":"назначение|решаемая задача|задача|purpose|use case","sku":"артикул изготовителя|manufacturer part number|artnumber", "price":"прайс|цена дилера",
    "currency":"вал", "category_path":"путь группы|group path|разделы|путь разделов|путь раздела|section path|разделы каталога", "stock":"свободно|доступно",
    "series":"серия|product series","edition":"исполнение","operation":"операция|license operation",
    "period":"период|license period","unit":"за единицу|ед лицензирования|единица измерения|uom",
    "qty_min":"нижний порог","qty_max":"верхний порог","delivery":"вариант поставки",
    "country":"страна разработки|country of origin","registry_no":"запись рпо|номер в реестре",
    "analog_of":"альтернатива|замена для|аналог для|alternative to","fstec":"фстэк","fsb":"фсб",
    "delivery_days":"отгрузка|срок поставки|lead time","barcode":"ean 13|ean|штрихкод",
    "status":"состояние|статус|статус товара|product status","warehouse":"склад|warehouse","promo":"акция","added_at":"дата добавления|дата поступления","domestic":"отечественное по",
    "in_stock":"в наличии на складе"
}

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


def decorate(row):
    from .enrich import number
    from .enrich import attributes
    attrs=dict(attributes(row.get("attrs")))
    from .mapping import field_for
    for header,value in list(attrs.items()):
        key=field_for(header)
        if key:
            row.setdefault(key,value)
    if isinstance(row.get("description"),str):
        row["description"]=description_text(row["description"])
    if row.get("series"):
        row.setdefault("family_name",row["series"])
    period=str(row.get("period","")).casefold()
    if "бессроч" in period:
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
    for k in ("status","warehouse","stock","period","country","analog_of","registry_no","certs","operation","unit","qty_min","qty_max","term_months","delivery","series","edition","fstec","fsb","barcode"):
        if k in row:
            attrs[k]=row[k]
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


def wire_attrs(attrs):
    """Use structured values as soon as the shared Offer reader supports them."""
    from kuznitsa.schema import Offer
    if Offer.model_fields["attrs"].annotation==dict[str,str]:
        return attrs
    result=dict(attrs)
    for key in ("extra","aliases","certs","source_ids"):
        value=result.get(key)
        if isinstance(value,str):
            try:
                parsed=json.loads(value)
            except ValueError:
                continue
            if isinstance(parsed,(list,dict)):
                result[key]=parsed
    return result
