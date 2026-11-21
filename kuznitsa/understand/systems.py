import re

# Названия систем встречаются в родительном падеже и после названия класса ПО.
SYSTEMS={
    "1С":r"1[сc](?:\b|[- ])","PostgreSQL":r"постгрес\w*|postgres\w*|\bpgsql\b",
    "Exchange":r"exchange|эксчейндж\w*","Active Directory":r"active directory"}
def system_record(engine,text,categories):
    for label,row in engine.kb.systems.items():
        groups=[g for g in row["compatible"].values() if set(g.get("categories",[])).intersection(categories)]
        if groups and any(re.search(r"(?<!\w)"+re.escape(alias.casefold())+r"(?!\w)",text)
                          for alias in row.get("aliases",[]) if isinstance(alias,str)):
            return label


def linked_families(engine,system,categories):
    row=engine.kb.systems.get(system,{})
    return {family["id"] for group in row.get("compatible",{}).values()
            if set(group.get("categories",[])).intersection(categories)
            for family in group.get("families",[]) if isinstance(family,dict) and "id" in family}


def target_system(engine,text,f,entities,exclude=None):
    if re.search(r"миграци\w*|перенос|переход",text) and re.search(r"российск|отечествен",text) and re.search(SYSTEMS["Active Directory"],text):
        f["registry"]=True
        f["category"]=["directory_services"]
        system="Active Directory"
    else:
        cats=f.get("category",[])
        if not cats:return
        system=system_record(engine,text,cats) or next((s for s,pat in SYSTEMS.items() if re.search(pat,text)),None)
        if system and system in engine.kb.systems:
            lookup=engine.kb.systems[system]["compatible"]
            group="monitoring" if re.search("монитор|метрик",text) else "security" if re.search("защит|аудит|утеч|антивирус|антиспам|двухфактор",text) else None
            related=lookup.get(group,{}).get("categories",[])
            if related:
                specific=[cid for cid in cats if cid in related and cid not in ("endpoint_security","monitoring_apm")]
                f["category"]=cats=specific or [related[0]]
        if not system:
            if not re.search(r"резервн|б[эе]кап|мониторинг|антивирус|защит|аудит|двухфактор",text):return
            target=next((e for e in entities if e["type"] in ("family","vendor") and e["span"][0]>0),None)
            if not target or target["id"] in (exclude or {}).get(target["type"],[]):return
            # Производитель средств этого класса остаётся предметом покупки.
            if target["type"]=="family":
                row=engine.kb.rows["families"].get(target["id"],{})
                vendor=row.get("vendor")
                brand=engine.kb.rows["vendors"].get(vendor,{})
                marks=[vendor,brand.get("name"),*brand.get("aliases",[])]
                if any(isinstance(mark,str) and mark.casefold()==target["text"].casefold() for mark in marks):
                    if vendor in (exclude or {}).get("vendor",[]):return
                    if any(engine.catalog.cards[cid].category in cats for cid in engine.catalog.by["vendor"].get(vendor,())):
                        f.pop("family",None)
                        f["vendor"]=[vendor]
                        return
            own=engine.catalog.by[target["type"]].get(target["id"],())
            if any(engine.catalog.cards[cid].category in cats for cid in own):
                f[target["type"]]=[target["id"]]
                if target["type"]=="vendor":
                    f.pop("family",None)
                return
            system=engine.names[target["type"]].get(target["id"],target["text"])
        ids={cid for cat in cats for cid in engine.catalog.by["category"].get(cat,())}
        products=set(f.get("family",[])) | set(f.get("vendor",[]))
        products.update(engine.kb.systems.get(system,{}).get("system_vendors",[]))
        explicit_monitor=system=="PostgreSQL" and re.search(r"метрик\w*|мониторинг",text)
        if not explicit_monitor and products and any({engine.catalog.cards[c].vendor,engine.catalog.cards[c].family}.intersection(products) for c in ids):return
    for key in ("family","vendor","action","edition","version"):f.pop(key,None)
    entities[:]=[e for e in entities if e["type"] not in ("family","vendor","action","edition")]
    return system
