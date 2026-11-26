"""Two streaming passes over the grouped YML export from store.softline.ru."""
import csv
import json
import re
from collections import Counter, defaultdict
from contextlib import closing
import sqlite3
from html import unescape
from itertools import islice
from pathlib import Path

import yaml

from lxml import etree

from .enrich import number
from .mapping import field_for
from .nameparse import normalize

PLACEHOLDERS={"другое или отсутствует","не указано","не определено"}
SUFFIX=re.compile(r"(?:\s*[,;(]\s*(?:лицензи|подписк|продлен|для (?:коммерческ|образоват|государств)|электронн|\d+\s*(?:мес|год|польз))|(?:\s+[-–]\s+)?\b(?:renewal license|subscription license)\b)",re.I)


def matches(path):
    if path.suffix.lower() not in (".xml",".yml"):
        return False
    with path.open("rb") as stream:
        for _,node in islice(etree.iterparse(stream,events=("end",),resolve_entities=False,no_network=True),12):
            if node.tag=="name" and node.getparent() is not None and node.getparent().tag=="shop":
                return node.text=="store.softline.ru"
    return False


def copy_decisions(source, destination):
    """SQLite backup also includes committed writes still in the WAL."""
    if source.is_file():
        with closing(sqlite3.connect(source.resolve().as_uri()+"?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dest:
                src.backup(dest)


def elements(path):
    for _,node in etree.iterparse(str(path),events=("end",),tag=("category","offer"),resolve_entities=False,no_network=True):
        yield node
        node.clear()
        while node.getprevious() is not None:
            del node.getparent()[0]


def tree(cats,key):
    chain=[]
    while key in cats and key not in chain:
        chain.append(key)
        key=cats[key][1]
    return chain[::-1]


def group(node):
    return node.get("group_id") or node.findtext("group_id") or "sku_"+node.get("id")


ACTIONS=(("продлен","renewal"),("техподдерж","support"),("миграц","crossgrade"),
         ("перекрест","crossgrade"),("обновлен","upgrade"),("модуль","addon"),
         ("полная","new"),("базовая","new"),("full","new"))
AUDIENCES={"некоммерческая":"nonprofit","коммерческая":"business","государственная":"gov",
           "академическая":"edu","для дома":"home","образовательная":"edu"}


def license_fields(parameters,attrs):
    lic={}
    for key,metric in (("qty_max","user"),("qty_min","device")):
        values=[int(v) for v in parameters.get(key,()) if v.isdecimal() and int(v)>0]
        if values:
            lic["metric"]=metric
            lic[key]=min(values) if key=="qty_min" else max(values)
            if key=="qty_min" and len(values)>1:
                lic["qty_max"]=max(values)
    if "qty_min" in lic and "qty_max" in lic and lic["qty_max"]<lic["qty_min"]:
        lic.pop("qty_max")
    for key,value in lic.items():
        if key in ("qty_min","qty_max"):
            # Keep the original set of thresholds alongside its numeric bounds.
            if key in attrs and attrs[key]!=str(value):
                attrs["source_"+key]=attrs[key]
            attrs[key]=str(value)
    term=attrs.get("term_months","").casefold()
    months=re.fullmatch(r"(\d+)\s*мес\.?",term)
    if months:
        lic.update(term_months=int(months[1]),model="subscription")
        attrs["term_months"]=months[1]
    if "бессроч" in term:
        lic["model"]="perpetual"
    operation=attrs.get("operation","").casefold()
    for fragment,value in ACTIONS:
        if fragment in operation:
            lic["action"]=value
            break
    if "audience" in attrs:
        attrs.setdefault("edition",attrs["audience"])
        attrs["organization_type"]=attrs["audience"]
        audiences=[AUDIENCES.get(v.casefold(),v) for v in parameters["audience"]]
        attrs["audience"]="; ".join(audiences)
        if len(audiences)==1 and audiences[0] in AUDIENCES.values():
            lic["audience"]=audiences[0]
    return lic


# Punctuation before licensing terms distinguishes the product from its offer variant.
VARIANT=re.compile(r"\s*[,;:(]\s*(?:подписк|продлен|обновлен|конфигураци|"
                   r"(?:основная|новая|базовая|академическая) лицензия|"
                   r"лицензи|электронная поставка|на \d+ (?:год|мес|узл|польз))",re.I)


def card_title(prefix,line,vendor,sku,domain):
    title=prefix.strip(" ,;:-")
    if domain in {"software","cloud","service"}:
        title=VARIANT.split(title,1)[0].rstrip(" ,;:-")
        if sku and title.casefold().endswith(" "+sku.casefold()):
            title=title[:-len(sku)].rstrip(" ,;:-")
    if not title or normalize(title)==normalize(vendor):
        return line or title or vendor
    return title


def build(path,out,kb):
    with Path(__file__).with_name("softline_roots.tsv").open() as table:
        domains={r["id"]:r["domain"] for r in csv.DictReader(table,delimiter="\t")}
    cats,titles={},{}
    for node in elements(path):
        if node.tag=="category":
            cats[node.get("id")]=(unescape(node.text or ""),node.get("parentId"))
            continue
        key=group(node)
        words=SUFFIX.split(unescape(node.findtext("name") or ""),1)[0].strip(" ,(-").split()
        if key in titles:
            old=titles[key]
            length=next((i for i,(a,b) in enumerate(zip(old,words)) if a.casefold()!=b.casefold()),min(len(words),len(old)))
            words=old[:length]
        titles[key]=words
    paths={k:tree(cats,k) for k in cats}
    classes={k:dict(path=[cats[i][0] for i in p],examples=[],offers=0,domain=domains.get(p[0],"software")) for k,p in paths.items() if len(p)==2}
    vendors={normalize(v):k for k,r in kb["vendors"].items() for v in [r.get("name",k),*r.get("aliases",[])]}
    display_titles={}
    counts=Counter()
    mapped, unmatched, levels = Counter(), Counter(), Counter()
    with (out/"catalog.jsonl").open("w") as stream:
        for node in elements(path):
            if node.tag!="offer":
                continue
            p=paths.get(node.findtext("categoryId"),[])
            group_path=paths.get(group(node))
            if len(p)==2 and group_path and group_path[:-1]==p:
                p=group_path
            names=[cats[k][0] for k in p]
            levels[len(p)]+=1
            raw={x.tag:x.text or "" for x in node if x.tag!="param"}
            for key in ("name","vendor","description"):
                raw[key]=unescape(raw.get(key,""))
            ident=node.get("id")
            g=group(node)
            domain=domains.get(p[0] if p else "", "software")
            if g not in display_titles:
                line=names[-1] if len(p)==3 else raw["name"]
                display_titles[g]=card_title(" ".join(titles[g]),line,raw["vendor"],raw.get("vendorCode"),domain)
            title=display_titles[g]
            attrs=dict(domain=domain,group_id=node.get("group_id") or raw.get("group_id",""),
                       feed_offer_id=ident,feed_category_id=raw.get("categoryId",""),feed_category_path_ids=p)
            if len(p)==3:
                attrs["series"]=names[-1]
            for k,v in zip(("root_id","class_id","line_id"),p):
                attrs[k]=v
            parameters=defaultdict(dict)
            for param in node.iterfind("param"):
                label=param.get("name","")
                val=unescape(param.text or "").strip()
                if not val or val.casefold() in PLACEHOLDERS:
                    continue
                key=field_for(label)
                (mapped if key else unmatched)[key or label]+=1
                parameters[key or label][val]=None
            attrs.update({key:"; ".join(values) for key,values in parameters.items()})
            for key in ("vendorUrl","sales_notes","oldprice"):
                if raw.get(key):
                    attrs[key]=raw[key]
            price=number(raw.get("price"))
            oldprice=number(raw.get("oldprice"))
            promo=0<(price or 0)<(oldprice or 0)
            avail=node.get("available","true").casefold()=="true"
            sku=raw.get("vendorCode") or ident
            lic=license_fields(parameters,attrs)
            if len(p)==3:
                aliases=attrs.get("aliases","").split("; ") if attrs.get("aliases") else []
                attrs["aliases"]=list(dict.fromkeys([*aliases,names[-1]]))
            vendor=raw.get("vendor","")
            row=dict(offer_id="sl_"+ident,source_id=ident,source_ids=list(dict.fromkeys([ident,sku])),sku=sku,name=raw["name"],
                     vendor=vendor,vendor_id=vendors.get(normalize(vendor),"sl_v_"+normalize(vendor)),family_id=g,family_name=title,
                     category_path=names,category_id=None,domain=domain,kind={"hardware":"hardware","service":"service"}.get(domain,"license"),
                     lic=lic,attrs=attrs,price=price,oldprice=oldprice,price_on_request=not price,
                     available=avail,in_stock=avail,promo=promo,image=raw.get("picture"),picture=raw.get("picture"),
                     vendorUrl=raw.get("vendorUrl"),sales_notes=raw.get("sales_notes"),url=raw.get("url"),description=raw.get("description",""),
                     platforms=attrs.get("platform","").split("; ") if attrs.get("platform") else [],margin=.5,popularity=.5)
            if "электрон" in attrs.get("delivery","").lower():
                row["delivery"]="esd"
            for key in ("language","version"):
                if key in attrs:
                    row[key]=attrs[key]
            if attrs.get("registry_no") and attrs["registry_no"].casefold() not in ("нет","0","false"):
                row["registry"]=True
            stream.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
            counts[domain]+=1
            if len(p)>1:
                c=classes[p[1]]
                c["offers"]+=1
                example=" ".join(titles[g]) or c["path"][-1]
                if len(c["examples"])<5 and example not in c["examples"]:
                    c["examples"].append(example)
    (out/"feed_classes.json").write_text(json.dumps(classes,ensure_ascii=False))
    (out/"feed_categories.json").write_text(json.dumps(cats,ensure_ascii=False))
    return dict(offers=sum(counts.values()),cards=len(titles),categories=len(cats),classes=len(classes),domains=dict(counts),path_depths=dict(levels),
                attributes=dict(by_key=dict(mapped),unmatched=dict(unmatched)))


def map_classes(out,kb,cfg,mode,budget,transport=None,dry=False):
    """Classify each source class once. Keep the source tree as the primary navigation."""
    from concurrent.futures import ThreadPoolExecutor
    from .classify import describe,words
    from .ai_backend import Gateway,Vectors,cached_keys,forecast
    classes=json.loads((out/"feed_classes.json").read_text())
    parents={r.get("parent") for r in kb["categories"].values()}
    candidates={k:r for k,r in kb["categories"].items() if k not in parents}
    ids=list(candidates)
    docs=[describe(candidates[k]) for k in ids]
    indices=list(range(len(ids)))
    exact_names=[{normalize(x) for x in (row["title"],*row.get("synonyms",[]))} for row in candidates.values()]
    descriptions={k:doc[:220] for k,doc in zip(ids,docs)}
    terms=[words(doc) for doc in docs]
    queries={k:" / ".join(r["path"]) for k,r in classes.items()}
    vectors=Vectors(cfg,docs,list(queries.values()),set()) if mode!="off" else None
    db=out/"import_ai.sqlite"
    keys=cached_keys(db) if mode=="jev" else set()
    gateway=Gateway(db,min(.30,budget),transport) if mode=="jev" and not dry else None
    def decide(item):
        k,r=item
        label=r["path"][-1]
        bag=words(label)
        ranked=[]
        normalized=normalize(label)
        for j,similarity in enumerate(vectors.scores(queries[k],indices) if vectors else []):
            exact=normalized in exact_names[j]
            overlap=len(bag & terms[j])/max(1,len(bag))
            score=1. if exact else .72*float(similarity)+.28*overlap
            ranked.append((score,ids[j]))
        ranked.sort(reverse=True)
        p,local=ranked[0] if ranked else (0.,None)
        local=local if p>=.55 else None
        options={i:descriptions[i] for _,i in ranked[:8]}
        options["none"]="Подходящего класса в базе нет"
        result=dict(object=k,question="category",state=r["path"],options=options,local=local,local_score=p,
                    choice=local,probability=p,source=mode if mode=="off" else "embed",usd=0)
        state={"класс":queries[k],"направление":r["domain"],"линейки":r["examples"]}
        if mode=="jev":
            estimated,hit=forecast(state,"category",options,keys)
            result.update(forecast_usd=estimated,forecast_sent=int(not hit))
        if gateway:
            ans,meta,reason=gateway.request(k,state,"category",options)
            result.update(usd=meta["usd"],sent=meta.get("sent",False),cached=meta.get("cached",False),fallback=reason)
            if ans:
                pick=ans["choice"]
                prob=ans["probabilities"][pick]
                result.update(choice=pick if prob>=.55 and pick!="none" else None,probability=prob,source="jev")
        result["confidence"]="model" if result["source"]=="jev" else "low"
        result["accepted"]=bool(result["choice"])
        return result
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            decisions=list(pool.map(decide,classes.items())) if mode!="off" else []
    finally:
        if gateway:
            gateway.close()
    for item in classes.values():
        item.update(kb_category=None,local_category=None)
    with (out/"import_ai.jsonl").open("w") as f:
        for row in decisions:
            f.write(json.dumps(row,ensure_ascii=False)+"\n")
            classes[row["object"]].update(kb_category=row["choice"],local_category=row["local"])
    (out/"feed_classes.json").write_text(json.dumps(classes,ensure_ascii=False))
    def coverage(key):
        covered=[r for r in classes.values() if r[key]]
        return dict(classes=len(covered),offers=sum(r["offers"] for r in covered))
    examples=[r for accepted in (True,False) for r in [d for d in decisions if d["accepted"]==accepted][:5]]
    accepted=sum(d["accepted"] for d in decisions)
    return dict(mode=mode,examples=examples,forecast_usd=sum(r.get("forecast_usd",0) for r in decisions),
                forecast_sent=sum(r.get("forecast_sent",0) for r in decisions),accepted=accepted,rejected=len(decisions)-accepted,by_kind={"category":len(decisions)},
                coverage_gain_offers=coverage("kb_category")["offers"],local=coverage("local_category"),selected=coverage("kb_category"),questions=len(decisions),
                sent=sum(bool(d.get("sent")) for d in decisions),cached=sum(bool(d.get("cached")) for d in decisions),
                jev_answers=sum(d["source"]=="jev" for d in decisions),usd=sum(d["usd"] for d in decisions),
                fallback=dict(Counter(d["fallback"] for d in decisions if d.get("fallback"))))


def import_feed(path,out,kb,cfg,mode,budget,dry,report_path,transport=None):
    import os
    from tempfile import TemporaryDirectory
    from kuznitsa.data_lock import snapshot_lock
    if report_path and Path(report_path).resolve() in {(out/name).resolve() for name in ("feed_classes.json","feed_categories.json")}:
        raise ValueError("Путь отчёта совпадает со справочником фида")
    if not dry:
        out.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=None if dry else out) as tmp:
        stage=Path(tmp)
        summary=build(path,stage,kb)
        if mode=="jev":
            copy_decisions(out/"import_ai.sqlite",stage/"import_ai.sqlite")
        ai=map_classes(stage,kb,cfg,mode,budget,transport,dry)
        if (stage/"import_ai.sqlite").is_file():
            with closing(sqlite3.connect(stage/"import_ai.sqlite")) as db:
                ai["cache_lifetime_usd"]=db.execute("SELECT coalesce(sum(cost_usd),0) FROM llm_calls").fetchone()[0]
        if not dry:
            classes=json.loads((stage/"feed_classes.json").read_text())
            with (stage/"catalog.jsonl").open() as src,(stage/"resolved.jsonl").open("w") as dest:
                for line in src:
                    row=json.loads(line)
                    category=classes.get(row["attrs"].get("class_id"),{}).get("kb_category")
                    if category:
                        row["attrs"]["kb_category"]=category
                    class_id=row["attrs"].get("class_id")
                    row["category_id"]=category or ("auto_sl_"+class_id if class_id else None)
                    dest.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
            os.replace(stage/"resolved.jsonl",stage/"catalog.jsonl")
        count=summary["offers"]
        report=dict(feed=summary,rows=count,offers=count,rejected=0,duplicates=0,inactive=0,ai=ai,
                    currency={"currency":"RUB"},attributes=summary.pop("attributes"),merge={"matched":{},"conflicts":{}},
                    sources={str(path):{"offers":count,"rows":count}},issues=[])
        body=json.dumps(report,ensure_ascii=False,indent=2)
        if not dry:
            (stage/"import_report.json").write_text(body)
            (stage/"inactive_offers.jsonl").touch()
            auto=[dict(id="auto_sl_"+key,title=r["path"][-1],synonyms=[]) for key,r in classes.items() if not r["kb_category"]]
            (stage/"kb_auto.yaml").write_text(yaml.safe_dump({"categories":auto},allow_unicode=True,sort_keys=False))
            with snapshot_lock(out,write=True):
                for f in stage.iterdir():
                    os.replace(f,out/f.name)
        if report_path:
            Path(report_path).write_text(body)
        return report
