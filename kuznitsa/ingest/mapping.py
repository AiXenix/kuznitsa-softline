"""Canonical field names and supplier header recognition."""
import re
from functools import lru_cache
from .nameparse import normalize
from kuznitsa.schema import Offer, License

NAMES = {
    "currency":"валюта|currency code|currencyId", "name":"номенклатура|наименование|название|наименование товара|название товара|товар|product name|product|title|model name",
    "sku":"артикул|арт|код товара|код номенклатуры|код производителя|part number|vendorCode|product code|pn",
    "price":"цена|стоимость|цена руб|цена с ндс|розничная цена|розница|цена продажи|price rub|retail price|price usd|unit price usd|цена usd|unit price",
    "vendor":"вендор|производитель|бренд|brand|manufacturer", "category_path":"категория|category|раздел|путь категории|группа товаров|категория товара|категории",
    "description":"описание|описание товара|аннотация|описание продукта", "attrs":"атрибуты|характеристики|attributes|params|param",
    "available":"доступен|наличие|в наличии|availability|in stock", "stock":"остатки|остаток|количество на складе|stock quantity",
    "vat":"ндс|ставка ндс|vat rate", "url":"ссылка|ссылка на товар|адрес", "category_id":"код категории|categoryId",
    "parent":"parentId|parent id|родитель|код родителя", "id":"ид|идентификатор",
    "family_name":"семейство|линейка|family", "edition":"редакция", "version":"версия",
    "sales_90d":"продажи|продано|sales", "views_90d":"просмотры|views", "rating":"рейтинг",
    "cost":"закупка|закупочная цена|себестоимость|purchase price", "margin":"маржа|маржинальность|margin percent",
    "popularity":"популярность", "action":"действие|тип лицензии", "model":"модель лицензии",
    "metric":"метрика|единица лицензирования", "term_months":"срок|срок мес|срок в месяцах|duration",
    "qty_min":"от|минимальное количество|minQuantity", "qty_max":"до|максимальное количество|maxQuantity",
    "pack":"пакет|размер пакета", "delivery":"поставка|тип поставки", "registry":"реестр|реестр по",
    "audience":"аудитория|сегмент", "certs":"сертификаты", "language":"язык", "platforms":"платформы",
}
NAMES.update(kind="тип товара|вид товара", image="изображение|картинка|picture",
             price_on_request="цена по запросу|по запросу", sku=NAMES["sku"]+"|article| артикул поставщика|product sku")
ALIASES = {normalize(k):k for k in {*Offer.model_fields,*License.model_fields,*NAMES}}
for field, aliases in NAMES.items():
    ALIASES.update({normalize(alias):field for alias in aliases.split("|")})


@lru_cache(4096)
def field_for(header):
    key=normalize(header)
    direct=ALIASES.get(key)
    if direct:
        return direct
    if key.startswith("lic ") and key[4:] in ALIASES:
        return ALIASES[key[4:]]
    return None


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
