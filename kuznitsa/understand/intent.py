import re
from .normalize import resembles_sku

TITLES = dict(sku="Поиск по артикулу",product="Поиск продукта",vendor="Поиск по вендору",category="Подбор в категории",
              broad="Требуется уточнение",out_of_catalog="Продукта нет в продаже",off_topic="За пределами каталога",
              renewal="Продление лицензии",license_ops="Изменение лицензии",question="Вопрос о ПО",analog="Поиск аналога",
              spec_list="Список позиций",compare="Сравнение",account="Личный кабинет",service="Услуга",promo="Акции",
              role_kit="Рабочее место",industry="Отраслевой подбор",task="Поиск по задаче",compliance="Требования к ПО")


def scenario(raw,words,filters,entities,sku,context):
    text = " ".join(words)
    if sku or (not any(e["type"] in ("family","vendor","category") for e in entities) and any(resembles_sku(w) for w in words)):
        return "sku"
    if re.search(r"кряк|торрент|активатор|ноутбук|картридж|принтер",text) and not filters.get("family"):
        return "off_topic"
    if len([s for s in re.split("[;\n]",raw) if s.strip()])>1:
        return "spec_list"
    for k,pattern in [("compare",r"\b(vs|сравнить|или)\b"),("question",r"^(как|что такое|можно ли|почему)\b"),
                      ("analog",r"\b(аналог|замена|вместо)"),("account",r"мои лицензии|мой заказ|личный кабинет"),
                      ("promo",r"акция|промокод|скидка"),("service",r"внедрение|настройка|обучение")]:
        if re.search(pattern,text):
            return k
    if filters.get("action")=="renewal":
        return "renewal"
    if filters.get("action") in {"upgrade","addon","crossgrade"}:
        return "license_ops"
    for typ,intent in [("role","role_kit"),("industry","industry"),("use_case","task"),("compliance","compliance")]:
        if any(e["type"]==typ for e in entities):
            return intent
    return base_plan(filters,words,context)


def base_plan(f,words,context):
    if len(words)==1 and (words[0] in {"офис","астра","по","софт","программа","лицензия"} or len(f.get("family",[]))>1):
        return "category" if context else "broad"
    for key,plan in [("family","product"),("vendor","vendor"),("category","category")]:
        if f.get(key):
            return plan
    return "category" if context or f else "off_topic"
