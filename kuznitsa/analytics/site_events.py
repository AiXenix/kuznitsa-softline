"""Нормализация событий поиска сайта и сортировка по времени на диске."""
import hashlib
import json
import re
from collections import Counter

from .store import dump


FIELDS = {
    "kind": ("event", "type", "action", "event_type"),
    "ts": ("ts", "time", "timestamp", "datetime"),
    "session_id": ("session", "sid", "session_id", "visit_id"),
    "q": ("query", "q", "term", "search_term"),
    "n_cards": ("found", "results_count", "result_count", "n_cards", "results", "hits"),
    "item": ("item", "sku", "product_id", "offer_id", "card_id", "item_id"),
    "items": ("items", "products", "cards"),
    "position": ("position", "rank"),
    "client_id": ("client_id", "client", "user_id"),
    "segment": ("segment",),
    "revenue": ("revenue", "value", "amount", "total"),
    "currency": ("currency",),
    "qty": ("qty", "quantity"),
    "event_id": ("event_id", "eid"),
    "order_id": ("order_id", "transaction_id"),
    "search_id": ("search_id",),
}
NAMES = {
    "search": ("search", "site_search", "search_request", "search_submit", "submit_search", "query", "поиск", "поисковый запрос"),
    "impression": ("impression", "impressions", "view", "results", "results_view", "search_results",
                   "view_results", "view_search_results", "serp_view", "show_results", "results_shown", "search_results_shown", "view_item_list", "show", "results_impression", "serp_impression",
                   "search_impression", "search_results_view", "показ", "показ выдачи"),
    "click": ("click", "item_click", "product_click", "result_click", "search_click", "select_item", "click_result", "клик"),
    "cart": ("cart", "add_cart", "cart_add", "add_to_cart", "add_to_basket", "корзина", "добавление в корзину"),
    "order": ("order", "purchase", "order_created", "order_completed", "order_placed", "заказ", "покупка"),
}
KINDS = {name:kind for kind,names in NAMES.items() for name in names}
ALIASES = {name:field for field,names in FIELDS.items() for name in names}


def first(row, field):
    return next((row[k] for k in FIELDS[field] if row.get(k) not in (None,"")),None)


def event_kind(row):
    for key in FIELDS["kind"]:
        value = re.sub(r"(?<=[a-z])(?=[A-Z])","_",str(row.get(key,""))).lower().strip()
        kind = KINDS.get(value) or KINDS.get(re.sub(r"[ .-]+","_",value))
        if kind:
            return kind


def sniff_rows(rows):
    if not any(event_kind(row) and first(row,"session_id") is not None and first(row,"ts") is not None for row in rows):
        return None
    return dict(kind="search_log", format="site_events", confidence=.99,
                columns={k:ALIASES[k] for row in rows for k in row if k in ALIASES},
                reason="События поиска сайта с идентификатором сессии и временем")


def item_code(value):
    if isinstance(value,dict):
        value = first(value,"item") or value.get("id")
    return str(value).strip() if isinstance(value,(str,int)) else None


def normalize_row(row, timestamp, amount, number):
    kind = event_kind(row)
    if not kind:
        raise ValueError("Неизвестный тип события")
    sid = first(row,"session_id")
    if not isinstance(sid,(str,int)) or not str(sid).strip():
        raise ValueError("Нет идентификатора сессии")
    try:
        ts = timestamp(str(first(row,"ts")),None)
    except (TypeError,ValueError):
        raise ValueError("Неверное время события") from None
    q = first(row,"q")
    if kind=="search" and (not isinstance(q,str) or not q.strip() or len(q)>1500):
        raise ValueError("Нет корректного текста поиска")
    q = q.strip() if isinstance(q,str) else None
    size = None
    ids = []
    if kind in ("search","impression"):
        shown = next((row[k] for k in (*FIELDS["items"],"results","hits") if isinstance(row.get(k),list)),None)
        if shown is not None:
            ids = [code for item in shown if (code:=item_code(item))]
        count = next((row[k] for k in FIELDS["n_cards"] if row.get(k) not in (None,"") and not isinstance(row[k],list)),None)
        size = amount(count) if count is not None else len(shown) if shown is not None else None
    item = first(row,"item")
    position = first(row,"position")
    if position is None and isinstance(item,dict):
        position = first(item,"position")
    qty = first(row,"qty")
    value = first(row,"revenue") if kind=="order" else None
    currency = str(first(row,"currency") or "RUB").upper()
    value = number(value) if value is not None and currency in ("RUB","RUR","₽") else None
    result = dict(kind=kind,ts=ts,sid=str(sid).strip(),q=q,size=size,ids=ids,item=item_code(item),
                  position=amount(position) if position is not None else None, qty=amount(qty) if qty is not None else None,
                  value=value, client=str(first(row,"client_id") or "guest"),segment=str(first(row,"segment") or "unknown"))
    native = first(row,"event_id")
    if kind=="order" and first(row,"order_id") is not None:
        native=first(row,"order_id")
    if kind=="search" and first(row,"search_id") is not None:
        native=first(row,"search_id")
    signature = [str(sid),kind,str(native)] if native is not None else result
    result["id"] = "site_"+kind+"_"+hashlib.sha256(dump(signature).encode()).hexdigest()[:32]
    return result


def ordered_events(db, rows, metadata, timestamp, amount, number):
    db.execute("CREATE TEMP TABLE site_event_batch(seq INTEGER PRIMARY KEY,ts REAL,priority INTEGER,id TEXT UNIQUE,body TEXT)")
    accepted, errors = Counter(), Counter()
    columns, ignored = {}, set()
    metadata.update(counts=accepted,errors=errors,columns=columns,ignored=ignored,valid=0,inserted=Counter())
    def stage():
        for seq,raw in enumerate(rows):
            if not isinstance(raw,dict):
                errors["Запись не является объектом"] += 1
                continue
            columns.update((k,ALIASES[k]) for k in raw if k in ALIASES)
            ignored.update(raw.keys()-ALIASES.keys())
            try:
                r = normalize_row(raw,timestamp,amount,number)
            except (TypeError,ValueError,OverflowError) as exc:
                errors[str(exc) if isinstance(exc,ValueError) else "Неверное поле события"] += 1
                continue
            metadata["valid"] += 1
            yield seq,r["ts"],int(r["kind"]!="search"),r["id"],dump(r)
    db.executemany("INSERT OR IGNORE INTO site_event_batch VALUES (?,?,?,?,?)",stage())
    metadata["repeated"] = metadata["valid"] - db.execute("SELECT count(*) FROM site_event_batch").fetchone()[0]
    for row in db.execute("SELECT body FROM site_event_batch ORDER BY ts,priority,seq"):
        yield json.loads(row[0])
    db.execute("DROP TABLE site_event_batch")


def record_impression(db, search, size, card_ids):
    ident = search["search_id"]
    if size is not None:
        db.execute("INSERT OR IGNORE INTO site_result_sizes VALUES (?,?,0)",(ident,size))
    measured = db.execute("SELECT size FROM site_result_sizes WHERE search_id=?",(ident,)).fetchone()
    total = measured[0] if measured else max(search["n_cards"],len(card_ids))
    if card_ids:
        cards = dump(card_ids[:total])
    else:
        cards = search["top_cards_json"] if total else "[]"
    if total != search["n_cards"] or cards != search["top_cards_json"]:
        db.execute("""UPDATE searches SET n_cards=?,zero=?,top_cards_json=?,blocks_json=?,
                   fail_reason=CASE WHEN ?>0 THEN NULL ELSE fail_reason END WHERE search_id=?""",
                   (total,not total,cards,dump(["products"] if total else []),total,ident))
