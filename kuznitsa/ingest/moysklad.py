"""Join locally exported MoySklad Remap pages by entity identity, without following URLs."""
import json
from collections import defaultdict

from .enrich import number
from .mapping import attribute_key, primary_retail


ITEM_TYPES = {"product", "service", "bundle", "variant"}
CATALOGS = ITEM_TYPES | {"assortment"}
ROLES = {"productfolder": "categories", "stock": "stock"}


def meta(obj):
    value = obj.get("meta") if isinstance(obj, dict) else None
    return value if isinstance(value, dict) else {}


def identifier(obj):
    if isinstance(obj, str):
        return obj.split("?", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    if isinstance(obj, dict):
        return str(obj.get("id") or identifier(meta(obj).get("href", "")))
    return ""


def kind(obj):
    info = meta(obj)
    parts = str(info.get("href", "")).partition("?")[0].lower().strip("/").split("/")
    if "stock" in parts and "report" in parts:
        return "stock"
    if "entity" in parts:
        idx = parts.index("entity") + 1
        if idx < len(parts):
            return parts[idx]
    return str(info.get("type", "")).lower().removesuffix("list")


def page(obj):
    """Recognise by endpoint or structured row fields; filenames carry no meaning."""
    if isinstance(obj, list) and obj and isinstance(obj[0], dict) and (
            kind(obj[0]) in CATALOGS | ROLES.keys() or "assortmentId" in obj[0]):
        obj = {"rows": obj}
    if not isinstance(obj, dict):
        return None
    rows = obj.get("rows", obj.get("stock"))
    if not isinstance(rows, list):
        return None
    endpoint = kind(obj)
    sample = next((r for r in rows if isinstance(r, dict)), {})
    if endpoint not in CATALOGS | ROLES.keys():
        if "stock" in obj or ("stock" in sample or "quantity" in sample) and "salePrices" not in sample and (
                kind(sample) in ITEM_TYPES or "assortment" in sample or "assortmentId" in sample
                or "size" in meta(obj) and "offset" in meta(obj)):
            endpoint = "stock"
        elif kind(sample) in CATALOGS | ROLES.keys():
            endpoint = kind(sample)
        elif any(k in sample for k in ("salePrices", "productFolder", "externalCode", "characteristics")):
            endpoint = "variant" if "characteristics" in sample and "product" in sample else "assortment"
        elif "pathName" in sample and set(sample) <= {"id", "name", "pathName", "meta", "productFolder"}:
            endpoint = "productfolder"
        else:
            return None
    return endpoint, rows, {k:meta(obj)[k] for k in ("size","offset") if k in meta(obj)}


def read(path):
    from .adapters import encoding
    with path.open(encoding=encoding(path)) as stream:
        return page(json.load(stream))


def label(value):
    return value.get("name") if isinstance(value, dict) else value


def aliases(item):
    return [str(item[k]) for k in ("code","article","externalCode")
            if item.get(k) is not None and item[k] != ""]


def offer_fields(item):
    ids = [identifier(item), *aliases(item)]
    attrs = {}
    for field in ("attributes", "characteristics"):
        pairs = item.get(field)
        if not isinstance(pairs, list):
            continue
        for pair in pairs:
            if isinstance(pair, dict) and isinstance(pair.get("name"),str):
                attrs[pair["name"]] = label(pair.get("value"))
    row = dict(name=item.get("name"), source_id=identifier(item), sku=item.get("article") or item.get("code"),
               description=item.get("description"), source_ids=[str(v) for v in ids if v], attrs=attrs,
               country=label(item.get("country")), unit=label(item.get("uom")))
    for field in ("uom","country"):
        ref = item.get(field)
        if isinstance(ref,dict) and identifier(ref):
            attrs[field+"_id"] = identifier(ref)
    if item.get("archived") is True:
        row["active"] = False
    prices = {}
    for entry in item["salePrices"] if isinstance(item.get("salePrices"),list) else ():
        if not isinstance(entry, dict):
            continue
        title = label(entry.get("priceType"))
        amount = number(entry.get("value"))
        if isinstance(title,str) and title and amount is not None:
            prices[title] = round(amount / 100, 2)
    if prices:
        retail = primary_retail(prices)
        default = next((title for title in prices if title.casefold() in {"цена продажи","основная","базовая","sale price"}),None)
        if retail or default:
            row["price"] = prices[retail or default]
        elif len(prices)==1:
            row["price"] = next(iter(prices.values()))
        row["prices"] = prices
    return {k:v for k,v in row.items() if v is not None and v != ""}


def prepare(files):
    """Collect product and variant pages before applying references and stock receipts."""
    items, parents, folders = {}, {}, {}
    entity_aliases = defaultdict(set)
    stock_records = []
    stock = {}
    receipts, tables = {}, {}
    for path in files:
        if path.suffix.lower() != ".json" or (payload := read(path)) is None:
            continue
        endpoint, records, pagination = payload
        tables[path] = []
        receipt = receipts[path] = dict(columns={}, unused=[], reference_rows=0, references=0,
                                        page={**pagination,"rows":len(records)}, linked_rows=set())

        def collect(item, endpoint, num, parent=""):
            if not isinstance(item, dict):
                receipt["reference_rows"] += 1
                return
            entity = kind(item) or endpoint
            key = identifier(item)
            if endpoint == "stock":
                available = number(item.get("quantity"))
                if available is None:
                    available = number(item.get("stock"))
                if available is not None:
                    stock_records.append((path, num, item, available))
                receipt["reference_rows"] += 1
            elif entity == "productfolder":
                if key and item.get("name"):
                    folders[key] = item
                    receipt["linked_rows"].add(num)
                    receipt["references"] += 1
                receipt["reference_rows"] += 1
            elif key and entity in CATALOGS:
                entity_aliases[key].update(aliases(item))
                if key in items:
                    # Assortment pages and expanded variants can repeat the same entity.
                    old, owner, line = items[key]
                    items[key] = ({**item, **old}, owner, line)
                    receipt["reference_rows"] += 1
                    receipt["linked_rows"].add(num)
                    receipt["references"] += 1
                else:
                    items[key] = (item, path, num)
                parent = identifier(item.get("product")) or parent
                if parent:
                    parents[key] = parent
                variants = item.get("variants") or []
                if isinstance(variants, dict):
                    variants = variants.get("rows", [])
                for variant in variants if isinstance(variants,list) else ():
                    collect(variant, "variant", num, key)
            else:
                receipt["reference_rows"] += 1

        for num, record in enumerate(records, 1):
            collect(record, endpoint, num)

    def folder_path(item):
        folder = item.get("productFolder") or {}
        folder = folders.get(identifier(folder), folder)
        if isinstance(folder, dict) and isinstance(folder.get("name"),str):
            branch = str(folder.get("pathName") or "").strip("/")
            return branch if branch.split("/")[-1]==folder["name"] else "/".join(filter(None, (branch, folder["name"])))
        return item.get("pathName")

    templates = set(parents.values())
    by_code = defaultdict(set)
    parent_names = {}
    for key, (item, _, _) in items.items():
        if key in parents and item.get("name"):
            parent_names.setdefault(parents[key],str(item["name"]).split(" (",1)[0])
        for field in ("code", "article", "externalCode"):
            if item.get(field):
                by_code[str(item[field])].add(key)
    for path, num, item, available in stock_records:
        key = (identifier(item.get("assortment")) or identifier(item.get("variant"))
               or identifier(item.get("product")) or identifier(item) or str(item.get("assortmentId") or ""))
        if not key:
            candidates = [by_code[str(item[k])] for k in ("code","article","externalCode")
                          if str(item.get(k)) in by_code]
            matches = set.intersection(*candidates) if candidates else set()
            key = next(iter(matches)) if len(matches)==1 else ""
        if key in items and key not in templates:
            stock.setdefault(key, available)
            entity_aliases[key].update(aliases(item))
            receipts[path]["linked_rows"].add(num)
            receipts[path]["references"] += 1
    for key, (item, path, num) in items.items():
        if key in templates:
            receipts[path]["linked_rows"].add(num)
            receipts[path]["reference_rows"] += 1
            receipts[path]["references"] += 1
            continue
        base = items.get(parents.get(key))
        row = offer_fields(item)
        if key in parents:
            parent = base[0] if base else item.get("product")
            if not isinstance(parent,dict):
                parent = {}

            inherited = offer_fields(parent)
            overridden = {attribute_key(k) or k for k in row["attrs"]}
            base_attrs = {k:v for k,v in inherited["attrs"].items() if (attribute_key(k) or k) not in overridden}
            row = {**inherited, **row, "attrs": {**base_attrs, **row["attrs"]},
                   "source_ids": list(dict.fromkeys(row["source_ids"] + inherited["source_ids"] + [parents[key]]))}
            row["family_name"] = parent.get("name") or parent_names.get(parents[key]) or parents[key]
            category = folder_path(item) or folder_path(parent)
        else:
            category = folder_path(item)
        if category:
            row["category_path"] = category
        if key in stock:
            row["stock"] = stock[key]
        elif item.get("quantity", item.get("stock")) is not None:
            row["stock"] = item.get("quantity", item.get("stock"))
        extra_ids = entity_aliases[key] | entity_aliases.get(parents.get(key),set())
        row["source_ids"] = list(dict.fromkeys([*row["source_ids"], *sorted(extra_ids)]))
        row["_variant_identity"] = "moysklad:" + key
        tables[path].append((num, row))

    return tables, {str(p):r for p,r in receipts.items()}
