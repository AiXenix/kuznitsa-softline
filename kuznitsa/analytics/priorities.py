"""Правила приоритета направлений, история редакций и парный предпросмотр."""
import json
from collections import Counter
from datetime import date, datetime, timezone
from time import time
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kuznitsa.plans.base import descendants
from kuznitsa.schema import Request
from kuznitsa.text import normalize
from kuznitsa.understand.intent import TITLES
from .store import dump, result_cards

TAGS = "domestic fstec fsb in_stock promo new subscription perpetual cloud electronic box edu gov".split()
CRITERIA = "popularity margin personal stock novelty price_low domestic promo conversion".split()


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, str_strip_whitespace=True)


class Price(Fields):
    min: float | None = Field(None, ge=0)
    max: float | None = Field(None, ge=0)


class Target(Fields):
    categories: list[str] = []
    vendors: list[str] = []
    families: list[str] = []
    cards: list[str] = []
    tags: list[str] = []
    price_rub: Price | None = None


class Scope(Fields):
    segments: list[str] = []
    profiles: list[str] = []
    regions: list[str] = []
    intents: list[str] = []
    queries: list[str] = []
    channels: list[str] = []
    start: str | None = Field(None, alias="from")
    end: str | None = Field(None, alias="to")


class Top(Fields):
    k: int = Field(ge=0)
    n: int = Field(ge=1)


class Pin(Fields):
    card_id: str = Field(min_length=1)
    position: int = Field(ge=1)


class Action(Fields):
    boost: int = Field(0, ge=-100, le=100)
    criteria: dict[str, float] = {}
    max_in_top: Top | None = None
    pin: Pin | None = None
    public_label: str | None = None


class Rule(Fields):
    id: str | None = Field(None, pattern=r"^[\w.-]{1,100}$")
    title: str = Field(min_length=1, max_length=250)
    enabled: bool = True
    order: int = 10
    target: Target
    scope: Scope = Scope()
    action: Action
    cross_tier: bool = False
    note: str = ""
    author: str = Field("admin", min_length=1)
    created_at: int | None = None
    updated_at: int | None = None


def validate(body):
    try:
        rule = Rule.model_validate(body)
    except ValidationError as exc:
        error = exc.errors()[0]
        field = ".".join(map(str, error["loc"]))
        raise ValueError(f"Проверьте значение поля «{field}» ({error['type']})") from exc
    scope, target, action = rule.scope, rule.target, rule.action
    for values, allowed, label in [(target.tags, TAGS, "признаки"), (scope.channels, ["ui","widget","api"], "каналы"),
                                   (scope.intents, TITLES, "виды запросов"), (action.criteria, CRITERIA, "критерии")]:
        unknown = set(values) - set(allowed)
        if unknown:
            raise ValueError(f"Неизвестные {label} · {', '.join(sorted(unknown))}")
    for value in [*target.model_dump().values(), *scope.model_dump().values()]:
        if isinstance(value, list) and "" in value:
            raise ValueError("Пустое значение внутри списка")
    if any(v < 0 for v in action.criteria.values()):
        raise ValueError("Вес критерия должен быть неотрицательным")
    if action.max_in_top and action.max_in_top.k > action.max_in_top.n:
        raise ValueError("Ограничение k должно быть не больше n")
    if target.price_rub and None not in (target.price_rub.min, target.price_rub.max) and target.price_rub.min > target.price_rub.max:
        raise ValueError("Нижняя граница цены больше верхней")
    try:
        dates = [date.fromisoformat(x).isoformat() if x else None for x in (scope.start, scope.end)]
    except ValueError as exc:
        raise ValueError("Дата должна иметь вид ГГГГ-ММ-ДД") from exc
    scope.start, scope.end = dates
    if all(dates) and dates[0] > dates[1]:
        raise ValueError("Конец периода раньше начала")
    return rule.model_dump(by_alias=True)


def all_rules(journal):
    return [json.loads(r["body"]) for r in journal.rows(
        "SELECT body FROM priorities ORDER BY json_extract(body,'$.order'),rowid")]


def active_rules(journal):
    if not hasattr(journal,"transaction"):
        return 0, []
    with journal.lock:
        version = journal.db.execute("SELECT coalesce(max(version),0) FROM priorities_audit").fetchone()[0]
        cached = getattr(journal, "_priority_rules", None)
        if cached is None or cached[0] != version:
            # Обе части ответа относятся к одному снимку, даже при внешней записи.
            snapshot = journal.rows("""SELECT rev.v, p.body FROM
                (SELECT coalesce(max(version),0) v FROM priorities_audit) rev
                LEFT JOIN priorities p ON json_extract(p.body,'$.enabled')=1
                ORDER BY json_extract(p.body,'$.order'), p.rowid""")
            journal._priority_rules = snapshot[0]["v"], [json.loads(r["body"]) for r in snapshot if r["body"]]
        return journal._priority_rules


def change(journal, operation, body=None, ident=None, author=None):
    with journal.transaction() as db:
        before = db.execute("SELECT body FROM priorities WHERE id=?", (ident,)).fetchone()
        previous = json.loads(before[0]) if before else None
        if operation in {"update","delete","toggle"} and previous is None:
            raise KeyError(ident)
        if operation == "create" and previous:
            raise ValueError("Идентификатор правила уже занят")
        now = int(time())
        if operation == "delete":
            db.execute("DELETE FROM priorities WHERE id=?", (ident,))
            rule = None
        else:
            if operation == "toggle":
                body = previous | {"enabled": not previous["enabled"]}
            rule = validate(body)
            if ident and rule["id"] and ident != rule["id"]:
                raise ValueError("Идентификатор в теле отличается от адреса правила")
            ident = ident or rule["id"] or "p_" + uuid4().hex[:16]
            if operation == "create" and db.execute("SELECT 1 FROM priorities WHERE id=?", (ident,)).fetchone():
                raise ValueError("Идентификатор правила уже занят")
            created_at=previous["created_at"] if previous else now
            updated_at=now
            if operation=="import":
                created_at=rule["created_at"] if rule["created_at"] is not None else created_at
                updated_at=rule["updated_at"] if rule["updated_at"] is not None else now
            rule.update(id=ident, author=author or rule["author"], updated_at=updated_at, created_at=created_at)
            db.execute("INSERT INTO priorities VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", (ident, dump(rule)))
        version = db.execute("INSERT INTO priorities_audit(rule_id,operation,ts,author,before_json,after_json) VALUES (?,?,?,?,?,?)",
                             (ident, operation, now, author or (rule or {}).get("author","admin"),
                              before[0] if before else None, dump(rule) if rule else None)).lastrowid
    return dict(id=ident, version=version, item=rule)


def audit(journal):
    rows = journal.rows("SELECT * FROM priorities_audit ORDER BY version DESC")
    for row in rows:
        for side in ("before","after"):
            row[side] = json.loads(row.pop(side + "_json") or "null")
    return dict(items=rows)


def export_rules(journal):
    return dict(format="priorities.v1", items=all_rules(journal))


def import_rules(journal, payload):
    if not isinstance(payload, dict) or payload.get("format") != "priorities.v1" or not isinstance(payload.get("items"), list):
        raise ValueError("Требуется снимок priorities.v1 с массивом items")
    rules = [validate(r) for r in payload["items"]]
    ids = {r["id"] for r in rules}
    if None in ids or len(ids) != len(rules):
        raise ValueError("Каждому правилу снимка нужен уникальный id")
    mode = payload.get("mode","merge")
    if mode not in ("merge","replace"):
        raise ValueError("Режим импорта — merge или replace")
    with journal.transaction():
        if mode=="replace":
            # Порядок строк снимка разрешает ничьи при одинаковом order.
            for old in all_rules(journal):
                change(journal,"delete",ident=old["id"])
        for rule in rules:
            change(journal, "import", rule, rule["id"])
    return dict(imported=len(rules), version=active_rules(journal)[0])


def direction_test(engine, target):
    categories = descendants(engine.kb, target["categories"])

    def includes(card_id, offer_id, day):
        card = engine.catalog.cards.get(card_id)
        if not card or any(values and value not in values for values,value in (
                (categories,card.category),(target["families"],card.family),
                (target["vendors"],card.vendor),(target["cards"],card_id))):
            return False
        price, tags = target["price_rub"], target["tags"]
        if not price and not tags:
            return True
        offer = engine.catalog.offers_by_id.get(offer_id)
        if not offer:
            return None
        if price and (offer.price is None or price["min"] is not None and offer.price < price["min"]
                      or price["max"] is not None and offer.price > price["max"]):
            return False
        if not tags:
            return True
        flags = set(offer.certs) | {offer.lic.model,offer.lic.audience,
                                   "electronic" if offer.delivery=="esd" else offer.delivery}
        if offer.registry:
            flags.add("domestic")
        if "cloud" in card.kb.get("deployment",[]) or offer.attrs.get("deployment")=="cloud":
            flags.add("cloud")
        for tag in ("domestic","in_stock","promo"):
            value = getattr(offer,tag,None)
            if str(offer.attrs.get(tag) if value is None else value).lower() in ("true","1","да"):
                flags.add(tag)
        added = getattr(offer,"added_at",None) or offer.attrs.get("added_at")
        try:
            age = (day-date.fromisoformat(str(added)[:10])).days
        except ValueError:
            age = None
        if age is not None and 0 <= age <= 30:
            flags.add("new")
        return bool(flags.intersection(tags))
    return includes


def in_scope(engine, scope, row):
    profile = engine.clients.get(row["client_id"])
    for key, value in [("profiles",row["client_id"]), ("segments",row["segment"]), ("regions",getattr(profile,"region",None)),
                       ("intents",row["intent"]), ("channels",row["source"])]:
        if scope[key] and value not in scope[key]:
            return False
    if scope["queries"] and not any(normalize(q) in row["q_norm"] for q in scope["queries"]):
        return False
    day = datetime.fromtimestamp(row["ts"], timezone.utc).date().isoformat()
    return (not scope["from"] or day >= scope["from"]) and (not scope["to"] or day <= scope["to"])


def listing(engine):
    j = engine.journal
    version, _ = active_rules(j)
    rules = all_rules(j)
    live = j.rows("""SELECT search_id,q_norm,ts,client_id,source,segment,intent,top_cards_json,trace_json FROM searches
                     WHERE ts BETWEEN ? AND ? AND source IN ('ui','api','widget')""",
                  (engine.clock()-86400,engine.clock())) if rules else []
    for rule in rules:
        scope = [r for r in live if in_scope(engine,rule["scope"],r)]
        direction = direction_test(engine, rule["target"])
        places = Counter()
        fired = 0
        for row in scope:
            saved = json.loads(row["trace_json"] or "{}")
            metadata = saved if isinstance(saved,dict) else {}
            fired += rule["id"] in metadata.get("priority_ids",[])
            ids = json.loads(row["top_cards_json"] or "[]")[:5]
            offers = metadata.get("top_offers",[])
            day = datetime.fromtimestamp(row["ts"],timezone.utc).date()
            for index,card_id in enumerate(ids):
                places[direction(card_id,offers[index] if index<len(offers) else None,day)] += 1
        available = places[True]+places[False]
        rule["stats"] = dict(fired_24h=fired, searches_in_scope_24h=len(scope),
                             share_top5=places[True]/available if available else None,
                             measured_positions=available,unknown_positions=places[None])
    return dict(version=version, items=rules, criteria=CRITERIA, tags=TAGS)


def preview(engine, payload):
    if not isinstance(payload, dict) or "rule" not in payload:
        raise ValueError("Укажите проект правила")
    rule = validate(payload["rule"])
    limit = payload.get("limit",30)
    queries = payload.get("queries")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Размер выборки должен быть от 1 до 100")
    if queries is not None and (not isinstance(queries,list) or not all(
        isinstance(q,str) and q.strip() and len(q)<=1500 for q in queries)):
        raise ValueError("Нужен список непустых поисковых фраз")
    if not callable(getattr(engine,"preview",None)):
        raise NotImplementedError("Установите версию движка с Engine.preview")
    j = engine.journal
    stored = all_rules(j)
    active = [r for r in stored if r["enabled"]]
    rule["id"] = rule["id"] or "draft_" + uuid4().hex
    edited = [rule if r["id"]==rule["id"] else r for r in stored]
    if not any(r["id"]==rule["id"] for r in stored):
        edited.append(rule)
    trial = sorted((r for r in edited if r["enabled"]), key=lambda r:r["order"])
    scope = rule["scope"]
    direction = direction_test(engine,rule["target"])
    profiles = [p for p in engine.clients.values() if
                (not scope["profiles"] or p.client_id in scope["profiles"]) and
                (not scope["regions"] or p.region in scope["regions"]) and
                (not scope["segments"] or p.segment in scope["segments"])]
    default_profile = next((p.client_id for p in profiles if p.client_id=="guest"),
                           profiles[0].client_id if profiles else None)
    if not default_profile:
        raise ValueError("Для предпросмотра нужен профиль в выбранном сегменте и регионе")
    requested = list(dict.fromkeys(queries or []))[:limit]
    params = requested
    where = " WHERE q_raw IN (" + ",".join("?" for _ in params) + ")" if params else ""
    rows = j.rows("""SELECT q_raw,q_norm,ts,client_id,segment,source,intent,
        coalesce(o.orders,s.search_id GLOB 's_mock_*') order_observed,
        EXISTS(SELECT 1 FROM events e WHERE e.search_id=s.search_id AND type='order') ordered
        FROM active_history s LEFT JOIN analytics_observation o ON o.id=s.search_id""" + where, params)
    counts, contexts, orders, observed = Counter(), Counter(), Counter(), Counter()
    channel = next(iter(scope["channels"]),"ui")
    profile_by_segment = {}
    for p in profiles:
        profile_by_segment.setdefault(p.segment,p.client_id)
    for r in rows:
        # У истории нет метки канала витрины. Канал задаёт сценарий предпросмотра.
        r["source"] = channel
        if in_scope(engine, scope, r):
            q = r["q_raw"]
            profile = r["client_id"] if r["client_id"] in engine.clients else profile_by_segment.get(r["segment"],default_profile)
            counts[q] += 1
            contexts[q,profile] += 1
            orders[q,profile] += r["ordered"]
            observed[q,profile] += bool(r["order_observed"] or r["ordered"])
    selected = requested if queries is not None else sorted(counts,key=lambda q:(-counts[q],q))[:limit]
    hits, slots, margins, priced = [0,0], [0,0], [0.,0.], [0,0]
    affected = 0
    order_potential = 0.
    order_denominator = 0
    examples = []
    for q in selected:
        samples = [(pid,n) for (phrase,pid),n in contexts.items() if phrase==q] or [(default_profile,0)]
        for profile, frequency in sorted(samples,key=lambda s:(-s[1],s[0])):
            req = Request(q=q,profile_id=profile,mode="fast",page_size=5).model_copy(update={"source":channel})
            pair = []
            shares = []
            for side,rules in enumerate((active,trial)):
                cards = result_cards(engine.preview(req, priorities=rules))[:5]
                top = [dict(card_id=c["card_id"],title=c["title"],tier=c["score"]["tier"]) for c in cards]
                pair.append(top)
                today = datetime.fromtimestamp(engine.clock(),timezone.utc).date()
                included = sum(bool(direction(c["card_id"],(c.get("offer") or {}).get("offer_id"),today)) for c in cards)
                shares.append(included/len(cards) if cards else 0.)
                weight = frequency or 1
                hits[side] += weight * included
                slots[side] += weight * len(cards)
                for c in cards:
                    o = engine.catalog.offers_by_id.get((c.get("offer") or {}).get("offer_id"))
                    if o and o.price is not None and o.margin is not None:
                        margins[side] += weight * o.price * o.margin
                        priced[side] += weight
            before, after = pair
            old = [c["card_id"] for c in before]
            new = [c["card_id"] for c in after]
            moved = sum(a!=b for a,b in zip(old,new)) + abs(len(old)-len(new))
            affected += frequency if moved else 0
            order_denominator += observed[q,profile]
            order_potential += orders[q,profile]*max(0,shares[1]-shares[0])
            examples.append(dict(q=q,profile_id=profile,frequency=frequency,before=before,after=after,moved=moved))
    def mean(total,n):
        return round(total/n,4) if n else None
    order_text=(f"Осторожный ориентир для направления — {int(order_potential)} заказов на {order_denominator} поисках с данными о покупке."
                if order_denominator else "Данных о покупках для оценки заказов в этой выборке нет.")
    summary = dict(share_top5_before=mean(hits[0],slots[0]),share_top5_after=mean(hits[1],slots[1]),
                   avg_margin_before=mean(margins[0],priced[0]),avg_margin_after=mean(margins[1],priced[1]),
                   margin_unit="₽ за единицу",searches_affected=affected,orders_estimate=int(order_potential) if order_denominator else None,order_denominator=order_denominator,
                   effect_text=f"Изменится порядок в {affected} поисках выборки. "+order_text,
                   note="Вес пары — число таких поисков в истории. Канал для моделирования — "+channel+
                   ". Для фразы без истории вес показа равен 1, исторический спрос равен 0. Маржа — цена × доля маржи SKU с известной ценой. "+
                   "Ориентир — сумма заказавших поисков × положительное изменение доли направления в топ-5, с округлением вниз. Это модель перераспределения.")
    return dict(queries=examples,summary=summary)
