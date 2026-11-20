from collections import Counter, defaultdict
import json
import re
from .kpi import facts,loss_by_search

GAPS={"not_in_catalog_known","not_in_catalog_unknown"}


def demand(engine,rows,loss):
    end=max((r["ts"] for r in rows),default=0)
    groups=defaultdict(list)
    impressions=Counter()
    for r in rows:
        if r["ts"]>end-30*86400:
            impressions.update(set(json.loads(r["top_cards_json"] or "[]")))
        if r["reason"] not in GAPS|{"vendor_left"}:
            continue
        f=json.loads(r["filters_json"] or "{}")
        family=next(iter(f.get("family",[])),None)
        vendor=engine.kb.rows["families"].get(family,{}).get("vendor") or next(iter(f.get("vendor",[])),None)
        if r["reason"]=="vendor_left":
            key=vendor or family or r["q"]
        else:
            brand=re.findall(r"\b[a-z][a-z0-9+-]{2,}\b",r["q"].lower())
            key=family or next((x for x in brand if x not in {"enterprise","windows","linux","astra","commercial","server","pro"}),r["q"].lower())
        groups[(r["reason"]=="vendor_left",key)].append((r,vendor,family))
    gaps=[]
    departed=[]
    for (left,key),entries in groups.items():
        recent=[r for r,_,_ in entries if r["ts"]>end-30*86400]
        if not recent:
            continue
        prev=sum(end-60*86400<r["ts"]<=end-30*86400 for r,_,_ in entries)
        vendor,family=entries[0][1:]
        item=dict(key=key,title=engine.names["vendor" if left else "family"].get(key,key),vendor=vendor,family=family,
                  category=Counter(r["category"] for r in recent).most_common(1)[0][0],searches=len(recent),
                  sessions=len({r["session_id"] for r in recent}),previous=prev,change=len(recent)-prev,
                  segments=dict(Counter(r["segment"] for r in recent)),queries=[q for q,_ in Counter(r["q"] for r in recent).most_common(5)],
                  expected_rub=round(sum(loss.get(r["search_id"],(0,0))[0] for r in recent)))
        (departed if left else gaps).append(item)
    defects=[]
    for c in engine.catalog.cards.values():
        if not impressions[c.id]:
            continue
        fields=[key for key,attr in (("description","description"),("price","price"),("platforms","platforms"),("attributes","attrs"),
                                      ("registry","registry"),("qty_range","lic")) if all(
            (o.lic.qty_min is None and o.lic.qty_max is None) if attr=="lic" else getattr(o,attr) in (None,"",[],{}) for o in c.offers)]
        if fields:
            defects.append(dict(card_id=c.id,title=c.title,category=c.category,fields=fields,impressions=impressions[c.id]))
    sort=lambda items:sorted(items,key=lambda x:-x["searches"])
    breakdown={}
    for dimension in ("family","vendor","category"):
        grouped=defaultdict(list)
        for item in gaps:
            grouped[item[dimension] or "unknown"].append(item)
        breakdown[dimension]=sort([dict(key=key,searches=sum(i["searches"] for i in items),
            previous=sum(i["previous"] for i in items),expected_rub=sum(i["expected_rub"] for i in items),
            clusters=[i["key"] for i in items]) for key,items in grouped.items()])
    return dict(items=sort(gaps),breakdown=breakdown,departed=sort(departed),card_defects=sorted(defects,key=lambda x:-x["impressions"]),
                period_days=30,through=end)


def report(engine):
    rows=[r for r in facts(engine.journal) if r["source"]!="replay"]
    result=demand(engine,rows,loss_by_search(rows)[0])
    result["bridge"]=engine.journal.rows("""SELECT count(distinct s.search_id) impressions,
        count(distinct case when e.type='click' and json_extract(e.payload_json,'$.block')='analogs' then s.search_id end) clicks,
        count(distinct case when e.type='cart' and json_extract(e.payload_json,'$.block')='analogs' then s.search_id end) carts
        FROM searches s LEFT JOIN events e USING(search_id) WHERE s.fail_reason='vendor_left' AND s.blocks_json LIKE '%analogs%'
        AND s.source IN ('ui','history')""")[0]
    return result
