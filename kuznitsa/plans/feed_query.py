"""Условия запроса, которые можно проверить по строкам фида."""
import re
from kuznitsa.index.feed import STOP, words
from kuznitsa.index.feed_solutions import SolutionHit
from kuznitsa.text import normalize
from kuznitsa.index.feed_language import edition_form
from kuznitsa.rank.variants import select

QUANTITY=re.compile(r"\b(?:на\s+)?(\d{1,7})\s*(?:рабоч\w*\s+)?(пользовател\w*|сотрудник\w*|человек\w*|узел|узл(?:ы|а|ов|ах)|устройств\w*|комп(?:ьютер\w*|ов|а)?|сервак\w*|процессор\w*|мест\w*|лицензи\w*|пк|devices?|users?|seats?|licen[cs]es?|endpoints?|servers?|pcs?)\b")
PRICE_LIMIT=re.compile(r"\b(?:не дороже|до|в пределах)\s+(\d+(?: \d{3})*(?:[.,]\d{1,2})?)\s*(тыс\w*|млн|[кk])?\s*(?:руб(?:лей|ля|ль)?\.?|₽|р\.)?\s*$")
LICENSE=r"лицензи(?:я|ю|и|й|ей)"
RENEW=re.compile(rf"\b(?:{LICENSE}\s+(?:на\s+)?)?(?:продл(?:ить|ение|ения)|renewal)(?:\s+(?:свою\s+)?{LICENSE})?\b")
PURCHASE=re.compile(rf"^(?:(?:найти|купить|нуж(?:ен|на|но|ны)|{LICENSE}(?:\s+на)?)\s+)+|[\s,]+{LICENSE}$")
HOME=re.compile(r"\b(?:домашн\w*|домой|для дома|для семьи)\b")
HELP=re.compile(r"^(?:как |чем |что (?:взять|поможет|подойд[её]т|поставить|нужно)|каки[еи]|какая |какой |нужн[ао] |хочу |на ч[её]м )")
COMPARE_OR_EXCL=re.compile(r"\b(?:vs|сравн\w*|или|кроме|деш[её]в\w*|дорог\w*)\b|(?:^|\s)не\s+\w+",re.I)
COMMERCE_QUESTION=re.compile(
    r"^(?:(?:подскажите|скажите|посоветуйте)[,\s]+)*"
    r"(?:сколько стоит|какая цена(?:\s+на)?|где купить|где взять|как купить|что есть у|какие продукты у)\s+"
    r"(?:(?:лицензи[юяией]|подписк[уаи]|программ[уа]|софт)\s+(?:на\s+)?)?",
    re.I,
)
COMMERCIAL_ACTION=re.compile(
    r"^(?:(?:требуется|нужн[аоы]|необходим[аоы])\s+)?(?:(?:докупить|докупка|расшир(?:ить|ение)|увелич(?:ить|ение)(?:\s+(?:числа|количества))?|дополнительн\w*)\s+"
    r"(?:дополнительн\w*\s+)?(?:лиценз\w*|подпис\w*|мест\w*|узл\w*)\s+(?:(?:на|для)\s+)?|"
    r"(?:поставка|закупка|приобретение)\s+(?:лиценз\w*|по|программного\s+обеспечения)\s+(?:(?:на|для)\s+)?|"
    r"(?:передача\s+)?(?:неисключительн\w+\s+)?прав[ао]?\s+на\s+использование\s+|"
    r"лицензи\w+\s+на\s+право\s+использования\s+)+",
    re.I,
)
REPLACE_QUESTION=re.compile(
    r"(?:что\s+(?:можно\s+)?поставить|что\s+(?:можно\s+)?взять|что\s+(?:можно\s+)?выбрать|"
    r"чем\s+(?:можно\s+)?заменить|замен[ауы]|альтернатив[ауы]|аналог(?:и|а|ов)?)\s+(?:вместо\s+)?(.+?)$|"
    r"\bвместо\s+(.+?)$",
    re.I,
)
REPLACE_TAIL=re.compile(r"\b(?:в россии|для бизнеса|для компании|для офиса|отечественн\w*|российск\w*)\b",re.I)
CONTEXT_TOOL_Q=re.compile(r"^(?:у\s+нас|есть|стоит|используем)\b.+?,\s*(?:чем|как|что|какой|какая)\b\s*(.+)$",re.I)
MIGRATION_RE=re.compile(
    r"\b(?:переход\w*|перейти|миграц\w*|мигрир\w*|перевод\w*|перевести|переезд\w*)\s+"
    r"(?:с|со|из)\s+(?P<src>.+?)\s+на\s+(?P<dst>.+?)$",
    re.I,
)
MIGRATION_ALIASES={"р7":"р7 офис","r7":"р7 офис"}
OS_COMPAT_RE=re.compile(
    r"\b(?:для|под|на|for)\s+(?P<os>astra\s+linux|астр\w*\s+линукс\w*|ред\s+ос|red\s+os|"
    r"альт\s+линукс\w*|alt\s+linux|windows\s+server|виндовс\s+сервер\w*|linux\s+server|сервер\w*\s+linux)\b",
    re.I,
)
SERVICE_PREFIX_RE=re.compile(
    r"^(?P<kind>обучени\w*|курс(?:ы|ов|ам)?|тренинг\w*|учебн\w+\s+курс\w*|"
    r"внедрени\w*|настройк\w*|установк\w*\s+и\s+настройк\w*|"
    r"тех(?:ническ\w+)?\s*поддержк\w*|поддержк\w*|сопровождени\w*)\s+"
    r"(?:(?:по|для|на)\s+)?(?:(?:работ\w*\s+(?:в|с)|администрировани\w*|настройк\w*|использовани\w*)\s+)?"
    r"(?:(?:программ\w*|по|ос|продукт\w*)\s+)?(?P<target>.+)$",
    re.I,
)
SERVICE_MARKERS={
    "training":re.compile(r"курс|обучен|course|awareness|тренинг|учебн",re.I),
    "support":re.compile(r"поддержк|support|expert\s+services|сертификат|сопровожден",re.I),
    "implementation":re.compile(r"внедрен|настройк|интеграц|expert\s+services|услуг",re.I),
}
GENERIC_HEAD=re.compile(
    r"^(?:программн\w+\s+обеспечени\w*|операционн\w+\s+систем\w*|"
    r"систем\w*|программ\w*|платформ\w*|решени\w*|комплекс\w*|средств\w*|сервис\w*|"
    r"софт\w*|по|утилит\w*|приложени\w*|инструмент\w*|пакет\w*|антивирус\w*)$",
    re.I,
)
# Лексические мосты между действием и существительным в дереве магазина.
PURPOSES=[
    (r"перевести|переводить|переводчик|машинн\w* перевод","переводчики"),
    (r"восстанов|вернуть.*(?:файл|удален|стерт)|реанимиров","восстановление данных"),
    (r"диаграм|блок.?схем|схем\w* (?:бизнес|процесс)","схемы и диаграммы"),
    (r"(?:перекод|конверт).*видео|видео.*(?:конверт|кодиров)","конвертеры и кодировщики"),
    (r"(?:освобод|очист|почист).*диск","очистка диска"),
    (r"инвентариз.*(?:пк|компьютер|лиценз|программ|оборудован)","программное обеспечение для учета компьютеров"),
    (r"удаленн.*(?:помощ|поддерж|подключ)|(?:помо|помощ|подключ|управл).*удален","удаленный доступ"),
]

def split_budget(q):
    match=PRICE_LIMIT.search(q)
    if not match:return q,None
    scale=match[2]
    amount=float(match[1].replace(" ","").replace(",","."))
    return q[:match.start()].strip(" ,"),amount*(1_000_000 if scale=="млн" else 1000 if scale else 1)


def split_conditions(q):
    m=QUANTITY.search(q)
    qty=None
    if m and int(m[1]):
        unit=m[2]
        metric="user" if unit.startswith(("польз","сотруд","челов","user","seat")) else None if unit.startswith(("лиценз","мест","licen")) else "device"
        if unit.startswith(("сервак","server")):metric="server"
        if unit.startswith("процессор"):metric="cpu"
        qty=dict(value=int(m[1]),metric=metric)
        q=q[:m.start()]+" "+q[m.end():]
    renewal=bool(RENEW.search(q))
    return " ".join(RENEW.sub("",q).strip(" ,;:-").split()),qty,renewal


def strip_question(text):
    """Снять вопросительную и коммерческую обёртку вокруг названия продукта или вендора."""
    if not text or COMPARE_OR_EXCL.search(text):
        return text
    cleaned=text.strip(" ?!.,;")
    stripped=COMMERCE_QUESTION.sub("",cleaned).strip(" ?!.,;«»\"")
    stripped=COMMERCIAL_ACTION.sub("",stripped).strip(" ?!.,;«»\"")
    if stripped and stripped!=cleaned:
        return stripped
    return text


def migration_target(text):
    """Выделить целевой продукт из запроса о переходе/миграции («переход с X на Y»)."""
    if not text:
        return None
    cleaned=text.strip(" ?!.,;")
    m=MIGRATION_RE.search(cleaned)
    if not m:
        return None
    src=m.group("src").strip(" ?!.,;«»\"")
    dst=m.group("dst").strip(" ?!.,;«»\"")
    if not src or not dst:
        return None
    # Не перехватываем «переход на российское ПО» без источника (там нет «с X») и апгрейд версий «с 10 на 11»
    if re.fullmatch(r"\d+(?:\.\d+)?",dst):
        return None
    dst_norm=MIGRATION_ALIASES.get(dst.lower(),dst)
    note=f"Переход с {src} на {dst}: ниже актуальные варианты целевого продукта."
    return src,dst_norm,note


def extract_os_compat(text):
    """Выделить указание целевой ОС (Astra Linux, РЕД ОС, Альт Линукс, Windows Server), чтобы не путать с вендором."""
    if not text:
        return text,None,None
    m=OS_COMPAT_RE.search(text)
    if not m:
        return text,None,None
    cleaned=" ".join((text[:m.start()]+" "+text[m.end():]).strip(" ,;:-").split())
    if not cleaned:
        return text,None,None
    os_raw=m.group("os").strip()
    low=os_raw.lower()
    if "server" in low or "сервер" in low:
        tag="server"
    else:
        tag="linux"
    label="Astra Linux" if ("astra" in low or "астр" in low) else (
        "РЕД ОС" if ("ред" in low or "red" in low) else (
            "Альт Линукс" if ("альт" in low or "alt" in low) else (
                "Windows Server" if ("windows" in low or "виндовс" in low) else os_raw
            )
        )
    )
    return cleaned,tag,label


def replacement_subject(text):
    """Выделить продукт из вопроса о замене («что поставить вместо X», «чем заменить X»)."""
    if not text:
        return None
    cleaned=text.strip(" ?!.,;")
    m=REPLACE_QUESTION.search(cleaned)
    if not m:
        return None
    raw=(m.group(1) or m.group(2) or "").strip(" ?!.,;«»\"")
    raw=REPLACE_TAIL.sub("",raw).strip(" ?!.,;«»\"")
    raw=re.sub(r"^(?:(?:для|на|программы|программе)\s+)+","",raw)
    return raw or None


def resolve_service_query(engine,req,norm,base,cond=None):
    """Обработка запросов на обучение/курсы/поддержку/внедрение по конкретному продукту или вендору."""
    index=engine.catalog.feed
    if req.verbatim or req.category or "\n" in req.q:
        return None
    kind=None
    target=None
    if cond and cond.service:
        kind=cond.service
        target=base
    else:
        m=SERVICE_PREFIX_RE.match(base) or SERVICE_PREFIX_RE.match(norm)
        if not m:
            return None
        raw_kind=m.group("kind").lower()
        target=m.group("target").strip(" ?!.,;«»\"")
        if not target:
            return None
        if raw_kind.startswith(("обуч","курс","тренинг","учеб")):
            kind="training"
        elif raw_kind.startswith(("внедр","настрой","установ")):
            kind="implementation"
        else:
            kind="support"

    marker=SERVICE_MARKERS[kind]
    # Собираем все карточки, относящиеся к целевому продукту/вендору
    pool=[]
    t_norm=normalize(target)
    t_words=" ".join(words(t_norm))
    vid=index.vendor_names.get(t_norm) or index.vendor_names.get(t_words)
    if not vid and t_norm in index.slang:
        field,slang_ids=index.slang[t_norm]
        if field=="vendors":
            pool.extend(slang_ids)
            if slang_ids:
                vid=index.card_vendors.get(slang_ids[0])
        else:
            pool.extend(slang_ids)
    if vid:
        pool.extend(index.language.vendor_cards.get(vid,()))
        pool.extend(index.cat.by["vendor"].get(vid,()))
    pool.extend(index.products(t_norm,domain="software",fuzzy=False))
    if not pool:
        pool.extend(index.products(index.correct(t_norm),domain="software",fuzzy=False))
    if not pool:
        sound_ids,_=index.sound_products(t_norm)
        pool.extend(sound_ids)
    # Дедупликация с сохранением приоритета качества
    pool=list(dict.fromkeys(cid for cid in pool if cid in index.cat.cards and index.cat.cards[cid].offers[0].domain=="software"))
    if not pool:
        return None

    direct=[]
    products=[]
    for cid in pool:
        card=index.cat.cards[cid]
        if marker.search(card.title) or any(marker.search(o.name) for o in card.offers[:15]):
            direct.append(cid)
        else:
            products.append(cid)
    direct.sort(key=lambda cid:(bool(marker.search(index.cat.cards[cid].title)),index.quality[cid]),reverse=True)
    products.sort(key=lambda cid:index.quality[cid],reverse=True)

    # Для support/implementation, перехваченных feed_conditions: вмешиваемся только если нашли прямые сервисные карточки
    # (например, Kaspersky Softline Expert Services для «техподдержка касперский»), чтобы не мешать обычному пути N4.
    if cond and cond.service and not direct:
        return None

    if direct:
        # Для training/support с найденными сервисными карточками ставим их первыми, затем сам продукт
        ordered=direct[:6]+products[:6]
        if kind=="support":
            note=f"Услуги поддержки и сервисы для «{target}», а также основные лицензии продукта."
            title=f"Техническая поддержка · {target}"
        elif kind=="training":
            note=f"Учебные курсы по «{target}» и основные лицензии продукта."
            title=f"Обучение · {target}"
        else:
            note=f"Услуги внедрения для «{target}» и основные лицензии продукта."
            title=f"Внедрение · {target}"
        return SolutionHit(id=f"service_{kind}",title=title,note=note,cards=tuple(ordered),sections=(),kit=True,exact=True,phrase_len=2)

    # Прямых курсов/услуг по этому продукту в каталоге нет -> честное пояснение + сам продукт + общие IT-курсы/сервисы каталога
    nearby=[]
    if kind=="training":
        for cid,card in index.cat.cards.items():
            if card.offers[0].domain!="software" or cid in products:
                continue
            tlow=card.title.lower()
            if "it-курс" in tlow or "электронный курс" in tlow:
                nearby.append(cid)
        nearby.sort(key=lambda cid:("it-курс" in index.cat.cards[cid].title.lower(),index.quality[cid]),reverse=True)
        note=f"Отдельного курса обучения по «{target}» в каталоге фида не выделено — ниже сам продукт и близкие учебные предложения каталога."
        title=f"Обучение · {target}"
    elif kind=="implementation":
        note=f"Отдельной услуги внедрения «{target}» в каталоге фида не выделено — ниже основные лицензии продукта."
        title=f"Внедрение · {target}"
    else:
        note=f"Отдельного сертификата поддержки для «{target}» в каталоге фида не выделено — ниже основные лицензии продукта."
        title=f"Поддержка · {target}"
    ordered=products[:4]+nearby[:2]
    return SolutionHit(id=f"service_{kind}",title=title,note=note,cards=tuple(ordered),sections=(),kit=True,exact=True,phrase_len=2)




def restore_platform_subject(norm,base,cond):
    """Если feed_conditions снял «на Windows / для Linux» как платформу, оставив пустой/общий каркас («где купить лицензию»), вернуть платформу как предмет запроса."""
    if not (cond and cond.platform):
        return base,False
    stripped=strip_question(base)
    if not stripped or re.fullmatch(r"(?:лиценз\w*|ключ\w*|подписк\w*|ос|операционн\w+\s+систем\w*|по|программ\w*|софт\w*|продукт\w*)",stripped):
        restored=strip_question(norm)
        if restored:
            return restored,True
    return base,False

def apply_solution_conditions(engine,req,profile,solution,ids,cond,os_compat,preferred,selections,use_qty,note,info=None):
    """Применить условия покупки и ОС-совместимость к карточкам курируемого решения."""
    from . import feed_conditions
    index=engine.catalog.feed
    ids=list(ids)
    extra_chips=[]
    eff_platform=(os_compat[0] if os_compat else None) or (cond.platform if cond else None)
    if eff_platform=="linux" and ids:
        if solution.id in ("office_suite","office_suite_ru"):
            non_ms=[cid for cid in ids if "microsoft" not in index.cat.cards[cid].title.lower()
                    and "microsoft" not in (index.cat.cards[cid].offers[0].vendor or "").lower()]
            if non_ms:
                ids=non_ms
        elif solution.id in ("mechanical_cad","cad_2d"):
            non_win=[cid for cid in ids if "autodesk" not in index.cat.cards[cid].title.lower()
                     and "autodesk" not in (index.cat.cards[cid].offers[0].vendor or "").lower()]
            if non_win:
                ids=non_win
        linux_explicit=[cid for cid in ids if "linux" in index.cat.cards[cid].title.lower()
                        or cid in index.platform_offers.get("linux",{})]
        if linux_explicit:
            seen=set(linux_explicit)
            ids=linux_explicit+[cid for cid in ids if cid not in seen]
    if cond and (cond.active or cond.price_min is not None or cond.price_max is not None) and ids:
        # Передаём section=None, чтобы условия фильтровали только карточки решения без подмешивания соседних разделов
        ids,_,note,relaxed=feed_conditions.apply_conditions(
            engine,req,profile,cond,ids,None,preferred,selections,use_qty,False,note)
        # Мягкий текстовый потолок цены: вызывающий узнаёт, что показаны ближайшие по цене варианты.
        if info is not None:info["price_relaxed"]=relaxed
        # Если cond.registry не нашёл флага registry на офферах и apply_conditions откатился к нефильтрованному списку,
        # всё равно отсекаем зарубежные продукты по is_domestic_card.
        if (cond.origin=="russian" or cond.registry) and ids:
            dom=[cid for cid in ids if feed_conditions.is_domestic_card(index,engine.kb,engine,cid)]
            if dom:
                ids=dom
    if os_compat and not (cond and cond.platform):
        extra_chips.append(dict(key="platform",label=f"ОС: {os_compat[1]}",removable=True))
    return ids,note,extra_chips

def resolve_solution(engine,req,norm,base,*,renewal=False,os_compat=None):
    """Распознать курируемую бизнес-задачу до ветки оборудования, опечаток и узких эвристик."""
    index=engine.catalog.feed
    if (req.verbatim or req.category or req.sort or req.weights or req.exclude or renewal
            or req.filters.keys()-{"price_max","price_min","origin","registry"}
            or set(req.ignore)-{"price_max","price_min","origin","registry","platform"}
            or "\n" in req.q or not index.solutions.rows):
        return None
    if COMPARE_OR_EXCL.search(norm) or COMPARE_OR_EXCL.search(base):
        return None
    # Не перехватываем запросы о миграции («переход с X на Y») — их обрабатывает migration_target
    if MIGRATION_RE.search(norm) or MIGRATION_RE.search(base):
        return None
    # Снимаем коммерческие/закупочные обёртки («поставка лицензий офисного пакета») для чистого матчинга
    clean_base=COMMERCIAL_ACTION.sub("",base).strip(" ?!.,;«»\"") or base
    # 1. Запрос о замене конкретного продукта на курируемый класс решений (AD, MS Office)
    rep=replacement_subject(clean_base) or replacement_subject(norm)
    if rep:
        hit=index.solutions.match_replacement(rep)
        if hit:
            return hit
        # Остальные запросы «аналог X» / «чем заменить X» обрабатывает feed_analogs
        return None
    # 2. Не перехватывать out-of-catalog бренды («veeam backup», «1с бухгалтерия», «zoom»)
    row=index.analogs.lookup(clean_base,fuzzy=False)
    if row and not row["in_catalog"]:
        return None
    # 3. Конструкция «у нас <контекст>, чем его <задача>»: приоритет у вопросительной части
    ctx_q=CONTEXT_TOOL_Q.match(clean_base) or CONTEXT_TOOL_Q.match(norm)
    if ctx_q:
        hit=index.solutions.match(ctx_q.group(1))
        if hit:
            return hit
    # 4. Поиск самой длинной фразы задачи (с учётом ОС-совместимости, чтобы «сапр для astra linux» не путалось с вендором Astra)
    hit=None
    if os_compat and os_compat[0]=="linux":
        # Сначала ищем по предмету без ОС-хвоста («сапр»)
        os_subj=extract_os_compat(clean_base)[0]
        hit=index.solutions.match(os_subj)
    if not hit:
        hit=index.solutions.match(clean_base) or (index.solutions.match(base) if base!=clean_base else None)
    if not hit and norm!=base:
        hit=index.solutions.match(norm)
    if not hit:
        return None
    # 5. Защита: конкретный продаваемый продукт или бренд имеют приоритет над задачей
    check_text=extract_os_compat(clean_base)[0] if (os_compat and os_compat[0]=="linux") else clean_base
    if not hit.exact:
        if index.edition(check_text):
            return None
        if index.recovery.full_name(check_text)[0]:
            return None
        if product_context(engine,check_text):
            return None
        if vendor_class(index,check_text)[0]:
            return None
        parts=check_text.split()
        if len(parts)>=2:
            for length in range(min(len(parts)-1,3),0,-1):
                for side in (parts[:length],parts[-length:]):
                    alias=" ".join(side)
                    alias_w=" ".join(words(alias))
                    # Не уступаем вендору, если само слово является точным названием задачи/класса (например, «видеомонтаж» -> AMS Software)
                    if index.solutions.is_exact_phrase(alias) or index.solutions.is_exact_phrase(alias_w):
                        continue
                    if alias in index.vendor_names or alias_w in index.vendor_names:
                        return None
    return hit


def license_request(engine,text):
    """Распознать отдельный запрос о программе поставки или единице лицензирования."""
    match=re.fullmatch(r"(?:лицензи[яиюй]\s+)?на\s+(?:\d+\s*)?([а-яa-z]+)",text)
    if match:
        term,kind=match[1],"metric"
    elif " " not in text:
        term,kind=text,"license_type"
    else:
        return None
    return next(((kind,value) for _,_,found in engine.lex.match([term])
                 for name,value,_ in found if name==kind),None)


def purchase_subject(text):
    return PURCHASE.sub("",text).strip(" ,") or text


def supplier_clause(index,text):
    """Выделяем «от» только перед подтверждённым названием издателя."""
    head,sep,tail=text.partition(" от ")
    if sep:
        parts=tail.split()
        for end in range(len(parts),0,-1):
            if parts[end-1] in STOP:continue
            vendor=index.vendor_names.get(" ".join(words(" ".join(parts[:end]))))
            if vendor:return " ".join([head,*parts[end:]]),vendor
    return text,None


def vendor_class(index,q):
    parts=q.split()
    for length in range(min(len(parts)-1,5),0,-1):
        for vendor,rest in [(parts[:length],parts[length:]),(parts[-length:],parts[:-length])]:
            alias=" ".join(vendor)
            group=index.vendor_names.get(alias) or index.vendor_names.get(" ".join(words(alias)))
            if not group:continue
            label=" ".join(rest)
            label=re.sub(r"^(?:решени\w*|софт|программ\w*|по) для ","",label)
            section=index.class_match(label)
            if not section:
                device=index.hardware.get(label,{})
                section=next((str(k) for k in device.get("hardware_feed_classes",[]) if str(k) in index.groups),None)
            if not section and re.fullmatch(r"антивирус\w*",label):
                section=index.class_by_name.get("антивирусы для организаций")
            if not section:section=index.language.section(index,label)
            if not section:section=index.task_class(label)
            if section:return group,section
    return None,None


def software_for_class(engine,vendor,label):
    """Класс-омоним у издателя ПО: проверяем продукты из тематических задач БЗ."""
    index=engine.catalog.feed
    key=set(words(label))
    if not key:return []
    categories={k for k,row in engine.kb.rows["categories"].items()
                if key<=set(words(row.get("title_short") or row.get("title","")))}
    names={name for row in index.task_rows.values() if categories.intersection(row.get("categories",[]))
           for name in row.get("products",[])}
    found=set()
    for name in names:
        terms=set(words(name))
        for cid in index.products(name,fuzzy=False):
            card=index.cat.cards[cid]
            if index.card_vendors[cid]==vendor and card.offers[0].domain=="software" and terms<=set(words(card.title)):
                found.add(cid)
    return sorted(found,key=lambda cid:(index.quality[cid],cid),reverse=True)


def mixed_subject(index,text):
    if re.search("[a-z]",text) and re.search("[а-я]",text) and not index.products(text,fuzzy=False):
        ids,corrected=index.sound_products(text)
        if ids:return corrected
    return text


def matching_variants(index,ids,profile,qty,renewal,conditions=None,*,nodes=False):
    filters=dict(conditions or {})
    if qty and qty["metric"]:filters["metric"]=qty["metric"]
    if nodes and qty and qty["metric"]=="device":filters["metric"]=["device","server"]
    if renewal:filters["action"]="renewal"
    selected={}
    for cid in ids:
        card=index.cat.cards[cid]
        selection=select(card,profile,filters,{},qty)
        if not selection and renewal and profile.client_id=="guest" and "audience" not in filters:
            selection=select(card,profile,{**filters,"audience":"home"},{},qty)
        if not selection and filters.get("audience") and "price_max" not in filters and not qty and not renewal:
            offer=next((o for o in card.offers if all(getattr(o.lic,k,getattr(o,k,None))==v for k,v in filters.items())),None)
            if offer:selection=(offer,None,None)
        if selection:selected[cid]=selection
    return selected


CONTEXT = re.compile(r"\s+(?:для|под|чтобы|на|в)\s+",re.I)
TERM = re.compile(r"\b(\d{1,2})\s*(мес\w*|год\w*|лет)\b")
AUDIENCES = [("home",r"для дома|домашн|личн\w* использ"),("edu",r"школ|университет|учебн|образован"),
             ("gov",r"госучрежд|госорган|государствен"),("business",r"компани|организац|офис|бухгалтер")]
FUNCTION_WORDS={"защита":"protection","безопасность":"security","управление":"management",
                "резервирование":"backup","мониторинг":"monitor"}


def described_line(index,text):
    """Ищем марку до описания функции, затем уточняем её по классу и названию."""
    parts=text.split()
    for pos in range(1,min(5,len(parts))):
        tail=" ".join(parts[pos:])
        terms=words(tail)
        if not terms or terms[0] not in FUNCTION_WORDS:continue
        head=" ".join(parts[:pos])
        if (GENERIC_HEAD.fullmatch(head) or index.class_match(head)
                or head in index.hardware or index.solutions.is_exact_phrase(head)):
            continue
        name=index.correct(head)
        ids=index.products(name,fuzzy=False)
        if not ids:ids,name=index.sound_products(head)
        ids=[cid for cid in ids if set(words(name))<=set(words(index.cat.cards[cid].title))]
        if not ids:continue
        section=index.task_class(tail) or index.class_match(tail)
        features=set(terms)|{FUNCTION_WORDS[terms[0]]}
        return sorted(ids,key=lambda cid:(index.card_sections[cid]==section,
                            len(features.intersection(words(index.cat.cards[cid].title)))),reverse=True)
    return ()


def product_context(engine,text):
    """Выделить продаваемую линейку перед описанием применения."""
    index=engine.catalog.feed
    split=CONTEXT.search(text)
    if not split:
        named=described_line(index,text)
        return (named,{}) if named else None
    head=text[:split.start()]
    if (GENERIC_HEAD.fullmatch(head) or head in index.hardware
            or index.class_match(head) or index.solutions.is_exact_phrase(head)):
        return None
    mapped,_=engine._phrases.apply(head)
    phrase=index.correct(mapped)
    refs=engine.lex.match(head.split())
    candidates=[]
    for start,end,matches in refs:
        if start!=0 or end!=len(head.split()):continue
        for kind,key,_ in matches:
            if kind=="family":
                family=engine.kb.rows["families"].get(key,{})
                for label in (family.get("name"),family.get("title")):
                    if label:candidates.extend(index.products(normalize(label)))
                candidates.extend(sorted(index.tags["families"].get(key,()),key=index.quality.get,reverse=True))
    phrase=edition_form(index,phrase)
    hits=index.products(phrase)
    spoken,_=index.sound_products(head)
    if not spoken and head!=phrase:spoken,_=index.sound_products(phrase)
    # Затемнение названия нечётким соседом («Фотошоу» и «Фотошоп»)
    # особенно заметно, когда за маркой идёт описание работы.
    literal=[cid for cid in hits if set(words(phrase))<=index.terms[cid]]
    vendor=index.vendor_names.get(head) or index.vendor_names.get(" ".join(words(head)))
    brand=sorted(index.cat.by["vendor"].get(vendor,()),key=index.quality.get,reverse=True) if vendor else ()
    supported=tuple(dict.fromkeys(literal or candidates or brand or spoken or hits))
    if not supported:return None
    tail=text[split.start():]
    context={}
    audience=next((key for key,pattern in AUDIENCES if re.search(pattern,tail)),None)
    if audience:context["audience"]=audience
    term=TERM.search(tail)
    if term:context["term_months"]=int(term[1])*(1 if term[2].startswith("мес") else 12)
    return supported,context

# Снимаем вводное родовое название только перед названием продукта.
WRAPPER=re.compile(r"^(?:(?:операционная система|программ[аы]|платформ[аы]|систем[аы]|софт|приложени[ея]|сервис(?:ы)?|утилит[аы]|решени[ея])\s+)+")
def product_subject(index,base):
    candidate=WRAPPER.sub("",base).strip("«»\" ")
    if (candidate and candidate!=base and not re.match(r"^(?:для|по|от|с|на|под|и|чтобы)\b",candidate)
            and candidate not in index.hardware and not index.class_match(base)):
        return candidate
    return base

SERVER_TAIL=re.compile(r"\s+(?:на|для)\s+сервер(?:е|а|ах|ы|ов)?$")


def software_scope(index,base):
    """Класс программы и, отдельно, назначение для сервера."""
    tail=SERVER_TAIL.search(base)
    if not tail:return None
    head=base[:tail.start()]
    label=re.sub(r"^(?:софт|по|программ(?:ы|а|ное обеспечение))\s+для\s+","",head)
    if not index.class_match(label) and index.products(label,fuzzy=False):return None
    return index.language.section(index,label)


def named_subject(engine,base):
    """Проверить часть после названия класса до маршрутизации по классу."""
    index=engine.catalog.feed
    for rest in index.language.class_prefixes(index,base):
        if rest.startswith(("для ","под ","на ","в ","от ")):continue
        head=CONTEXT.split(rest,maxsplit=1)[0]
        mapped,_=engine._phrases.apply(head)
        name=edition_form(index,index.correct(mapped))
        # Голое имя производителя в запросе о классе — ограничение по вендору.
        if not re.search(r"[а-яa-z]",name):continue
        if (head in index.vendor_names or " ".join(words(head)) in index.vendor_names) and vendor_class(index,base)[0]:
            kind=index.slang.get(head,(None,()))[0]
            if kind!="families" and not index.recovery.full_name(name)[0]:continue
        ids=index.products(name,fuzzy=False) or index.slang.get(head,(None,()))[1]
        if not ids:ids=index.sound_products(name)[0]
        if not ids:continue
        return rest
    return base
