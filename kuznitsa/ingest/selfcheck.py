"""Black-box probes against Engine.search; expectations come from the imported offers."""
from collections import Counter, defaultdict
import random
import re
from time import perf_counter

import numpy as np

from kuznitsa.engine import Engine
from kuznitsa.mock.naming import quantity_word
from kuznitsa.schema import Request
from .nameparse import normalize
from kuznitsa.understand.repair import LAYOUT

LETTERS=dict(zip("abcdefghijklmnopqrstuvwxyz","абкдефгхидклмнопкрстуввкйз"))
DIGRAPHS={"sh":"ш","ch":"ч","ph":"ф","th":"т","ck":"к","oo":"у","ee":"и","qu":"кв","x":"кс","j":"дж","y":"й"}


def sample(offers,n,rng):
    pools=defaultdict(list)
    for offer in offers:
        pools[offer.vendor_id,offer.category_id].append(offer)
    for items in pools.values():
        rng.shuffle(items)
    vendors,cats=Counter(),Counter()
    keys=list(pools)
    rng.shuffle(keys)
    while keys and n>0:
        key=min(keys,key=lambda k:vendors[k[0]]+cats[k[1]])
        yield pools[key].pop()
        if not pools[key]:
            keys.remove(key)
        vendors[key[0]]+=1
        cats[key[1]]+=1
        n-=1


def probes(o,kb,rng):
    family=o.family_name or o.name
    f=kb["families"].get(o.family_id,{})
    family=f.get("title") or family
    edition=next((e.get("title") or e.get("name") for e in f.get("editions",[]) if e["id"]==o.edition),o.edition)
    title=" ".join(filter(None,[family,edition]))
    ed=next((e for e in f.get("editions",[]) if e["id"]==o.edition),{})
    spellings=[o.edition,edition,ed.get("name"),*ed.get("aliases",[])]
    normalized=" "+normalize(o.name)+" "
    mentions=any(s and " "+normalize(s)+" " in normalized for s in spellings)
    yield "exact",o.name,o.edition if mentions else None
    yield "short",title,o.edition
    if o.sku:
        kind="source_id" if o.attrs.get("feed_offer_id")==o.sku and len(o.source_ids)==1 else "sku"
        yield kind,o.sku,o.edition
    if o.vendor:
        yield "vendor_family"," ".join([o.vendor,family]),None
    choices=[i for i in range(len(title)-1) if title[i:i+2].isalpha() and title[i]!=title[i+1]]
    if choices:
        i=rng.choice(choices)
        yield "typo",title[:i]+title[i+1]+title[i]+title[i+2:],o.edition
    wrong=title.lower().translate(LAYOUT)
    if wrong!=title.lower():
        yield "layout",wrong,o.edition
    phon=re.sub(r"sh|ch|ph|th|ck|oo|ee|qu|[a-z]",lambda m:DIGRAPHS.get(m[0],LETTERS.get(m[0],m[0])),title.lower())
    if phon!=title.lower():
        yield "phonetic",phon,o.edition
    if o.lic.qty_min or o.lic.pack:
        lo=o.lic.qty_min or o.lic.pack
        num=min(lo+5,o.lic.qty_max or lo)
        unit="пк" if o.lic.metric=="device" else quantity_word(o.lic.metric,num)
        unit={"организация":"организацию","пользователь":"пользователя","виртуальная машина":"виртуальную машину","площадка":"площадку"}.get(unit,unit)
        yield "quantity",f"{title} на {num} {unit}",o.edition
    cat=kb["categories"].get(o.category_id,{}).get("title") or next(iter(o.category_path[-1:]),None)
    if o.attrs.get("class_id") and len(o.category_path)>1:
        cat=o.category_path[1]
    if cat and o.vendor:
        yield "class_vendor",f"{cat} {o.vendor}",None


def card_ids(response):
    result=[]
    for block in response["blocks"]:
        for item in block.get("items",[])+block.get("slots",[]):
            if not isinstance(item,dict):
                continue
            for card in [item.get("card") or item,*item.get("alternatives",[])]:
                if card.get("card_id") and card["card_id"] not in result:
                    result.append(card["card_id"])
    return result


def selfcheck(cfg,n,mode,seed,engine=None):
    if n<=0:
        raise ValueError("Размер выборки должен быть положительным")
    rng=random.Random(seed)
    from .ai_backend import search_client
    owns_engine=engine is None
    if owns_engine:
        engine=Engine.open(cfg,llm=search_client(mode))
    kb=engine.kb.rows
    if engine.decisions:
        engine.decisions.run_budget=cfg.daily_budget
    selection=list(sample(engine.catalog.offers_by_id.values(),n,rng))
    groups=defaultdict(lambda:defaultdict(list))
    worst=defaultdict(list)
    for o in selection:
        cohort="known" if o.family_id and not o.family_id.startswith("auto_") and o.family_id in kb["families"] else "unknown"
        for kind,q,ed in probes(o,kb,rng):
            start=perf_counter()
            error=None
            if len(q)>1500:
                ids=[]
                error="Название превышает ограничение поискового запроса (1500 символов)"
            else:
                ids=card_ids(engine.search(Request(q=q,page_size=5,source="eval",mode=mode,context="off",explain=False)))
            ms=(perf_counter()-start)*1000
            pos=next((i for i,c in enumerate(ids[:5],1) if (c==o.card_id if ed else c.split(":")[0]==o.family_id)),6)
            for group in ("all",cohort):
                groups[group][kind].append((pos,ms))
            if pos>3:
                examples=worst[kind]
                examples.append(dict(q=q,error=error,sku=o.sku,expected=o.card_id if ed else o.family_id,found=ids[:5],rank=pos if pos<=5 else None))
                examples.sort(key=lambda e:e["rank"] or 6,reverse=True)
                del examples[10:]
    def stats(values):
        pos,times=map(np.array,zip(*values))
        return dict(n=len(pos),top3=float(np.mean(pos<=3)),top5=float(np.mean(pos<=5)),
                    p50_ms=round(float(np.percentile(times,50)),2),p95_ms=round(float(np.percentile(times,95)),2))
    if owns_engine:
        engine.close()
    all_results=[v for values in groups["all"].values() for v in values]
    return dict(overall=stats(all_results) if all_results else {},n=len(selection),mode=mode,seed=seed,groups={g:{k:stats(v) for k,v in groups[g].items()} for g in ("all","known","unknown")},
                worst=worst)
