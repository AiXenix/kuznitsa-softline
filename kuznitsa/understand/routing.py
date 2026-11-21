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
    from kuznitsa.plans.license_help import operation
    if operation(raw):return "question"
    if has(r"как (?:перенести|активировать|зарегистрировать|восстановить|переоформить).*(?:ключ|лиценз)|как .*ключ.*активир"):
        return "question"
    if has(r"(?:мои|наши|моих|наших|у меня|у нас).*(?:срок|лиценз|куплен)|(?:срок|остаток|список).*наших лиценз|что (?:мы|я) (?:купили|купил)"):
        return "account"
    if len({e["id"] for e in entities if e["type"]=="family"})>=2 and has(r"\b(?:связка|плюс)\b|\s\+\s"):
        return "spec_list"
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
    if has(r"\b(?:гос)?закуп(?:к|очн)|\bтендер") and has(r"\b\d+[ -]?фз\b"):
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
    if has(r"\b(vs|против|сравн\w*)\b|что лучше" if len(f.get("family",[]))<2 else r"\b(vs|против|сравн\w*|или)\b|что лучше") and ("family" in types or "vendor" in types):
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


def procurement_subject(text,words,entities,filters,intent):
    """Предмет покупки может иметь адресата, цену и формат поставки."""
    if filters.get("price_max") or filters.get("price_min"):
        return True
    if intent=="compliance" and not re.search(r"комплект|набор",text):
        return True
    supplied=[e for e in entities if e["type"] in ("vendor","category","family")]
    named_first=any(e["span"][0]==0 for e in supplied)
    beneficiary=re.search(r"\bдля (?:\w+ )?(?:сотрудник|пользоват|сисадмин|удаленщик)|рабочи[ех] мест",text)
    if named_first and (beneficiary or "набор" in words):
        return True
    if supplied and re.search(r"^(?:недорог|бюджетн|дешев|доступн|купить набор лиценз)",text):
        return True
    return bool(intent in ("service","task") and re.search(r"^(?:внедрени|обучени|настро|чем |как )",text))


def software_name(query):
    """Признаки названия ПО или явного запроса покупки лицензии."""
    if re.search(r"\b(?:программ[уа]|software|редактор|платформу|enterprise|studio|suite|professional|pro)\b|[a-z][A-Z]|^[A-Z][a-z]{3,}\b",query):
        return True
    text=query.lower()
    if re.search(r"\b[a-z][a-z0-9.-]{3,}\b",text) and re.search(r"лиценз|подписк|софт|купить",text):
        return True
    return bool(re.search(r"\b[a-z]{3,}(?:desk|flow|cad|sync|cloud|docs|soft|suite)\b",text))


def software_like_unknown(raw,words,entities):
    """Общее слово редакции без бренда не идентифицирует латинское название."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z -]+",raw.strip()):return False
    if any(e["type"]=="vendor" for e in entities) and not any(e["type"]=="family" for e in entities):
        covered={w for e in entities for w in e["text"].split()}
        tail=set(words)-covered-{"license","subscription","products","buy","business","lab"}
        if tail and any(len(w)>=5 for w in tail):return True
    generic={"studio","suite","manager","enterprise","professional","standard","software"}
    return (len(words)>=2 and bool(generic.intersection(words)) and
            not any(e["type"] in ("family","vendor","category") and
                    set(e["text"].split())-generic for e in entities))


def explicit_request(engine, text, filters, intent):
    """Явная операция и предмет покупки имеют приоритет перед адресатом программы."""
    from kuznitsa.plans.license_help import operation
    if operation(text):return "question"
    if re.search(r"(?:еще|следующ)\w* .*год.*действующ\w* подписк",text):
        filters["action"]="renewal"
        return "renewal"
    families=engine.kb.rows["families"]
    named=[families[fid] for fid in filters.get("family",[]) if fid in families]
    if re.search(r"купленн\w* лиценз\w* .*?(?:моей|нашей)|(?:моей|нашей) компани\w* .*лиценз",text):
        return "account"
    if re.search(r"^(?:нужен ли сертификат|нужна ли сертификац|можно ли)\b",text):
        return "question"
    if re.search(r"^(?:нужн\w* )?(?:курсы|обучение|внедрение)\s",text) and (named or filters.get("vendor")):
        if named and not filters.get("vendor"):
            filters["vendor"]=list(dict.fromkeys(r["vendor"] for r in named if r.get("vendor")))
        return "service"
    if re.search(r"нужн\w* лицензи\w+ ",text) and named and re.search(r"упал|сбой|отказал|сломал",text):
        return "product"
    quote=re.search(r"\bкп\b.*\bаналог",text)
    if quote or intent=="renewal":
        from kuznitsa.text import lemma,tokens
        words=tuple(map(lemma,tokens(text)))
        aliases=[(end-start,fid) for start in range(len(words))
                 for end in range(start+1,min(len(words),start+engine.lex.max_length)+1)
                 for kind,fid,_ in engine.lex.entries.get(words[start:end],()) if kind=="family" and fid in families
                 and (quote or engine.kb.rows["vendors"].get(families[fid].get("vendor"),{}).get("market_status")=="left")]
        if aliases:
            fid=max(aliases)[1]
            if quote or not families[fid].get("catalog",True):
                filters["family"]=[fid]
                filters.pop("action",None)
                return "analog"
    if quote:return "analog"
    if re.search(r"переход с .+? на .+? на \d+|(?:клиентские|сетевые|плавающие) лицензии",text) or not named and re.search(r"(?:клиентск|сетев|плавающ)\w* лицензи",text):
        return "license_ops"
    if intent=="renewal":
        brands=set(filters.get("vendor",[]))|{r.get("vendor") for r in named}
        if any(engine.kb.rows["vendors"].get(v,{}).get("market_status")=="left" for v in brands):
            filters.pop("action",None)
            return "analog"
    if re.search(r"(?:в чем|чем|как) откры(?:ва)?ть .*файл",text):
        words=set(re.findall(r"[\w]+",text))
        formats={cid for cid,card in engine.catalog.cards.items()
                 if words.intersection(str(fmt).casefold().strip(".*") for fmt in card.kb.get("formats",[]))}
        if formats:
            return "analog"
