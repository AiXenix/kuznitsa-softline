import re
from statistics import median

TIERS=("Точное соответствие","Подходит по условиям","Близкий вариант","Расширенный поиск")


def edition_rank(card):
    edition=card.offers[0].edition
    return next((i for i,e in enumerate(card.kb.get("editions",[])) if e["id"]==edition),0)


def is_module(card):
    edition=next((e for e in card.kb.get("editions",[]) if e["id"]==card.offers[0].edition),{})
    return bool(re.search(r"\b(?:модуль|плагин|надстройка|дополнение)\b", " ".join([card.title,edition.get("name","")]),re.I))


def analog_scope(engine,rel,f,exc,cheaper):
    families=engine.kb.rows["families"]
    anchors=[families[fid] for fid in f.get("family",[]) if fid in families]
    vendors=set(f.get("vendor",[]))|{r.get("vendor") for r in anchors}
    if not anchors:
        for vendor in vendors:
            rows=[families[k] for k in engine.vendor_families.get(vendor,[]) if families[k].get("catalog",True)]
            if rows:
                anchors.append(max(rows,key=lambda r:(r.get("popularity",0),len(r.get("replaces",[])))))
    if vendors:
        exc["vendor"]=sorted(v for v in vendors if v)
    cats={r.get("category") for r in anchors}
    targets={v for r in anchors for v in r.get("analogs",[])}
    for r in anchors:
        targets.update(a["family"] for a in engine.kb.rows["analogs"].get(r["id"],{}).get("russian_analogs",[]))
    if cheaper:
        prices=[r.get("price_rub",{}).get("typical") for r in anchors]
        if any(prices):
            f["price_max"]=median(v for v in prices if v)-.01
    return {cid:(.97 if card.family in targets and card.category in cats else .84 if card.family in targets else .54)
            for cid in rel if (card:=engine.catalog.cards[cid]).vendor not in vendors and not is_module(card)
            and (not cats or card.family in targets or card.category in cats)}


def preference(card,query,filters,rel):
    text=card.title.casefold()
    seats=filters.get("metric") in ("user","device") or filters.get("audience")=="edu"
    if not filters.get("edition"):
        rel-=min(.10,edition_rank(card)*.035)
        if not re.search("сервер|шлюз|server|gateway",query) and re.search("сервер|шлюз|server|gateway",text):
            rel-=.28 if seats else .19
        if is_module(card) and not re.search("модул|плагин",query):
            rel-=.28
    return max(.05,min(1.,rel))
