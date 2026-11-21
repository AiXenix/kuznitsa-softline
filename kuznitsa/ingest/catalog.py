"""Normalize supplier catalogs into a validated, staged catalog snapshot."""
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from itertools import chain, islice
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory

import yaml

from kuznitsa.data_lock import snapshot_lock
from kuznitsa.kb.loader import load
from kuznitsa.schema import License
from .adapters import tables
from .enrich import Enricher, number
from .mapping import field_for, infer
from .nameparse import Parser

TITLES = dict(bad_row="Строка пропущена: проверьте формат данных", inactive="Позиция снята с продажи", duplicate="Повтор предложения или артикула",
              no_price="Цена не заполнена", zero_price="Указана нулевая цена", request_price="Цена по запросу",
              invalid_price="Некорректная цена", no_description="Нет описания товара", no_vendor="Не указан производитель",
              no_category="Не указана категория", price_outlier="Цена отличается от медианы семейства более чем в 10 раз")


def import_catalog(files, out, kb, mapping=None, report_path=None, dry_run=False, *, ai="embed", ai_budget_usd=.5, transport=None, config=None):
    files=list(map(Path,files))
    out=Path(out)
    if report_path and Path(report_path).resolve() in {
        *(p.resolve() for p in files), (out/"catalog.jsonl").resolve(), (out/"kb_auto.yaml").resolve(), (out/"import_ai.sqlite").resolve(), (out/"import_ai.jsonl").resolve()
    }:
        raise ValueError("Путь отчёта совпадает с каталогом или входным файлом")
    explicit=yaml.safe_load(Path(mapping).read_text()) if mapping else {}
    from kuznitsa.config import Config
    from math import isfinite
    if ai not in {"off","embed","jev"} or not isfinite(ai_budget_usd) or ai_budget_usd<0:
        raise ValueError("Проверьте режим и бюджет раскладки")
    cfg=config or Config(data=out,kb=kb)
    from .product_rules import apply as product_rules
    observations={}
    other_categories=set()
    parser=Parser(load(kb))
    categories={}
    enricher=Enricher(parser,categories)
    issues={}
    counts=Counter()
    recognized=Counter()
    unmatched={g:Counter() for g in ("vendors","families")}
    examples=[]
    prices=defaultdict(list)
    columns={}
    sources={}
    seen=set()
    skus=set()
    signals=Counter()
    def issue(code,example):
        item=issues.setdefault(code,dict(code=code,title=TITLES[code],count=0,examples=[]))
        item["count"]+=1
        if len(item["examples"])<5:
            item["examples"].append(example)

    merge_stats=dict(matched=Counter(),conflicts=Counter(),examples=[])
    rates={}
    from .variants import Commerce,is_commerce
    commerce=Commerce()
    commerce_files=[p for p in files if is_commerce(p)]
    for path in commerce_files:
        list(commerce.read(path,metadata_only=True))
    def scan(reference_pass):
        for path in files:
            for label,rows in tables(path,explicit,commerce):
                first=list(islice(rows,25))
                sample=[row for _,row in first if row]
                headers=list(dict.fromkeys(k for row in sample for k in row))
                fields=infer(headers,sample,explicit,parser)
                ref=bool({"id","category_id"}.intersection(fields.values()) and
                         ("parent" in fields.values() or label.rsplit("/",1)[-1].split(".")[0].lower() in ("categories","категории"))
                         and "price" not in fields.values() and "sku" not in fields.values())
                if ref!=reference_pass:
                    continue
                used=sources.setdefault(label,dict(columns={},unused=[]))
                def remember(h,key):
                    if key:
                        used["columns"][key]=h
                        columns.setdefault(key,h)
                    elif h not in used["unused"]:
                        used["unused"].append(h)
                for h,key in fields.items():
                    remember(h,key)
                for num,row in chain(first,rows):
                    data={}
                    extra={}
                    for h,v in (row or {}).items():
                        if h not in fields:
                            fields[h]=field_for(h)
                            remember(h,fields[h])
                        if h in ("_product","_parent_id","_variant_identity"):
                            data[h]=v
                        elif v is None and row.get("offer_id") and fields[h] in ("source_id","in_stock","delivery_days","added_at","promo","domestic"):
                            data[fields[h]]=None
                        elif fields[h] and v is not None and v!="":
                            key=fields[h]
                            if key in ("sku","source_id","id","guid","store_id","supplier_sku") and key in data:
                                data.setdefault("_aliases",[]).append(data[key])
                            if key=="aliases" and key in data:
                                from .source_fields import alias_list
                                v=list(dict.fromkeys(alias_list(data[key])+alias_list(v)))
                            data[key]=v
                        elif not fields[h] and v not in (None,""):
                            extra[h]=v
                    if extra:
                        data["_extra"]=extra
                    if ref:
                        used["reference_rows"]=used.get("reference_rows",0)+1
                        ident=data.get("id",data.get("category_id"))
                        if ident is not None:
                            used["references"]=used.get("references",0)+1
                            categories[str(ident)]=(data.get("name") or data.get("category_path"),str(data.get("parent","")))
                    else:
                        if not data.get("offer_id"):
                            units={}
                            for key in ("price","cost"):
                                if key in data:
                                    header=used["columns"].get(key,"").casefold()
                                    currency=str(data.get("currency") or "").upper()
                                    units[key]="USD" if "usd" in header or "$" in header else currency
                            if units:
                                data["_field_currency"]=units
                        if data.get("currency_rate") and data.get("currency"):
                            rates[str(data["currency"]).upper()]=number(data["currency_rate"])
                        yield label,num,data

    for _ in scan(True):
        pass
    if not dry_run:
        out.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=None if dry_run else out) as tmp:
        stage=Path(tmp)
        with (stage/"catalog.jsonl").open("w",encoding="utf8") as stream:
            from .join import merge
            from .source_fields import decorate,wire_attrs
            rows=scan(False)
            if len(files)>1 or commerce_files or any(p.suffix.lower()==".xlsx" for p in files):
                rows=merge(rows,merge_stats)
            for label,num,row in rows:
                counts["rows"]+=1
                example=dict(file=label,row=num,name=str(row.get("name",""))[:220])
                source=sources[label]
                source["rows"]=source.get("rows",0)+1
                if str(row.get("status","")).strip().casefold() in {"снято","снят с продажи","архив","discontinued","inactive"}:
                    counts["rejected"]+=1
                    issue("inactive",example)
                    continue
                converted=False
                units=row.pop("_field_currency",{})
                for key in ("price","cost"):
                    value=row.get(key)
                    currency=units.get(key,str(row.get("currency") or "").upper())
                    if value is None:
                        continue
                    if "$" in str(value) or "usd" in str(value).casefold():
                        currency="USD"
                    if currency in ("","RUB","RUR","643"):
                        continue
                    usd=currency in ("USD","840")
                    rate=(rates.get("USD") or cfg.usd_rub) if usd else rates.get(currency)
                    amount=number(str(value).replace("$","").upper().replace("USD",""))
                    if amount is not None:
                        row[key]=round(amount*rate,2) if rate and rate>0 else None
                        converted|=usd
                try:
                    native="offer_id" in row and isinstance(row.get("lic"),dict)
                    extension={k:row.pop(k) for k in ("source_ids","source_id","in_stock","delivery_days","added_at","promo","domestic") if native and k in row}
                    extra=row.pop("_extra",{})
                    if native and extension.get("source_ids"):
                        attrs=row.setdefault("attrs",{})
                        attrs.setdefault("source_ids",json.dumps(extension["source_ids"],ensure_ascii=False))
                        if extension.get("source_id"):
                            attrs.setdefault("source_id",extension["source_id"])
                    if not native:
                        extension=decorate(row)
                        if extra:
                            row["attrs"]["extra"]=json.dumps(extra,ensure_ascii=False,default=str)
                    offer,evidence,pending=enricher.convert(row)
                    if (row.get("source_id") or row.get("_tier") or row.get("_variant_identity")) and not native:
                        from .enrich import stable
                        identity=str(row.get("source_id") or offer.sku).casefold()
                        if row.get("_variant_identity"):
                            identity=row["_variant_identity"]
                        if row.get("_tier"):
                            identity+=f"|qty={row.get('qty_min','')}-{row.get('qty_max','')}"
                        offer.offer_id=stable("o_",identity)
                except (ValueError,TypeError,AttributeError,OverflowError) as exc:
                    counts["rejected"]+=1
                    issue("bad_row",{**example,"reason":str(exc)[:200]})
                    continue
                sku=(offer.sku or "").casefold()
                if offer.offer_id in seen or sku and sku in skus and not (row.get("source_id") or row.get("_tier") or row.get("_variant_identity")):
                    counts["duplicates"]+=1
                    issue("duplicate",example)
                    continue
                seen.add(offer.offer_id)
                if sku:
                    skus.add(sku)
                enricher.accept(offer,pending)
                imported_family=offer.family_id.startswith("auto_")
                native="offer_id" in row and isinstance(row.get("lic"),dict) and not imported_family
                if ai!="off" and (imported_family or (offer.category_path and not native)):
                    key=(offer.family_id,tuple(offer.category_path))
                    obs=observations.setdefault(key,dict(names=[],description="",category=offer.category_id,
                                                          vendor=offer.vendor or "",explicit_category=None,rules=set(),registry=set(),certs=None,count=0))
                    obs["count"]+=1
                    if row.get("category_id")==offer.category_id and offer.category_id in parser.kb["categories"]:
                        obs["explicit_category"]=offer.category_id
                    if len(obs["names"])<10 and offer.name not in obs["names"]:
                        obs["names"].append(offer.name[:220])
                    if not obs["description"]:
                        obs["description"]=offer.description[:600]
                    if imported_family:
                        obs["rules"].update(product_rules(offer))
                        declared=lambda k:k in evidence and evidence[k].source in ("column","attribute")
                        obs["registry"].add(offer.registry if declared("registry") else None)
                        certs=set(offer.certs) if declared("certs") else set()
                        obs["certs"]=certs if obs["certs"] is None else obs["certs"] & certs
                elif offer.category_id:
                    other_categories.add(offer.category_id)
                if ai!="off":
                    for field,empty in (("registry",None),("certs",[])):
                        if field in evidence and evidence[field].source not in ("column","attribute"):
                            setattr(offer,field,empty)
                            evidence.pop(field,None)
                source["offers"]=source.get("offers",0)+1
                counts["usd_rows"]+=converted
                counts["offers"]+=1
                record={**offer.model_dump(exclude_none=True),**extension}
                if not native:
                    record["attrs"]=wire_attrs(offer.attrs)
                stream.write(json.dumps(record,ensure_ascii=False,separators=(",",":"))+"\n")
                for key,val in [("vendor",offer.vendor_id),("family",offer.family_id),("edition",offer.edition),("category",offer.category_id)]:
                    recognized[key]+=bool(val and not val.startswith("auto_"))
                recognized["licence"]+=any(k in evidence for k in License.model_fields)
                for group,val,title in [("vendors",offer.vendor_id,offer.vendor),("families",offer.family_id,offer.family_name)]:
                    if val and val.startswith("auto_"):
                        unmatched[group][title]+=1
                if not offer.price:
                    raw=str(row.get("price",""))
                    code="request_price" if "запрос" in raw.lower() or "request" in raw.lower() or row.get("price_on_request") is True else (
                        "no_price" if not raw else "zero_price" if number(raw)==0 else "invalid_price")
                    issue(code,example)
                else:
                    prices[offer.family_id].append((offer.price,example))
                for field,code in [(offer.vendor,"no_vendor"),(row.get("category_id") or row.get("category_path"),"no_category"),
                                   (offer.description,"no_description")]:
                    if not field:
                        issue(code,example)
                for key,signal in [("popular","popularity"),("margin","margin")]:
                    if signal in evidence and evidence[signal].source!="default":
                        signals[key]+=1
                if len(examples)<3:
                    examples.append({**example,"fields":{k:asdict(v) for k,v in evidence.items()
                                    if k in License.model_fields or k in ("vendor_id","family_id","edition","version","category_id","delivery","certs","registry","language")}})
        for group in prices.values():
            if len(group)>=3:
                middle=median(p for p,_ in group)
                for p,example in group:
                    if p>middle*10 or p<middle/10:
                        issue("price_outlier",{**example,"price":p,"median":middle})
        from .classify import classify
        ai_report=classify(parser.kb,enricher.auto,observations,stage,cfg,ai,ai_budget_usd,dry_run,transport)
        if observations:
            used=set(other_categories)
            for obs in observations.values():
                used.add(obs["resolved"])
                recognized["category"]+=obs["count"]*(int(obs["resolved"] in parser.kb["categories"])-int(obs["category"] in parser.kb["categories"]))
            auto_categories=enricher.auto["categories"]
            for key in list(used):
                while key in auto_categories:
                    key=auto_categories[key].get("parent")
                    if key in used:
                        break
                    used.add(key)
            enricher.auto["categories"]={k:r for k,r in auto_categories.items() if k in used}
        if observations and not dry_run:
            with (stage/"catalog.jsonl").open() as src,(stage/"resolved.jsonl").open("w") as dest:
                for line in src:
                    row=json.loads(line)
                    key=row["family_id"],tuple(row.get("category_path",[]))
                    if key in observations:
                        row["category_id"]=observations[key]["resolved"]
                        line=json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n"
                    dest.write(line)
            os.replace(stage/"resolved.jsonl",stage/"catalog.jsonl")
        ai_report["coverage_gain_offers"]=sum(o["count"] for o in observations.values() if o["category"] not in parser.kb["categories"] and o["resolved"] in parser.kb["categories"])
        # These three record types have different extension points in the KB schema.
        for family in enricher.auto["families"].values():
            # Decision-level probabilities and evidence are already in import_ai.jsonl.
            family["confidence"]="low"
            family.pop("classification_confidence",None)
            family.pop("analog_suggestions",None)
        for group,field in (("vendors","notes"),("categories","description")):
            for item in enricher.auto[group].values():
                item.setdefault(field,"Уверенность низкая. Автозапись из каталога поставщика требует проверки.")
        auto={g:list(items.values()) for g,items in enricher.auto.items()}
        notes=[]
        if signals["popular"]<counts["offers"]:
            notes.append("Для части товаров популярность нейтральна. Загрузите продажи, рейтинг, остатки или историю заказов.")
        if signals["margin"]<counts["offers"]:
            notes.append("Для части товаров маржа нейтральна. Загрузите маржу или закупочную цену.")
        report=dict(merge=merge_stats,currency=dict(usd_rub=rates.get("USD") or cfg.usd_rub,converted_rows=counts["usd_rows"]),ai=ai_report,exchange_rates=rates,ts=datetime.now(timezone.utc).isoformat(),files=list(map(str,files)),
                    **{k:counts[k] for k in ("rows","offers","duplicates","rejected")},columns=columns,sources=sources,
                    recognized={k:recognized[k]/max(1,counts["offers"]) for k in ("vendor","family","edition","category","licence")},
                    auto={g:len(vals) for g,vals in auto.items()},issues=list(issues.values()),notes=notes,examples=examples,
                    unmatched={g:[dict(name=n,rows=c) for n,c in cnt.most_common()] for g,cnt in unmatched.items()})
        body=json.dumps(report,ensure_ascii=False,indent=2,default=str)
        if not dry_run and counts["offers"]:
            (stage/"kb_auto.yaml").write_text(yaml.safe_dump(auto,allow_unicode=True,sort_keys=False))
            (stage/"import_report.json").write_text(body)
            with snapshot_lock(out,write=True):
                for name in ("catalog.jsonl","kb_auto.yaml","import_ai.jsonl","import_report.json"):
                    os.replace(stage/name,out/name)
        if report_path:
            Path(report_path).write_text(body)
        return report
