import hashlib
from .pricing import price as license_price, edition_ranks
from .naming import sku_name
import json
import os
import random
import re
from tempfile import NamedTemporaryFile, TemporaryDirectory
from kuznitsa.data_lock import snapshot_lock
from pathlib import Path
from kuznitsa.schema import Offer, License
from math import prod
from kuznitsa.mock.clients_gen import configured_clients,date_client
from collections import defaultdict
from datetime import datetime,timezone,timedelta


def fallback():
    result = {}
    for line in Path(__file__).with_name("fallback.tsv").read_text().splitlines():
        ident,vendor,cat,title,aliases,editions = line.split("\t")
        result[ident] = dict(id=ident,name=title,vendor=vendor,category=cat,aliases=aliases.split("|"),
                             editions=[dict(id={"Стандартный":"standard","Расширенный":"advanced","ПРОФ":"prof","КОРП":"corp"}.get(x,x.lower().replace(" ","_")),name=x) for x in editions.split("|") if x],
                             license=dict(actions=["new","renewal","addon","support"],bands=["1-4","5-9","10-14","15-19","20-24","25-49","50-99","100-149","150-249","250-499","500-999","1000+"]),
                             catalog=ident!="autocad",analogs=["nanocad","zwcad"] if ident=="autocad" else [])
    # Условия демо привязаны к способу поставки соответствующего семейства.
    result["kaspersky_ksos"]["license"].update(bands=["5-9","10-14","15-19","20-25"])
    result["windows_11"]["license"].update(models=["perpetual"],actions=["new"],bands=["1-9","10-49","50-99","100+"])
    result["windows_11"]["delivery"]=["esd","box"]
    result["kaspersky_kesb"]["price_rub"]={"typical":2680}
    return result


def write_lines(path, lines):
    with NamedTemporaryFile("w",dir=path.parent,delete=False) as out:
        for line in lines:
            out.write(line+"\n")
    os.replace(out.name,path)


def offers_for(f,vendor,seed,limit):
    rng = random.Random(f"{seed}:{f['id']}")
    lic = f.get("license",{})
    bands = lic.get("bands") or ([] if lic.get("packs") else ["1-9","10-24","25-49","50-99","100-249","250+"])
    sizes = []
    for band in bands:
        nums = [int(n) for n in re.findall(r"\d+",str(band))]
        if nums:
            sizes.append((nums[0],nums[1] if len(nums)>1 else None,None))
    sizes.sort()
    sizes += [(None,None,int(p)) for p in lic.get("packs",[]) if str(p).isdigit() and 0<int(p)<=(f.get("max_seats") or float("inf"))]
    base = (f.get("price_rub") or {}).get("typical") or rng.randint(1500,4400)
    models = lic.get("models") or ["subscription"]
    terms = [(m,t) for m in models for t in ([None] if m=="perpetual" else lic.get("terms_months") or [12,24,36])]
    dimensions=(lic.get("actions") or ["new","renewal"],terms,sizes or [(None,None,None)],
                lic.get("audiences") or ["business","gov","edu"],lic.get("metrics") or ["device"],
                f.get("delivery") or ["esd"],f.get("versions") or [None])
    count=prod(map(len,dimensions))
    editions = f.get("editions") or [{}]
    for rank,ed in zip(edition_ranks(editions), editions):
        # Выбираем номера комбинаций. Полный декартов продукт не размещается в памяти.
        indices=rng.sample(range(count),min(count,max(12,limit//len(editions))))
        def unpack(index):
            parts=[]
            for dimension in reversed(dimensions):
                index,offset=divmod(index,len(dimension))
                parts.append(dimension[offset])
            return reversed(parts)
        from itertools import product
        preferred_term=next((t for t in terms if t[1]==12),terms[0])
        anchors=product(dimensions[0], [preferred_term], dimensions[2], dimensions[3], dimensions[4][:1], dimensions[5][:1],dimensions[6][:1])
        # Представительный вариант каждого диапазона нужен и в маленькой выборке.
        anchors=list(anchors)
        # Для каждой редакции держим базовый годовой вариант во всех аудиториях
        # и диапазонах. Сложные и популярные семейства получают больше SKU.
        budget=len(indices)
        essential=[a for a in anchors if a[0] in ("new","renewal") and (a[3] in ("business","gov","edu",dimensions[3][0]))]
        edition_text=(ed.get("title") or ed.get("name") or "").lower()
        restrict=("edu" if re.search("образован|учебн|academic",edition_text) else
                  "gov" if "государствен" in edition_text else "home" if "домашн" in edition_text else None)
        sampled=[tuple(unpack(i)) for i in indices]
        representative=product(dimensions[0][:1], [next(t for t in terms if t[0]==m) for m in models],
                               dimensions[2][:1], dimensions[3][:1], dimensions[4], dimensions[5][:1], dimensions[6][:1])
        options=list(dict.fromkeys([*essential,*representative,*sampled[:budget],*anchors[:2]]))
        if restrict and restrict in dimensions[3]:
            options=[a for a in options if a[3]==restrict]
        edition_metric = next((target for target,pattern in [
            ("device", r"рабочих станций|workstation|desktop"), ("server", r"сервер|server")
        ] if target in dimensions[4] and re.search(pattern,edition_text)), None)
        emitted = set()
        for action,(model,term),(lo,hi,pack),aud,metric,delivery,version in options:
            metric = edition_metric or metric
            price=license_price(f,rank,sizes.index((lo,hi,pack)) if lo else 0,pack,term,action,aud,base)
            identity = (f["id"],ed.get("id"),action,term,model,lo,hi,pack,aud,metric,delivery,version)
            if identity in emitted:
                continue
            emitted.add(identity)
            serial = hashlib.blake2s(repr(identity).encode(),digest_size=6).hexdigest().upper()
            prefix = {"kaspersky":"KL","microsoft":"FQC","drweb":"DWL"}.get(f.get("vendor"),"AX")
            sku = f"{prefix}-{serial}"
            name = sku_name(f,ed,version,action,term,lo,hi,pack,aud,metric,delivery)
            common = action in ("new","renewal") and (model,term)==preferred_term and delivery==dimensions[5][0]
            por = price>75000 and rng.random()<.08 and not common
            platforms = list(dict.fromkeys(f.get("platforms",[])+f.get("compat_ru_os",[])+(["linux"] if f.get("compat_ru_os") else [])))
            registry = f.get("registry") if isinstance(f.get("registry"),bool) and f.get("confidence")!="low" else None
            yield Offer(offer_id="o_"+serial,sku=sku,name=name,vendor=vendor,vendor_id=f.get("vendor"),family_id=f["id"],
                        family_name=f["name"],edition=ed.get("id"),version=str(version) if version else None,category_id=f.get("category"),
                        description=f.get("summary",""),platforms=platforms,registry=registry,certs=f.get("certs",[]) if f.get("confidence")!="low" else [],
                        delivery=delivery,lic=License(action=action,model=model,term_months=term,qty_min=lo,qty_max=hi,pack=pack,
                        metric=metric,audience=aud),price=None if por else price,attrs={"promo":"true"} if int(serial[-2:],16)%13==0 and action=="new" else {},
                        kind="course" if f.get("category")=="it_training_courses" else "service" if f.get("category")=="tech_support" else "license",
                        price_on_request=por,vat=0 if registry else None,
                        popularity=min(1,(f.get("popularity") or 3)/6+rng.random()*.16),margin=rng.uniform(.08,.4),available=rng.random()>.015 or common)


def seed_defects(offers):
    cards=defaultdict(list)
    for o in offers:
        cards[o.card_id].append(o)
    labels={}
    remove=set()
    def missing_tier(o):
        # Годовые ступени основных сегментов нужны для сравнения цен.
        primary = o.lic.term_months == 12 and o.lic.audience in ("business", "gov", "edu")
        return o.lic.qty_min in (25,50) and not primary

    for code,categories,limit in [("INS-07",{"backup_recovery","ngfw_vpn"},14),("INS-08",{"office_suite","cad_2d"},9),
                                  ("INS-09",{"endpoint_security"},11)]:
        eligible=[c for c,rows in cards.items() if rows[0].category_id in categories]
        if code=="INS-07":
            eligible=[c for c in eligible if {"astra","redos"}.intersection(cards[c][0].platforms)]
        if code=="INS-08":
            eligible=[c for c in eligible if any(o.registry for o in cards[c])]
        if code=="INS-09":
            eligible=[c for c in eligible if any(missing_tier(o) for o in cards[c])]
            eligible.sort(key=lambda c:(any(o.sku and not "-" in o.sku for o in cards[c]),"kesb" in c or "ksos" in c,c))
        for c in eligible[:limit]:
            labels[c]=code
            for o in cards[c]:
                if code=="INS-07":
                    o.platforms=[v for v in o.platforms if v not in ("astra","redos")]
                elif code=="INS-08":
                    o.registry,o.vat=None,22
                elif missing_tier(o):
                    remove.add(o.offer_id)
    return [o for o in offers if o.offer_id not in remove],labels


def demo_record(o,today,vendors):
    marker=int(hashlib.blake2s(o.offer_id.encode(),digest_size=4).hexdigest(),16)
    fields=dict(in_stock=o.available and (o.delivery=="esd" or marker%5!=0),
                added_at=str(today-timedelta(days=marker%540)),promo=o.attrs.get("promo")=="true",
                domestic=bool(o.registry or vendors.get(o.vendor_id,{}).get("origin")=="russian"))
    fields["delivery_days"]=0 if fields["in_stock"] else 2+marker%12 if o.available else None
    row=o.model_dump(exclude_none=True,exclude_defaults=True)
    row["attrs"]={**o.attrs,**{k:(str(v).lower() if isinstance(v,bool) else str(v))
                              for k,v in fields.items() if v is not None}}
    return json.dumps({**row,**fields},ensure_ascii=False,separators=(",",":"))


def build(cfg,kb,seed=20261126,today=None):
    cfg.data.mkdir(parents=True,exist_ok=True)
    real = kb.rows["families"]
    supplement = fallback() if len(real)<40 else {}
    supplement = {k:v for k,v in supplement.items() if k not in real and v["name"].casefold() not in {r["name"].casefold() for r in real.values()}}
    families = {**supplement,**real}
    active = [f for f in families.values() if f.get("catalog",True) and f["id"] not in {"cursor","cursor_ide","yandex_tracker","obsidian"}]
    offers = []
    for f in active:
        vendor = kb.rows["vendors"].get(f.get("vendor"),{}).get("name",f.get("vendor"))
        offers.extend(offers_for(f,vendor,seed,max(32,22000//max(1,len(active)))))
    from .sample_codes import apply_sample_codes
    apply_sample_codes(offers)
    offers,defects=seed_defects(offers)
    today=today or datetime.now(timezone(timedelta(hours=3))).date()
    with TemporaryDirectory(dir=cfg.data) as temporary:
        stage=Path(temporary)
        write_lines(stage/"catalog.jsonl",(demo_record(o,today,kb.rows["vendors"]) for o in offers))
        write_lines(stage/"mock_defects.jsonl",(json.dumps(dict(card_id=k,insight=v,**({"scope":"secondary_segments_or_nonannual","qty_min":[25,50]} if v=="INS-09" else {}))) for k,v in defects.items()))
        profiles=configured_clients(cfg.kb.parent/"mock/spec",offers,seed)
        write_lines(stage/"clients.jsonl",(date_client(c,today).model_dump_json() for c in profiles))
        write_lines(stage/"mock_families.jsonl",(json.dumps(f,ensure_ascii=False) for f in supplement.values()))
        with snapshot_lock(cfg.data,write=True):
            for source in stage.iterdir():
                os.replace(source,cfg.data/source.name)
    return len(offers)
