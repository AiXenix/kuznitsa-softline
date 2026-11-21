"""Закрытые вопросы о неоднозначной потребности и проверяемые факты кандидатов."""
from .decisions import choice

DESCRIPTIONS={
    "product":"Конкретный продукт или редакция, например офисный пакет определённой марки",
    "vendor":"Ассортимент одного производителя, например все продукты АСКОН",
    "category":"Класс ПО, например защита рабочих станций",
    "question":"Вопрос о понятиях или закупке, например как оформляется лицензия",
    "task":"Потребность своими словами, например предотвратить утечку документов",
    "service":"Услуга установки, настройки или сопровождения ПО",
    "compliance":"Условия закупки и сертификации, например реестр или ФСТЭК",
    "broad":"Нужно уточнение, например одно слово «офис»",
    "off_topic":"Нет подтверждённой связи с ПО, например заказ доставки еды",
    "role_kit":"Комплект программ для рабочего места или открытия филиала",
    "industry":"Набор решений отрасли, например ПО для клиники",
    "analog":"Замена исходного продукта, например альтернатива зарубежной САПР",
}


def questions_for(engine,intent,text,entities,f,state,branches=()):
    categories=[*f.get("category",[]),*branches]
    task=next((e["id"] for e in entities if e["type"]=="use_case"),None)
    if task:
        categories+=engine.kb.rows["use_cases"].get(task,{}).get("categories",[])
    categories.extend(engine.knowledge.nearest("category",text))
    scores=engine.catalog.scores(text)
    top=sorted(scores,key=scores.get,reverse=True)[:3]
    categories.extend(engine.catalog.cards[c].category for c in top)
    state["найдено"]=[dict(название=engine.catalog.cards[c].title,сходство=round(scores[c],2)) for c in top]
    state["сущности"]=[dict(тип=e["type"],название=e["text"]) for e in entities[:6]]
    choices=[intent,"broad"]
    if intent in ("category","task","broad","product","compliance","industry","role_kit"):
        choices+=["task","category","product"]
    if intent=="question":
        choices+=["compliance","task"]
    choices.append("off_topic")
    questions={"intent":choice("Выберите цель покупателя, опираясь на найденные сущности.",{k:DESCRIPTIONS[k] for k in choices if k in DESCRIPTIONS})}
    cats={}
    for k in dict.fromkeys(categories):
        row=engine.kb.rows["categories"].get(k)
        if row:
            cats[k]=row["title"]+". "+row.get("description","")[:130]
    if cats and intent not in ("question",):
        questions["category"]=choice("Какой класс ПО решает задачу? Для общего запроса учитывайте отрасль и парк организации. Если данных мало, оставьте исходный класс.",{**dict(list(cats.items())[:6]),"none":"Среди вариантов нет подходящего класса"})
    if intent=="question":
        rows=engine.knowledge.nearest("faq",text)
        if rows:
            questions["faq"]=choice("Какой вопрос совпадает по предмету?",{**{k:engine.kb.rows["faq"][k]["questions"][0] for k in rows[:5]},"none":"Другая тема"})
    return questions


def card_facts(engine,cid,offer,f):
    card=engine.catalog.cards[cid]
    facts=dict(card_id=cid,title=card.title,категория=engine.names["category"].get(card.category),
               назначение=card.kb.get("summary","")[:180],платформы=offer.platforms,лицензия=offer.lic.model_dump(exclude_none=True))
    if f.get("certs") or f.get("registry"):
        facts.update(сертификаты=offer.certs,реестр=offer.registry)
    return facts


def category_options(engine,entities,filters,profile,text):
    """Допустимое уточнение общего раздела с учётом парка и отрасли."""
    from kuznitsa.plans.base import descendants
    result=[]
    for e in entities:
        if e["type"]!="category":
            continue
        children=descendants(engine.kb,[e["id"]])-{e["id"]}
        if not children:
            continue
        owned={p.get("family_id") for p in profile.owned}
        def affinity(cid):
            group=engine.catalog.by["category"].get(cid,())
            families={engine.catalog.cards[c].family for c in group}
            industry=sum(profile.industry in engine.kb.rows["families"].get(fid,{}).get("industries",[]) for fid in families)
            return (bool(group),len(owned&families),industry,len(families),cid)
        result.extend(sorted(children,key=affinity,reverse=True)[:5])
    contextual=filters.get("deployment") or any(e["type"] in ("role","platform","industry") for e in entities)
    if contextual and not filters.get("family"):
        nearby=engine.catalog.dense.nearest_categories(text)
        lexical=engine.knowledge.nearest("category",text)
        result.extend([*nearby,*lexical])
    return list(dict.fromkeys(result))
