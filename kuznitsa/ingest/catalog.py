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

TITLES = dict(bad_row="Строка пропущена: проверьте формат данных", duplicate="Повтор предложения или артикула",
              no_price="Цена не заполнена", zero_price="Указана нулевая цена", request_price="Цена по запросу",
              invalid_price="Некорректная цена", no_description="Нет описания товара", no_vendor="Не указан производитель",
              no_category="Не указана категория", price_outlier="Цена отличается от медианы семейства более чем в 10 раз")


def import_catalog(files, out, kb, mapping=None, report_path=None, dry_run=False):
    files=list(map(Path,files))
    out=Path(out)
    if report_path and Path(report_path).resolve() in {
        *(p.resolve() for p in files), (out/"catalog.jsonl").resolve(), (out/"kb_auto.yaml").resolve()
    }:
        raise ValueError("Путь отчёта совпадает с каталогом или входным файлом")
    explicit=yaml.safe_load(Path(mapping).read_text()) if mapping else {}
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

    def scan(reference_pass):
        for path in files:
            for label,rows in tables(path,explicit):
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
                    for h,v in (row or {}).items():
                        if h not in fields:
                            fields[h]=field_for(h)
                            remember(h,fields[h])
                        if fields[h] and v is not None and v!="":
                            data[fields[h]]=v
                    if ref:
                        ident=data.get("id",data.get("category_id"))
                        if ident is not None:
                            categories[str(ident)]=(data.get("name") or data.get("category_path"),str(data.get("parent","")))
                    else:
                        yield label,num,data

    for _ in scan(True):
        pass
    if not dry_run:
        out.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=None if dry_run else out) as tmp:
        stage=Path(tmp)
        with (stage/"catalog.jsonl").open("w",encoding="utf8") as stream:
            for label,num,row in scan(False):
                counts["rows"]+=1
                example=dict(file=label,row=num,name=str(row.get("name",""))[:220])
                try:
                    offer,evidence,pending=enricher.convert(row)
                except (ValueError,TypeError,AttributeError,OverflowError) as exc:
                    counts["rejected"]+=1
                    issue("bad_row",{**example,"reason":str(exc)[:200]})
                    continue
                sku=(offer.sku or "").casefold()
                if offer.offer_id in seen or sku and sku in skus:
                    counts["duplicates"]+=1
                    issue("duplicate",example)
                    continue
                seen.add(offer.offer_id)
                if sku:
                    skus.add(sku)
                enricher.accept(offer,pending)
                counts["offers"]+=1
                stream.write(offer.model_dump_json(exclude_none=True)+"\n")
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
        auto={g:list(items.values()) for g,items in enricher.auto.items()}
        notes=[]
        if signals["popular"]<counts["offers"]:
            notes.append("Для части товаров популярность нейтральна. Загрузите продажи, рейтинг, остатки или историю заказов.")
        if signals["margin"]<counts["offers"]:
            notes.append("Для части товаров маржа нейтральна. Загрузите маржу или закупочную цену.")
        report=dict(ts=datetime.now(timezone.utc).isoformat(),files=list(map(str,files)),
                    **{k:counts[k] for k in ("rows","offers","duplicates","rejected")},columns=columns,sources=sources,
                    recognized={k:recognized[k]/max(1,counts["offers"]) for k in ("vendor","family","edition","category","licence")},
                    auto={g:len(vals) for g,vals in auto.items()},issues=list(issues.values()),notes=notes,examples=examples,
                    unmatched={g:[dict(name=n,rows=c) for n,c in cnt.most_common()] for g,cnt in unmatched.items()})
        body=json.dumps(report,ensure_ascii=False,indent=2,default=str)
        if not dry_run and counts["offers"]:
            (stage/"kb_auto.yaml").write_text(yaml.safe_dump(auto,allow_unicode=True,sort_keys=False))
            (stage/"import_report.json").write_text(body)
            with snapshot_lock(out,write=True):
                for name in ("catalog.jsonl","kb_auto.yaml","import_report.json"):
                    os.replace(stage/name,out/name)
        if report_path:
            Path(report_path).write_text(body)
        return report
