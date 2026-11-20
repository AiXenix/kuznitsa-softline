import re
from .quantities import number_before,numeric_conditions
from kuznitsa.kb.lexicon import GROUP, many

MULTI = {"family","vendor","category","platform","edition","certs"}


def assign(target,k,v):
    if k in MULTI:
        vals = target.setdefault(k,[])
        for item in many(v):
            if item not in vals:
                vals.append(item)
    else:
        target[k] = v


def extract(words,lex,kb):
    filters,exclude,entities = {},{},[]
    qty = None
    used = set()
    for i,end,matches in lex.match(words):
        target = exclude if i and words[i-1] in {"не","без","кроме"} else filters
        kinds = {k for k,v,s in matches}
        for k,v,source in matches:
            if k in {"category","vendor","platform"} and "family" in kinds:
                continue
            if k=="category" and "vendor" in kinds:
                continue
            if k=="metric" and number_before(words,i):
                qty = dict(value=number_before(words,i),metric=v)
                used.add(i-1)
            if k=="compliance":
                effect = kb.rows["compliance"].get(v,{}).get("effect",{}).get("filter",{})
                for key,value in effect.items():
                    assign(target,key,value)
            elif k in MULTI or k in {"action","model","audience","delivery","registry","deployment","origin","metric"}:
                assign(target,k,{"yes":True,"no":False}.get(v,v) if k=="registry" else v)
            if k=="edition" and v=="pro" and any(x[0]=="edition" and str(x[1]).lower()=="pro" and x[1]!=v for x in matches):
                continue
            entities.append(dict(type=k,id=v,text=" ".join(words[i:end]),span=[i,end],source=source,conf=1.))
            used.update(range(i,end))
    qty = numeric_conditions(words,filters,qty)
    for i,w in enumerate(words):
        if i and "family" in filters and re.fullmatch(r"\d+(?:\.\d+)*",w):
            versions = {str(x) for fid in filters["family"] for x in kb.rows["families"].get(fid,{}).get("versions",[])}
            if w in versions:
                filters["version"] = w
    return filters,exclude,entities,qty," ".join(w for i,w in enumerate(words) if i not in used)
