"""Classify source paths and unknown product lines once per import, before publication."""
import json
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from kuznitsa.text import lemma,tokens
from .ai_backend import Gateway,Vectors,cached_keys,forecast
from .enrich import stable

KINDS=("category","use_cases","roles","industries","analogs")
GENERIC={"программное обеспечение","по","программы","прочее","новинки","другое","каталог","софт","без категории","другие программы","программы для организаций","software","other"}
STOP=set("и на по для в с из к от или программа программный обеспечение".split())


def words(text):
    return set(map(lemma,tokens(text)))-STOP


def describe(row):
    return ". ".join(str(x) for x in [row.get("title") or row.get("name"),
        *row.get("phrases",[])[:4],*row.get("synonyms",[])[:8],*row.get("aliases",[])[:5],
        row.get("description") or row.get("summary")] if x)[:850]


def classify(kb,auto,observations,stage,cfg,mode,budget,dry,transport=None):
    audit=[]
    stats=dict(mode=mode,questions=0,sent=0,cached=0,usd=0.,accepted=0,rejected=0,
               by_kind=dict.fromkeys(KINDS,0),fallback={},forecast_sent=0,forecast_usd=0.,examples=[])
    log=stage/"import_ai.jsonl"
    log.touch()
    if mode=="off" or not observations:
        return stats
    families=auto["families"]
    for (fid,_),obs in observations.items():
        if fid in families and obs["description"]:
            families[fid]["summary"]=obs["description"]
    cats=kb["categories"]
    parents={r.get("parent") for r in cats.values()}
    groups=dict(category={k:v for k,v in cats.items() if k not in parents},
                parent={k:v for k,v in cats.items() if k in parents},analogs={**kb["families"],**families})
    groups.update({k:kb[k] for k in ("use_cases","roles","industries")})
    docs=[]; indices={}
    for kind,rows in groups.items():
        indices[kind]={}
        for key,row in rows.items():
            indices[kind][key]=len(docs)
            docs.append(describe(row))
    lex=[words(t) for t in docs]
    label_patterns={}
    for kind,rows in groups.items():
        for key,row in rows.items():
            labels=[row.get("title",""),*row.get("synonyms",[]),*row.get("phrases",[]),*row.get("aliases",[])]
            labels=[re.escape(t) for t in labels if isinstance(t,str) and len(t)>3]
            if labels:
                label_patterns[kind,key]=re.compile(r"(?<!\w)(?:"+"|".join(labels)+r")(?!\w)",re.I)
    pathstates={}; states={}; keys={}
    for (fid,path),obs in observations.items():
        if fid in families:
            f=families[fid]
            state=states.setdefault(fid,dict(семейство=f["name"],производитель=obs["vendor"],товары=[],описание=f["summary"]))
            state["товары"]=list(dict.fromkeys(state["товары"]+obs["names"]))[:3]
        key=("path",path) if path and path[-1].casefold() not in GENERIC else ("family",fid)
        explicit=obs["explicit_category"]
        if not explicit and key[0]=="family" and fid not in families:
            explicit=kb["families"][fid].get("category")
        if explicit in groups["category"]:
            keys[fid,path]=("explicit",explicit)
            continue
        if key[0]=="family" and fid not in families:
            key=("path",path)
        keys[fid,path]=key
        if key[0]=="path":
            state=pathstates.setdefault(key,dict(путь=" / ".join(path),товары=[],производители=[],назначение=[]))
            for field,items in [("товары",obs["names"]),("производители",[obs["vendor"]]),("назначение",[obs["description"]])]:
                state[field]=list(dict.fromkeys(state[field]+[s for s in items if s]))[:10]
        else:
            pathstates[key]=states[fid]
    def query(state):
        return ". ".join(" ".join(v) if isinstance(v,list) else v or "" for v in state.values())[:1800]
    queries=list(dict.fromkeys(query(s) for s in [*pathstates.values(),*states.values()]))
    vectors=Vectors(cfg,docs,queries,{indices["analogs"][fid] for fid in families}) if queries else None
    def shortlist(kind,state,allowed=None):
        q=query(state); bag=words(q)
        scored=[]
        candidates=list(indices[kind] if allowed is None else allowed)
        sims=vectors.scores(q,[indices[kind][k] for k in candidates])
        for key,similarity in zip(candidates,sims):
            idx=indices[kind][key]
            pattern=label_patterns.get((kind,key))
            exact=bool(pattern and pattern.search(q))
            overlap=len(bag & lex[idx])/max(1,min(len(bag),len(lex[idx]),8))
            score=min(.99,max(0,float(similarity))*.78+min(1,overlap)*.22+.14*exact)
            scored.append((round(score,5),key))
        return sorted(scored,reverse=True)[:8]
    tasks=[(key,"category",state) for key,state in pathstates.items()]
    tasks.extend((fid,kind,state) for fid,state in states.items() for kind in ("use_cases","roles","industries"))
    cache=cached_keys(cfg.data/"import_ai.sqlite") if mode=="jev" else set()
    gateway=Gateway(cfg.data/"import_ai.sqlite",budget,transport) if mode=="jev" and not dry else None
    def answer(task):
        obj,kind,state=task
        ranking=shortlist(kind,state)
        options={k:docs[indices[kind][k]][:340] for _,k in ranking}
        options["none"]="Нет подходящего варианта"
        p,selected=ranking[0] if ranking else (0.,"none")
        source="embed"
        meta={};reason=None
        if gateway:
            ans,meta,reason=gateway.request(str(obj),state,kind,options)
            if ans:
                source="jev";selected=ans["choice"];p=ans["probabilities"][selected]
        threshold=.55 if source=="jev" else (.55 if kind=="category" else .68)
        return dict(object=obj,question=kind,state=state,options=options,choice=selected,probability=p,
                    accepted=selected!="none" and p>=threshold,source=source,confidence="low" if source=="embed" else "model",
                    usd=meta.get("usd",0.),cached=meta.get("cached",0),sent=bool(meta.get("sent")),fallback=reason)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            decisions=list(pool.map(answer,tasks))
    finally:
        if gateway:
            gateway.close()
    stats["questions"]=len(tasks)
    category={}
    for d in decisions:
        obj,kind=d["object"],d["question"]
        audit.append(d)
        if mode=="jev":
            cost,hit=forecast(d["state"],kind,d["options"],cache)
            stats["forecast_usd"]+=cost
            stats["forecast_sent"]+=int(not hit)
        if d["fallback"]:
            stats["fallback"][d["fallback"]]=stats["fallback"].get(d["fallback"],0)+1
        if kind=="category":
            category[obj]=d["choice"] if d["accepted"] else None
        elif d["accepted"]:
            families[obj][kind]=[d["choice"]]
            families[obj].setdefault("classification_confidence",{})[kind]=dict(source=d["source"],level=d["confidence"],score=d["probability"])
    for (fid,path),key in keys.items():
        obs=observations[fid,path]
        if key[0]=="explicit":
            cid=key[1]
            audit.append(dict(object=fid,question="category",options=[cid],choice=cid,probability=1.,accepted=True,source="rule",usd=0))
        else:
            cid=category[key]
        if not cid:
            cid=obs["category"]
            if not cid or cid not in auto["categories"]:
                cid=stable("auto_c_","/".join(path) or fid)
                auto["categories"].setdefault(cid,dict(id=cid,title=path[-1] if path else "Без категории",parent=None,synonyms=[]))
            root=shortlist("parent",pathstates[key])
            if root and root[0][0]>=.60:
                auto["categories"][cid]["parent"]=root[0][1]
                audit.append(dict(object=cid,question="parent",options=[k for _,k in root],choice=root[0][1],
                                  probability=root[0][0],accepted=True,source="embed",usd=0))
        obs["resolved"]=cid
    by_family=defaultdict(list)
    for (fid,_),obs in observations.items():
        by_family[fid].append(obs)
    for fid,f in families.items():
        rows=by_family[fid]
        counts=Counter()
        for o in rows:
            counts[o["resolved"]]+=o["count"]
        f["category"]=counts.most_common(1)[0][0]
        registry=set().union(*(o["registry"] for o in rows))
        certs=sorted(set.intersection(*(o["certs"] for o in rows)))
        for field,value,options in [("registry",next(iter(registry)) if len(registry)==1 else None,[False,True]),
                                    ("certs",certs or None,certs)]:
            if value is not None:
                f[field]=value
                audit.append(dict(object=fid,question=field,options=options,choice=value,probability=1.,accepted=True,source="rule",usd=0))
        from .product_rules import PATTERNS
        rules=set().union(*(o["rules"] for o in rows))
        for field,patterns in PATTERNS.items():
            values=sorted(value for kind,value in rules if kind==field)
            if values:
                f[field]=values
                audit.append(dict(object=fid,question=field,options=list(patterns),choice=values,probability=1.,accepted=True,source="rule",usd=0))
    analog_pool=defaultdict(list)
    for key,row in groups["analogs"].items():
        analog_pool[row.get("category")].append(key)
    for fid,f in families.items():
        left=kb["vendors"].get(f["vendor"],{}).get("market_status")=="left"
        pool=[k for k in analog_pool[f["category"]] if k!=fid and
              (not left or kb["vendors"].get(groups["analogs"][k].get("vendor"),{}).get("origin")=="russian")]
        known=shortlist("analogs",states[fid],[k for k in pool if k in kb["families"]])
        imported=shortlist("analogs",states[fid],[k for k in pool if k not in kb["families"]])
        ranked=known+imported
        f["analogs"]=[k for _,k in ranked[:5]]
        f["analog_suggestions"]=[dict(family=k,confidence=p) for p,k in ranked[:5]]
        audit.append(dict(object=fid,question="analogs",options=[k for _,k in ranked],choice=f["analogs"],
                          probabilities={k:p for p,k in ranked[:5]},probability=ranked[0][0] if ranked else 0,
                          accepted=bool(ranked),source="embed",usd=0))
    with log.open("w") as stream:
        for d in audit:
            stream.write(json.dumps(d,ensure_ascii=False)+"\n")
            stats["accepted" if d["accepted"] else "rejected"]+=1
            if d["question"] in KINDS:
                stats["by_kind"][d["question"]]+=1
            for k in ("sent","cached","usd"):
                stats[k]+=d.get(k,0)
    stats["examples"]=[d for flag in (False,True) for d in [v for v in audit if v["accepted"]==flag][:5]]
    return stats
