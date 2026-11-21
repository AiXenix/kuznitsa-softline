"""Canonical field names and supplier header recognition."""
import re
from functools import lru_cache
from .nameparse import normalize
from kuznitsa.schema import Offer, License

NAMES = {
    "currency_rate":"курс валюты|exchange rate",
    "currency":"валюта|currency code|currencyId|вал",
    "name":"номенклатура|наименование|название|наименование товара|название товара|товар|product name|product|title|model name|display name|displayName|label|caption",
    "sku":"артикул|арт|код товара|код номенклатуры|код производителя|part number|vendorCode|product code|pn|article|product sku|артикул изготовителя|manufacturer part number|artnumber",
    "price":"цена|стоимость|цена руб|цена с ндс|розничная цена|розница|цена продажи|price rub|retail price|price usd|unit price usd|цена usd|unit price|розничная|прайс|цена дилера",
    "vendor":"вендор|производитель|бренд|brand|manufacturer",
    "category_path":"категория|category|раздел|путь категории|группа товаров|категория товара|категории|путь группы|group path|разделы|путь разделов|путь раздела|section path|разделы каталога",
    "description":"описание|описание товара|аннотация|описание продукта|detail text|preview text|детальное описание|описание для анонса",
    "attrs":"атрибуты|характеристики|attributes|params|param",
    "available":"доступен|наличие|в наличии|availability|in stock",
    "stock":"остатки|остаток|количество на складе|stock quantity|свободно|доступно",
    "vat":"ндс|ставка ндс|vat rate",
    "url":"ссылка|ссылка на товар|адрес",
    "category_id":"код категории|categoryId",
    "parent":"parentId|parent id|родитель|код родителя",
    "id":"ид|идентификатор",
    "family_name":"семейство|линейка|family",
    "version":"версия",
    "sales_90d":"продажи|продано|sales",
    "views_90d":"просмотры|views",
    "rating":"рейтинг",
    "cost":"закупка|закупочная цена|себестоимость|purchase price",
    "margin":"маржа|маржинальность|margin percent",
    "popularity":"популярность",
    "action":"действие",
    "model":"модель лицензии",
    "metric":"метрика|единица лицензирования",
    "term_months":"срок|срок действия|срок лицензии|срок мес|срок в месяцах|duration",
    "qty_min":"от|минимальное количество|minQuantity|нижний порог",
    "qty_max":"до|максимальное количество|maxQuantity|верхний порог",
    "pack":"пакет|размер пакета",
    "delivery":"поставка|тип поставки|вариант поставки",
    "registry":"реестр|реестр по",
    "audience":"аудитория|сегмент",
    "certs":"сертификаты",
    "language":"язык",
    "platforms":"платформы",
    "prices":"виды цен",
    "is_group":"это группа|этогруппа|это папка|тип строки",
    "kind":"тип товара|вид товара",
    "image":"изображение|картинка|picture",
    "price_on_request":"цена по запросу|по запросу",
    "source_id":"code|код|код ут|номенклатура код|код учетной системы|код учётной системы|код 1с|erp id|item id|internal code|erpId|код элемента|внутренний код",
    "guid":"uuid|uid|ид guid",
    "store_id":"код витрины|store id|web id|storefront code|storeCode|storefrontId|код сайта",
    "supplier_sku":"артикул поставщика|supplier sku|supplier part number|supplierSku",
    "active":"активность|активен|is active|активность элемента",
    "sold":"продается|в продаже|is sold",
    "withdrawn":"снят с продажи|снята с продажи|снято с продажи|discontinued",
    "source_ids":"source ids",
    "aliases":"также ищут|жаргон|синонимы|теги поиска|ключевые слова|keywords|synonyms|search tag|tags",
    "task":"назначение|решаемая задача|задача|для чего|purpose|use case",
    "series":"серия|product series",
    "edition":"редакция|исполнение|версия продукта",
    "operation":"операция|вид лицензии|тип лицензии|вид поставки|license operation",
    "period":"период|license period",
    "unit":"единица|ед изм|за единицу|ед лицензирования|единица измерения|uom",
    "country":"страна|страна происхождения|страна разработки|производство|country of origin",
    "registry_no":"запись рпо|номер в реестре|реестр минцифры",
    "analog_of":"замещает|альтернатива|замена для|аналог для|вместо|alternative to",
    "fstec":"фстэк",
    "fsb":"фсб",
    "delivery_days":"отгрузка|срок поставки|lead time",
    "barcode":"ean 13|ean|штрихкод",
    "status":"состояние|статус|статус товара|product status",
    "warehouse":"склад|warehouse",
    "promo":"акция",
    "added_at":"дата добавления|дата поступления",
    "domestic":"отечественное по",
    "in_stock":"в наличии на складе",
}
ALIASES = {normalize(k):k for k in {*Offer.model_fields,*License.model_fields,*NAMES}}
for field, aliases in NAMES.items():
    ALIASES.update({normalize(alias):field for alias in aliases.split("|")})


BUSINESS_ATTRS = {"analog_of","aliases","task","edition","operation","country","registry_no"}
COMPACT_ATTRS = {label.replace(" ",""):key for label,key in ALIASES.items() if key in BUSINESS_ATTRS}


# Price type labels use the same spelling normalization as SKU attributes.
PRICE_TYPES = {
    "retail": ("розничная", "розница", "retail", "цена продажи", "sale price"),
    "project": ("проектная", "проект", "для проектов", "проектный", "проектам", "project"),
    "partner": ("партнерская", "для партнеров", "партнер", "партнерам", "партнеры", "partner"),
    "gov": ("для госзаказчиков", "для гос заказчиков", "для государственных заказчиков",
            "для госучреждений", "для госсектора", "госзаказ", "госзаказчики", "госсектор", "гос", "государственная", "government", "gov"),
    "wholesale": ("оптовая", "опт", "wholesale"),
}
PRICE_ALIASES = {name:key for key,names in PRICE_TYPES.items() for name in (*names,key)}


@lru_cache(1024)
def price_key(label):
    name=normalize(label)
    if name in PRICE_ALIASES:
        return PRICE_ALIASES[name]
    name=re.sub(r"\b(?:без|с) ндс(?: \d+)?\b","",name)
    words=[w for w in name.split() if w not in {"руб","рубли","rub","usd","rur"}]
    return (PRICE_ALIASES.get(" ".join(words))
            or PRICE_ALIASES.get(" ".join(w for w in words if w not in {"цена","price"})))


def retail_header(label):
    return price_key(label)=="retail"


def primary_retail(labels):
    candidates=[label for label in labels if retail_header(label)]
    # The literal wire key takes precedence, followed by explicit retail labels.
    if "retail" in candidates:
        return "retail"
    return next((s for s in candidates if any(w in normalize(s).split()
                 for w in ("розничная","розница","retail"))),next(iter(candidates),None))


@lru_cache(4096)
def field_for(header):
    if header in NAMES or header in Offer.model_fields or header in License.model_fields:
        return header
    key=normalize(header)
    if key.startswith("property "):
        key=key.removeprefix("property ")
    direct=ALIASES.get(key) or COMPACT_ATTRS.get(key.replace(" ",""))
    if direct:
        return direct
    if retail_header(header):
        return "price"
    if key.startswith("lic ") and key[4:] in ALIASES:
        return ALIASES[key[4:]]
    return None


@lru_cache(4096)
def attribute_key(label):
    if normalize(label) in {"количество","кол во","количество лицензий"}:
        return "quantity"
    return field_for(label)


def infer(headers, sample, explicit, parser):
    mapping = {h:field_for(h) for h in headers}
    for field,header in explicit.items():
        if header in headers:
            if field not in ALIASES.values():
                raise ValueError(f"Неизвестное поле mapping: {field}")
            mapping = {h:(None if v==field else v) for h,v in mapping.items()}
            mapping[header] = field
    for h in headers:
        if mapping[h]:
            continue
        values = [str(r[h]).strip() for r in sample if r and r.get(h) not in ("",None)]
        if not values:
            continue
        checks = [("url",lambda v:v.startswith(("https://","http://"))),
                  ("attrs",lambda v:v.startswith(("{","[","{'")) or bool(re.fullmatch(r"[^:;]+:[^;]+(?:;[^:;]+:[^;]+)+",v))),
                  ("vat",lambda v:v.lower() in {"без ндс","ндс 0%","ндс 20%","ндс 22%","10%","20%","22%"}),
                  ("available",lambda v:v.lower() in {"в наличии","нет в наличии","под заказ","true","false","есть","отсутствует"}),
                  ("description",lambda v:len(v)>110 and (v.endswith(".") or v.startswith("<"))),
                  ("sku",lambda v:re.fullmatch(r"(?=.*\d)[A-Za-zА-Яа-я0-9]+[-/][\w/-]+",v)),
                  ("price",lambda v:re.fullmatch(r"[\d\s.,]+(?:\s*(?:₽|руб\.?))?",v)),
                  ("vendor",lambda v:normalize(v) in parser.index["vendors"].aliases),
                  ("category_path",lambda v:normalize(v) in parser.index["categories"].aliases or " > " in v),
                  ("name",lambda v:len(v.split())>=2 and parser.index["families"].match(v))]
        for field,test in checks:
            if field not in mapping.values() and sum(bool(test(v)) for v in values)>=len(values)*.8:
                mapping[h]=field
                break
    if "name" not in mapping.values():
        candidates=[]
        for header in headers:
            if mapping[header]:
                continue
            values=[str(r[header]) for r in sample if r and r.get(header)]
            if values and all(2<=len(v.strip())<=200 and re.search(r"[^\W\d_]",v) for v in values):
                candidates.append(header)
        if len(candidates)==1:
            mapping[candidates[0]]="name"
    return mapping
