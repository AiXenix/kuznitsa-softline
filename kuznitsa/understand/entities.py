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
        if end==i+1 and words[i] in {"в","и","на","по","к","с","а","из","для","ошибка"}:
            continue
        for k,v,source in matches:
            if k=="edition" and all(w.isdigit() for w in words[i:end]):
                continue
            if k=="edition" and number_before(words,i) and words[i].startswith("рабоч") and end>i+1 and words[i+1].startswith("мест"):
                continue
            if k=="edition" and kinds & {"family","vendor","category","metric","industry","compliance"}:
                continue
            if k=="audience" and v=="home" and words[i].startswith("персональн") and end<len(words) and words[end].startswith("данн"):
                continue
            if k=="metric" and not number_before(words,i) and not any(w in words for w in ("cal","ядерная","ядер")):
                continue
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
            entities.append(dict(type=k,id=v,text=" ".join(words[i:end]),span=[i,end],source=source,conf=.81 if source=="phonetic" else 1.))
            used.update(range(i,end))
    ambiguous_office=(len(filters.get("family",[]))>1 and
                      all(e["text"]=="офис" for e in entities if e["type"]=="family") and
                      all(kb.rows["families"].get(fid,{}).get("category")=="office_suite" for fid in filters["family"]))
    if ambiguous_office and "офис" in words and len(words)>1:
        filters.pop("family")
        entities=[e for e in entities if e["type"]!="family"]
    if "office_suite" in kb.rows["categories"] and "офис" in words and len(words)>1 and "family" not in filters and not filters.get("vendor"):
        if not filters.get("category") or "office" in filters["category"]:
            filters["category"]=["office_suite"]
    if any(w.startswith("бессроч") for w in words):
        filters["model"]="perpetual"
    qty = numeric_conditions(words,filters,qty)
    for i,w in enumerate(words):
        if i and "family" in filters and re.fullmatch(r"\d+(?:\.\d+)*",w):
            versions = {str(x) for fid in filters["family"] for x in kb.rows["families"].get(fid,{}).get("versions",[])}
            if w in versions:
                filters["version"] = w
    return filters,exclude,entities,qty," ".join(w for i,w in enumerate(words) if i not in used)
