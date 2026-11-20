import hashlib
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
from kuznitsa.mock.clients_gen import clients, demo_overrides


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
    sizes += [(None,None,int(p)) for p in lic.get("packs",[]) if str(p).isdigit() and int(p)>0]
    base = (f.get("price_rub") or {}).get("typical") or rng.randint(1500,4400)
    models = lic.get("models") or ["subscription"]
    terms = [(m,t) for m in models for t in ([None] if m=="perpetual" else lic.get("terms_months") or [12,24,36])]
    dimensions=(lic.get("actions") or ["new","renewal"],terms,sizes or [(None,None,None)],
                lic.get("audiences") or ["business","gov","edu"],lic.get("metrics") or ["device"],
                f.get("delivery") or ["esd"],f.get("versions") or [None])
    count=prod(map(len,dimensions))
    editions = f.get("editions") or [{}]
    for ed in editions:
        # Выбираем номера комбинаций. Полный декартов продукт не размещается в памяти.
        indices=rng.sample(range(count),min(count,max(12,limit//len(editions))))
        def unpack(index):
            parts=[]
            for dimension in reversed(dimensions):
                index,offset=divmod(index,len(dimension))
                parts.append(dimension[offset])
            return reversed(parts)
        options=map(unpack,indices)
        for action,(model,term),(lo,hi,pack),aud,metric,delivery,version in options:
            price = round(float(base)*(1 if action=="new" else .72)*({"edu":.47,"gov":.89}.get(aud,1))*
                          (int(term or 12))/12*(pack or 1)/(1+min(lo or 1,500)/1000))
            identity = (f["id"],ed.get("id"),action,term,model,lo,hi,pack,aud,metric,delivery,version)
            serial = hashlib.blake2s(repr(identity).encode(),digest_size=6).hexdigest().upper()
            prefix = {"kaspersky":"KL","microsoft":"FQC","drweb":"DWL"}.get(f.get("vendor"),"AX")
            sku = f"{prefix}-{serial}"
            name = sku_name(f,ed,version,action,term,lo,hi,pack,aud,metric,delivery)
            por = rng.random()<.025
            platforms = list(dict.fromkeys(f.get("platforms",[])+f.get("compat_ru_os",[])+(["linux"] if f.get("compat_ru_os") else [])))
            registry = f.get("registry") if isinstance(f.get("registry"),bool) and f.get("confidence")!="low" else None
            yield Offer(offer_id="o_"+serial,sku=sku,name=name,vendor=vendor,vendor_id=f.get("vendor"),family_id=f["id"],
                        family_name=f["name"],edition=ed.get("id"),version=str(version) if version else None,category_id=f.get("category"),
                        description=f.get("summary",""),platforms=platforms,registry=registry,certs=f.get("certs",[]) if f.get("confidence")!="low" else [],
                        delivery=delivery,lic=License(action=action,model=model,term_months=term,qty_min=lo,qty_max=hi,pack=pack,
                        metric=metric,audience=aud),price=None if por else price,price_on_request=por,vat=0 if registry else None,
                        popularity=min(1,(f.get("popularity") or 3)/6+rng.random()*.16),margin=rng.uniform(.08,.4),available=rng.random()>.015)


def build(cfg,kb,seed=20261126):
    cfg.data.mkdir(parents=True,exist_ok=True)
    real = kb.rows["families"]
    supplement = fallback() if len(real)<40 else {}
    supplement = {k:v for k,v in supplement.items() if k not in real and v["name"].casefold() not in {r["name"].casefold() for r in real.values()}}
    families = {**supplement,**real}
    active = [f for f in families.values() if f.get("catalog",True)]
    offers = []
    for f in active:
        vendor = kb.rows["vendors"].get(f.get("vendor"),{}).get("name",f.get("vendor"))
        offers.extend(offers_for(f,vendor,seed,max(32,22000//max(1,len(active)))))
    with TemporaryDirectory(dir=cfg.data) as temporary:
        stage=Path(temporary)
        write_lines(stage/"catalog.jsonl",(o.model_dump_json(exclude_none=True,exclude_defaults=True) for o in offers))
        profiles=demo_overrides(cfg.kb.parent/"mock/spec/profiles.yaml",offers,clients(offers,seed))
        write_lines(stage/"clients.jsonl",(c.model_dump_json() for c in profiles))
        write_lines(stage/"mock_families.jsonl",(json.dumps(f,ensure_ascii=False) for f in supplement.values()))
        with snapshot_lock(cfg.data,write=True):
            for source in stage.iterdir():
                os.replace(source,cfg.data/source.name)
    return len(offers)
