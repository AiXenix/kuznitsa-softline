"""Interpret hierarchy and named price columns in a supplier worksheet."""
import re
from itertools import chain, pairwise

from .mapping import field_for, price_key, primary_retail
from .nameparse import normalize


TOTAL = re.compile(r"(?:итого|всего|общий итог|grand total|total)(?: по .*)?[:.]?", re.I)
OTHER_PRICE = re.compile(r"(?:цена )?(?:дилерская|закупочная|специальная)(?: (?:цена|price))?|для .+")
FOLDER = {"да", "true", "1", "группа", "папка"}


def price_types(headers, sample, sheet, explicit):
    """A retail column anchors a price matrix. Keep supplier labels as keys."""
    from .enrich import number
    retail = primary_retail(headers)
    prices_only = ("цен" in sheet.casefold() or "price" in sheet.casefold()
                   or not any(field_for(h) == "name" for h in headers))
    others = []
    for idx, label in enumerate(headers):
        if not label or label == retail or label in explicit.values():
            continue
        if price_key(label) or retail and OTHER_PRICE.fullmatch(normalize(label)):
            others.append(label)
        elif retail and prices_only and not field_for(label):
            cells = [r[idx] for r in sample if r and idx < len(r) and r[idx] not in (None, "")]
            if cells and all(number(str(v).replace("$", "")) is not None for v in cells):
                others.append(label)
    return retail, others


def parent_tree(rows, name, parent, codes, group):
    # A child can precede its parent. Resolve references only within this sheet.
    rows = list(rows)
    refs = {str(r[parent]).strip() for _, r in rows if r and r.get(parent) not in (None, "")}
    groups = {}
    folders = set()
    for num, row in rows:
        if not row or not row.get(name):
            continue
        title = str(row[name]).strip()
        identifiers = [str(row[k]).strip() for k in codes if row.get(k) not in (None, "")]
        marker = str(row.get(group, "")).strip().casefold()
        if marker in FOLDER or refs.intersection(identifiers) or title in refs:
            folders.add(num)
            link = (title, str(row[parent]).strip() if row.get(parent) is not None else "")
            groups[title] = link
            for ident in identifiers:
                groups[ident] = link
    for num, row in rows:
        if num in folders:
            continue
        if row:
            value = row.pop(parent, None)
            key = str(value).strip() if value is not None else ""
            path = []
            seen = set()
            while key and key not in seen:
                seen.add(key)
                if key not in groups:
                    path.extend(reversed([s.strip() for s in re.split(r"[/>]", key) if s.strip()]))
                    break
                title, key = groups[key]
                path.append(title)
            if path:
                row.setdefault("category_path", list(reversed(path)))
        yield num, row


def hierarchy(rows, header, explicit, layout, sheet):
    overrides = {label: field for field, label in explicit.items()}
    fields = {overrides.get(label, field_for(label)): label for label in header if label}
    name = fields.get("name")
    if not name:
        yield from rows
        return
    parent = fields.get("parent")
    if parent and ({"sku", "source_id", "attrs", "is_group"} & fields.keys() or "номенклатур" in sheet.casefold()):
        codes = [label for label in header if overrides.get(label, field_for(label)) in {"sku", "source_id", "id", "guid"}]
        yield from parent_tree(rows, name, parent, codes, fields.get("is_group"))
        return

    column = header.index(name) + 1
    styled = bool(layout["outline"]) or any(col == column for _, col in layout["indent"])
    product_columns = [fields[k] for k in ("sku", "price", "attrs") if k in fields]

    def entries():
        for num, row in rows:
            depth = layout["indent"].get((num, column), layout["outline"].get(num, 0))
            if not styled and row and isinstance(row.get(name), str):
                title = row[name].expandtabs().replace("\u00a0", " ")
                depth = len(title) - len(title.lstrip(" "))
            yield num, row, depth

    stack = []
    for (num, row, depth), (_, following, next_depth) in pairwise(chain(entries(), [(0, None, 0)])):
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if row and row.get(name):
            marked = str(row.get(fields.get("is_group"), "")).strip().casefold() in FOLDER
            product = any(row.get(label) not in (None, "") for label in product_columns)
            if marked or (following and next_depth > depth and (styled or not product)):
                stack.append((depth, str(row[name]).strip()))
                continue
            if stack:
                row.setdefault("category_path", [title for _, title in stack])
        yield num, row
