import re
from .intent import base_plan
from .normalize import resembles_sku

PIRACY=r"кряк|торрент|активатор|варез|пиратск|ключ\w* бесплатно|бесплатно с ключ|скачать .* бесплатно.*ключ"
HARDWARE=r"ноутбук|картридж|принтер|купить (?:айфон|iphone)|купить (мышь|монитор|пк)"


def route(raw,words,f,entities,sku,category):
    text=" ".join(words)
    original=raw.casefold().replace("ё","е")
    def has(pattern):
        return re.search(pattern,original) is not None or re.search(pattern,text) is not None
    types={e["type"] for e in entities}
    if has(PIRACY) or has(HARDWARE) and not has(r"драйвер|защит|шифр|антивирус"):
        return "off_topic"
    lines=[s for s in re.split("[;\n]",raw) if s.strip()]
    if len(lines)>1 or ("," in raw and len(re.findall(r"\d+\s*(?:шт|пк|узл|мест|лиценз)",raw))>=2):
        return "spec_list"
    if has(r"(?:реестр|реестре) (?:по )?(?:№|номер|no)?\s*\d|(?:окпд2|ктру) \d+[.]"):
        return "compliance" if has("окпд2|ктру") else "sku"
    if has(r"наличие в .*сертификат.*поддержка") and raw.count(",")>=2:
        return "compliance"
    if has(r"(?:расчет|рассчитать|подбор) кп") and len(f.get("family",[]))>=2:
        return "spec_list"
    if sku or "артикул" in words or (not types.intersection({"family","vendor","category"}) and any(resembles_sku(w) for w in words)):
        return "sku"
    if has(r"лицензи[яю] .*для юрлица|домашн\w+ .*в офисе"):
        return "question" if has("можно ли|разрешен") else "license_ops"
    if has(r"гостайн|по гост \d"):
        return "compliance"
    if has(r"для нмцк") and has("аналог|сравн"):
        return "compare"
    if any(e["type"]=="role" and e["id"].startswith("kit_") for e in entities) and not has(r"^(как|почему|можно ли|сравн)"):
        return "role_kit"
    if has(r"комплект|набор|рабочее место|\bарм\b|оснастить|^(?:софт |по |программы? )?для ") and types.intersection({"role","industry"}) and (not types.intersection({"family","category"}) or has(r"комплект|набор|рабочее место|арм|оснастить")):
        return "role_kit" if "role" in types else "industry"
    if has(r"перевести офис|переоборудовать офис|новый офис на"):
        return "role_kit"
    if has(r"как |какие |можно ли |нужна ли ") and has(r"документ|фсб|лицензия .*чтобы купить"):
        return "question"
    if has(r"мои (?:лиценз|заказ|покуп)|у нас .*истека|личн\w+ кабинет|истори\w+ заказ|повторить .*заказ|что .*куплено|закрывающ\w+ документ"):
        return "account"
    if has("отлич|разниц") and (len(f.get("family",[]))>=2 or len(f.get("edition",[]))>=2):
        return "compare"
    if has(r"\b(vs|против|сравн\w*|или)\b|что лучше") and ("family" in types or "vendor" in types):
        return "compare"
    if has(r"\bаналог\w*|альтернатив\w*|дешевле [а-яa-z]|чем замен|\bзамен[ауы]|\bвместо|импортозамещ") and not has(r"как (?:перейти|заменить)"):
        return "analog"
    if f.get("category") and has(r"с интеграцией (?:в|с) "):
        return "category"
    if has(r"^(?:распозна|подписыва|подключа|зашифров|копирова)ть(?:ся)? |программа для |с интеграцией|(?:копирование|учет|моделирование|проверка|составление|документооборот) [а-яa-z]+ .+|как проверить |чем (?:чертить|начертить|открыть|защитить|вести|подписать|распознать)|чтобы |для чего подобрать"):
        return "task"
    if has(r"что такое|почему|можно ли|\bкак (?:активировать|перейти|купить|получить|оплатить)|работает ли|нужн\w* ли|чем отличается|входит ли|совместим\w* ли") or "faq" in types:
        return "question"
    if has(r"продл|пролонг|renewal|кончается лиценз") or f.get("action")=="renewal":
        return "renewal"
    if has(r"с техподдержкой|коммерческ\w+ верси") and len(words)>2:
        return "product"
    if f.get("action") in ("upgrade","crossgrade","addon") or has(r"докуп|апгрейд|миграци|кроссгрейд|расширить|перейти|еще на \d+"):
        return "license_ops"
    if has(r"акци[яюи]|скидк|пилот|промокод|триал|пробн\w+ верси"):
        return "promo"
    if has(r"техподдержк|внедрени|обучени|курсы |запрос\w* кп|расчет кп"):
        return "service"
    if has(r"по безналу|безналичн\w* расчет"):
        return "question"
    if (has("из реестра|фстэк|фсб") and (not category or has(r"^а |фстэк.*реестр|реестр.*фстэк|фстэк \d")) and not f.get("family") and not has(r"аналог")):
        return "compliance"
    if category and not f.get("family") and not f.get("vendor"):
        return "category"
    if text in ("российское по","отечественное по"):
        return "broad"
    if "role" in types and not types.intersection({"category","family","use_case"}) or has(r"(комплект|набор) (?:по|программ)|рабочее место для"):
        return "role_kit"
    if "industry" in types and not types.intersection({"family","vendor","category"}):
        return "industry"
    if "use_case" in types and not ("category" in types and len(words)<=3) and not ("family" in types and not has("чтобы|чем |задач")):
        return "task"
    if "compliance" in types or has(r"без ндс|фстэк|фсб|гостайн|ктру|окпд2|\bкии\b|из реестра"):
        return "compliance"
    if text in ("сертификат","ключ","защита сети","программы для бизнеса","программное обеспечение"):
        return "broad"
    if has(r"продукт\w* (?:компании|вендора)|все продукт|линейк\w* ") and f.get("vendor"):
        return "vendor"
    if f.get("vendor") and ("delivery" in f or f.get("model")=="perpetual"):
        return "product"
    return base_plan(f,words,category)
