import re
from kuznitsa.text import tokens,lemma
from .quantities import number_before


def refine(engine,words,f,exc,entities,qty):
    text=" ".join(words)
    kinds={e["type"] for e in entities}
    families=engine.kb.rows["families"]
    # Упомянутая ОС может задавать совместимость другого продукта.
    for e in list(entities):
        if e["type"] not in ("family","vendor"):
            continue
        start,end=e["span"]
        if start and (f.get("category") or len(f.get("family",[]))>1):
            target=" ".join(words[start:end])
            os_id=next((os for pat,os in [(r"астр|astra","astra"),(r"^альт|^alt","alt"),(r"ред ос|редос","redos"),(r"аврор","aurora")]
                        if re.search(pat,target)),None)
            if os_id and ("для" in words[max(0,start-4):start] or "под" in words[max(0,start-4):start] or "на" in words[max(0,start-2):start] or "поддержк" in text):
                f[e["type"]]=[x for x in f.get(e["type"],[]) if x!=e["id"]]
                if not f[e["type"]]:
                    del f[e["type"]]
                f["platform"]=[os_id]
                entities.remove(e)
    if "category" in f:
        cats=engine.kb.rows["categories"]
        for i,c in enumerate(f["category"]):
            children=[k for k,v in cats.items() if v.get("parent")==c and engine.catalog.by["category"].get(k)]
            if children and any(x.get("id")==c and x["text"]!=cats[c].get("title","").lower() for x in entities):
                f["category"][i]=children[0]
        f["category"]=list(dict.fromkeys(f["category"]))
    # Общая метка редакции имеет смысл только для названного семейства.
    if not f.get("family") and not f.get("vendor"):
        f.pop("edition",None)
    if not qty:
        for i,w in enumerate(words):
            n=number_before(words,i)
            if n and (w.startswith(("сотрудник","юзер","пользовател","участник","человек","рабочи")) or w in ("пк","мест","узлов","компов","ядра","ядер")):
                metric="user" if w.startswith(("сотрудник","юзер","пользовател","участник","человек")) else "core" if w in ("ядра","ядер") else "device"
                qty=dict(value=n,metric=metric)
                f["metric"]=metric
                break
    # Поиск по вендору с названием его линейки. Совпадение имени семейства
    # весомее пересечения с названием чужой редакции.
    if f.get("vendor") and not f.get("family"):
        candidates=set()
        noise={"по","для","на","и","место","лицензия","год","рабочий","пользователь","бизнес"}
        qwords=set(map(lemma,words))-noise
        brand=engine.vendor_terms.get(f["vendor"][0],set())
        meaningful=qwords-brand
        for fid in engine.vendor_families.get(f["vendor"][0],()):
            sw=engine.family_terms[fid]
            if len(qwords & sw)>=2 and meaningful & sw:
                candidates.add(fid)
        if candidates:
            best=max(candidates,key=lambda k:(len(qwords & engine.family_terms[k]),-len(engine.family_terms[k]),k))
            if len(qwords & engine.family_terms[best])>=2 and not ("role" in kinds or "use_case" in kinds):
                f["family"]=[best]
    # Выбор линейки вендора по предметным словам, включая ориентиры лицензирования.
    if f.get("vendor") and not f.get("family"):
        vids=f["vendor"]
        mentioned={w for e in entities if e["type"]=="vendor" for w in e["text"].split()}
        rest=set(map(lemma,words))-set(map(lemma,mentioned))-{"для","по","лицензия","бизнес","с","от","на"}
        rows=[(fid,engine.family_terms[fid]&rest) for v in vids for fid in engine.vendor_families.get(v,())]
        hits=[(len(overlap),families[fid].get("popularity",0),-len(engine.family_terms[fid]),fid) for fid,overlap in rows if overlap]
        if hits:
            f["family"]=[max(hits)[-1]]
        elif qty and re.search("лицензи",text):
            choices=[fid for fid,_ in rows if "клиентск" in families[fid]["name"].lower()]
            if choices:
                f["family"]=[choices[0]]
    if re.search(r"переход с |миграци\w* с ",text) and "на" in words:
        pivot=words.index("на")
        for key in ("vendor","family"):
            dest=[e["id"] for e in entities if e["type"]==key and e["span"][0]>pivot]
            if dest:
                f[key]=dest
            else:
                f.pop(key,None)
        f["action"]="crossgrade"
    if re.search("докуп|еще на",text):
        f["action"]="addon"
    if exc.get("family"):
        exc["vendor"]=list(dict.fromkeys([*exc.get("vendor",[]),*(families[k]["vendor"] for k in exc["family"] if k in families)])) if "кроме" in words and not f.get("family") else exc.get("vendor",[])
        if not exc["vendor"]:
            exc.pop("vendor")
    if re.search(r"из реестра|отечественн|российск\w* (?:аналог|ос\b|офис)|без ндс",text):
        f["registry"]=True
    if "без ндс" in text:
        exc.pop("registry",None)
    return qty


def apply_profile(profile,f,intent):
    if intent in ("category","role_kit","industry","task") and profile.preferences.get("registry_required"):
        f.setdefault("registry",True)
    if intent in ("category","role_kit","industry") and profile.segment=="gov" and profile.preferences.get("certs_required") and f.get("category") and any(
            c in ("endpoint_security","desktop_os_ru") for c in f["category"]):
        certs=[v for v in profile.preferences["certs_required"] if v in ("fstec","fsb","mo")]
        if certs:
            f.setdefault("certs",certs)
    if profile.segment=="individual" and f.get("category")==["endpoint_security"]:
        f["category"]=["home_antivirus"]
