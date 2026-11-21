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
    if f.get("category") and not f.get("platform"):
        # Склонённое название ОС может иметь несколько словарных основ.
        from kuznitsa.text import morphology
        for i,word in enumerate(words[1:],1):
            if words[i-1] not in ("на","под","для") or not word.isalpha():
                continue
            for parse in morphology().parse(word):
                matches=engine.lex.entries.get((parse.normal_form,),())
                platforms=[v for k,v,_ in matches if k=="platform"]
                if platforms:
                    f["platform"]=platforms
                    entities.append(dict(type="platform",id=platforms[0],span=[i,i+1],source="kb",text=word,conf=.85))
                    break
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
    if re.search(r"(?:переход|перейти|миграци\w*) с ",text) and "на" in words:
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
    if intent in ("category","role_kit","industry","task","compliance") and profile.preferences.get("registry_required"):
        f.setdefault("registry",True)
    if intent in ("category","role_kit","industry","task","compliance") and profile.preferences.get("certs_required") and (
            any(c in ("endpoint_security","desktop_os_ru","dlp","remote_desktop","nsd_access_control","ngfw_vpn") for c in f.get("category",[]))):
        certs=[v for v in profile.preferences["certs_required"] if v in ("fstec","fsb","mo")]
        if certs:
            f.setdefault("certs",certs)
    if profile.segment=="gov" and not {"ngfw_vpn","network_security"}.intersection(f.get("category",[])) and intent in ("category","task","compliance") and any(os in profile.fleet.get("os",[]) for os in ("astra","alt","redos")):
        f.setdefault("platform",[next(os for os in profile.fleet["os"] if os in ("astra","alt","redos"))])
    if profile.segment=="individual" and f.get("category")==["endpoint_security"]:
        f["category"]=["home_antivirus"]


def resolve_details(engine,lex,words,f,entities,qty):
    """Найти вложенные роли и редакции, скрытые длинным названием семейства."""
    text=" ".join(words)
    keys=list(map(lemma,words))
    if re.search(r"\b(?:комплект|набор|арм|оснастить|для|рабочее место)\b",text):
        for i in range(len(keys)):
            for end in range(min(i+4,len(keys)),i,-1):
                for kind,ident,src in lex.entries.get(tuple(keys[i:end]),()):
                    if kind in ("industry","role") and not any(e["type"]==kind and e["id"]==ident for e in entities):
                        entities.append(dict(type=kind,id=ident,text=" ".join(words[i:end]),span=[i,end],source=src,conf=.95))
    if f.get("action") in ("addon","renewal","upgrade"):
        for e in list(entities):
            if e["type"]!="family":
                continue
            matches=lex.entries.get(tuple(keys[slice(*e["span"])]),[])
            vendors=[v for k,v,_ in matches if k=="vendor"]
            if vendors and len(engine.vendor_families.get(vendors[0],()))>1:
                f["vendor"]=vendors
                f.pop("family",None)
    families=engine.kb.rows["families"]
    if f.get("family") and f.get("category"):
        anchor=next((e for e in entities if e["type"]=="family" and e["span"][0]>0 and
                    words[e["span"][0]-1] in ("для","к","под")),None)
        if anchor:
            f.pop("family",None)
    if not f.get("family") and f.get("vendor") and (qty or f.get("category")):
        ids=[fid for v in f["vendor"] for fid in engine.vendor_families.get(v,())]
        if f.get("category"):
            ids=[fid for fid in ids if families[fid].get("category") in f["category"]]
        if ids and not f.get("action"):
            f["family"]=[max(ids,key=lambda fid:(families[fid].get("popularity",0),len(engine.family_terms[fid]&set(keys)),-len(engine.family_terms[fid])))]
    for e in entities:
        if e["type"]!="vendor" or f.get("action") or text==engine.kb.rows["vendors"].get(e["id"],{}).get("name","").lower() and not qty:
            continue
        start,end=e["span"]
        tails=[" ".join(words[i:j]) for i in {start+1,end} for j in range(i+1,min(i+5,len(words))+1)]
        matches=[engine.brand_products.get(e["id"],{}).get(tail) for tail in tails]
        best=max((hit for hit in matches if hit),default=None)
        if best:
            f["family"]=[best[-1]]
    if f.get("family"):
        editions=[]
        # Общие номера версий/количества не являются именами редакций.
        for fid in f["family"]:
            for ed in families.get(fid,{}).get("editions",[]):
                for alias in [ed["id"],ed.get("title",""),ed.get("name",""),*ed.get("aliases",[])]:
                    parts=list(map(lemma,tokens(alias)))
                    if parts and not all(s.isdigit() for s in parts) and any(keys[i:i+len(parts)]==parts for i in range(len(keys))):
                        editions.append(ed["id"])
                        break
        f.pop("edition",None)
        if editions:
            f["edition"]=list(dict.fromkeys(editions))
    elif not any(e["type"]=="edition" and not e["text"].isdigit() for e in entities):
        f.pop("edition",None)
    if not f.get("family") and f.get("category") and "linux" in f.get("platform",[]) and text=="linux":
        # Покупателю нужны дистрибутивы ОС, включая российские.
        f["category"]=list(dict.fromkeys(f["category"]+[row["category"] for row in families.values()
                       if row.get("category") and "linux" in row.get("platforms",[]) and row.get("category","").endswith("_os_ru")]))

    # Если запрос целиком состоит из класса и марки, оставляем оба фильтра.
    if len(entities)!=2 or not f.get("category"):
        return
    cat=next((e for e in entities if e["type"]=="category"),None)
    if not cat:
        return
    brand=next(e for e in entities if e is not cat)
    spans=sorted([cat["span"],brand["span"]])
    if spans[0][0]!=0 or spans[0][1]!=spans[1][0] or spans[1][1]!=len(words):
        return
    vendors=[v for kind,v,_ in lex.entries.get(tuple(map(lemma,words[slice(*brand["span"])])),()) if kind=="vendor"]
    if vendors:
        f["vendor"]=list(dict.fromkeys(vendors))
        f.pop("family",None)
        f.pop("edition",None)
        brand.update(type="vendor",id=vendors[0])


def nested_family(lex,words,entities):
    if any(e["type"] in ("family","vendor","category") for e in entities):
        return
    # Название модуля может начинаться с последнего слова чужой редакции.
    keys=list(map(lemma,words))
    for i in range(len(keys)):
        for end in range(min(i+lex.max_length,len(keys)),i+1,-1):
            for kind,ident,src in lex.entries.get(tuple(keys[i:end]),()):
                if kind=="family":
                    return dict(type=kind,id=ident,text=" ".join(words[i:end]),span=[i,end],source=src,conf=.92)


def resolve_brand_quantity(engine,profile,words,residual,entities,filters):
    """Для марки с тиражом выбираем установленную линейку, если товар ещё не указан."""
    vendors=filters.get("vendor",[])
    if not vendors or filters.get("action") or any(e["type"] in ("family","category","edition") for e in entities):
        return
    families=engine.kb.rows["families"]
    if any(lemma(w)=="лицензия" for w in words) and any(
            "клиентск" in families[fid]["name"].lower() for fid in filters.get("family",[]) if fid in families):
        return
    quantity_words={"на","для","лицензия","шт","штука","место","по","рабочий","пк","компьютер","устройство","пользователь","узел","человек"}
    if any(not w.isdigit() and lemma(w) not in quantity_words for w in residual.split()):
        return
    owned=[item["family_id"] for item in profile.owned if families.get(item.get("family_id"),{}).get("vendor") in vendors]
    if owned:
        filters["family"]=list(dict.fromkeys(owned))
    elif profile.segment!="individual" and all(families.get(v,{}).get("category")=="home_antivirus" for v in filters.get("family",[])):
        filters.pop("family",None)
