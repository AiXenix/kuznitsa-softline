"""Проверки полей KB, используемых поиском и генератором."""
from math import isfinite
from typing import get_args
from kuznitsa.schema import Action,Metric,Audience,Model,Delivery

LIST_FIELDS = ("aliases synonyms slang phrases typical_queries questions categories platforms compat_ru_os editions versions certs "
               "use_cases roles industries formats analogs replaces delivery deployment slots russian_analogs").split()


def validate(group,row):
    if group=="feed_analogs":
        for key in ("names","sections"):
            values=row.get(key)
            if not isinstance(values,list) or not values or not all(isinstance(v,str) and v.strip() for v in values):
                raise ValueError(key)
        if not isinstance(row.get("in_catalog"),bool) or not isinstance(row.get("kind"),str):
            raise ValueError("in_catalog / kind")
        targets=row.get("analogs")
        if not isinstance(targets,list):
            raise ValueError("analogs")
        for target in targets:
            if (not isinstance(target,dict) or target.keys()-{"title","vendor","russian"}
                    or not isinstance(target.get("title"),str) or not target["title"].strip()
                    or not isinstance(target.get("vendor",""),str) or not isinstance(target.get("russian",False),bool)):
                raise ValueError("analogs.title / vendor / russian")
        return
    for field in ("name","name_ru","title","vendor","category","parent","summary","description","origin","market_status"):
        if row.get(field) is not None and not isinstance(row[field],str):
            raise ValueError(field)
    for field in set(LIST_FIELDS)-{"editions","slots","russian_analogs"}:
        if not all(isinstance(v,(str,int,float)) for v in row.get(field,[])):
            raise ValueError(field)
    for field in ("editions","slots","russian_analogs"):
        if not all(isinstance(v,dict) for v in row.get(field,[])):
            raise ValueError(field)
    if group=="feed_tasks":
        sections=row.get("sections")
        if not isinstance(sections,list) or not sections or not all(isinstance(v,str) and v.strip() for v in sections):
            raise ValueError("sections")
        if any(not isinstance(text,str) or not text.strip()
               for key in ("aliases","phrases") for text in row.get(key,[])):
            raise ValueError("phrases / aliases")
        if not row.get("aliases") and not row.get("phrases"):
            raise ValueError("phrases / aliases")
    if group=="hardware_hints":
        for k in ("hardware_class","prompt"):
            if not isinstance(row.get(k),str) or not row[k]:raise ValueError(k)
        for k in ("hardware_feed_classes","trigger_words","software_classes"):
            if not isinstance(row.get(k),list) or not row[k] or not all(isinstance(v,(str,int)) for v in row[k]):
                raise ValueError(k)
    if group=="compliance":
        effect=row.get("effect",{})
        if not isinstance(effect,dict) or not isinstance(effect.get("filter",{}),dict):
            raise ValueError("effect")
    if group!="families":
        return
    if row.get("registry") not in (True,False,None,"partial") or not isinstance(row.get("catalog",True),bool):
        raise ValueError("registry / catalog")
    price=row.get("price_rub") or {}
    if not isinstance(price,dict):
        raise ValueError("price_rub")
    for value in [price.get("typical",0),row.get("popularity",3)]:
        if value is not None and (type(value) not in (int,float) or not isfinite(value) or value<0):
            raise ValueError("price_rub / popularity")
    allowed_values={"audiences":Audience,"actions":Action,"metrics":Metric,"models":Model}
    if any(v not in get_args(Delivery) for v in row.get("delivery",[])):
        raise ValueError("delivery")
    for key,vals in row["license"].items():
        if key in allowed_values and any(v not in get_args(allowed_values[key]) for v in vals):
            raise ValueError(key)
        if key in {"terms_months","packs"}:
            if any(v is not None and (not str(v).isdigit() or int(v)<1) for v in vals):
                raise ValueError(key)
            row["license"][key]=[int(v) for v in vals if v is not None]
        elif any(not isinstance(v,(str,int)) for v in vals):
            raise ValueError(key)
    for ed in row.get("editions",[]):
        if not isinstance(ed.get("id"),str) or not isinstance(ed.get("name",ed["id"]),str):
            raise ValueError("editions")


def missing_references(kb):
    refs={"families":{"vendor":"vendors","category":"categories","analogs":"families","replaces":"families","extra_categories":"categories"},
          "categories":{"parent":"categories"},"vendors":{"categories":"categories"},
          "roles":{},"industries":{"compliance":"compliance"},"use_cases":{"categories":"categories","families":"families"},
          "faq":{"related_categories":"categories","related_families":"families"},"analogs":{"family":"families"},"slang":{}}
    def check(value,target,context):
        for v in value if isinstance(value,list) else [value]:
            if v and str(v) not in kb.rows[target]:
                yield f"{context} → {v}"
    for group,fields in refs.items():
        for ident,r in kb.rows[group].items():
            for field,target in fields.items():
                yield from check(r.get(field),target,f"{ident}.{field}")
            for slot in r.get("slots",[]):
                for field,target in (("category","categories"),("families","families")):
                    yield from check(slot.get(field),target,f"{ident}.slots.{field}")
            for alt in r.get("russian_analogs",[]):
                yield from check(alt.get("family"),"families",f"{ident}.russian_analogs")
            if group=="slang":
                for key,target in (("category","categories"),("vendor","vendors"),("family","families")):
                    yield from check(r["maps_to"].get(key),target,f"{ident}.{key}")
