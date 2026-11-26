"""Условия запроса, которые можно проверить по строкам фида."""
import re
from kuznitsa.index.feed import STOP, words
from kuznitsa.text import normalize
from kuznitsa.index.feed_language import edition_form
from kuznitsa.rank.variants import select

QUANTITY=re.compile(r"\b(?:на\s+)?(\d{1,7})\s*(?:рабоч\w*\s+)?(пользовател\w*|сотрудник\w*|уз(?:ел|лы|ла|лов|лах)|устройств\w*|комп(?:ьютер\w*|ов|а)?|сервак\w*|процессор\w*|мест\w*|лицензи\w*|пк)\b")
PRICE_LIMIT=re.compile(r"\b(?:не дороже|до|в пределах)\s+(\d+(?: \d{3})*(?:[.,]\d{1,2})?)\s*(тыс\w*|млн|[кk])?\s*(?:руб(?:лей|ля|ль)?\.?|₽|р\.)?\s*$")
LICENSE=r"лицензи(?:я|ю|и|й|ей)"
RENEW=re.compile(rf"\b(?:{LICENSE}\s+(?:на\s+)?)?(?:продл(?:ить|ение|ения)|renewal)(?:\s+(?:свою\s+)?{LICENSE})?\b")
PURCHASE=re.compile(rf"^(?:(?:найти|купить|нуж(?:ен|на|но|ны)|{LICENSE}(?:\s+на)?)\s+)+|[\s,]+{LICENSE}$")
HOME=re.compile(r"\b(?:домашн\w*|домой|для дома|для семьи)\b")
HELP=re.compile(r"^(?:как |чем |что (?:взять|поможет|подойд[её]т)|каки[еим]|нужн[ао] |хочу )")
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
        metric="user" if unit.startswith(("польз","сотруд")) else None if unit.startswith(("лиценз","мест")) else "device"
        if unit.startswith("сервак"):metric="server"
        if unit.startswith("процессор"):metric="cpu"
        qty=dict(value=int(m[1]),metric=metric)
        q=q[:m.start()]+" "+q[m.end():]
    renewal=bool(RENEW.search(q))
    return " ".join(RENEW.sub("",q).strip(" ,;:-").split()),qty,renewal


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
            offer=next((o for o in card.offers if all(getattr(o.lic,k)==v for k,v in filters.items())),None)
            if offer:selection=(offer,None,None)
        if selection:selected[cid]=selection
    return selected


CONTEXT = re.compile(r"\s+(?:для|под|чтобы|на|в)\s+",re.I)
TERM = re.compile(r"\b(\d{1,2})\s*(мес\w*|год\w*|лет)\b")
AUDIENCES = [("home",r"для дома|домашн|личн\w* использ"),("edu",r"школ|университет|учебн|образован"),
             ("gov",r"госучрежден|госорган|государствен"),("business",r"компани|организац|офис|бухгалтер")]
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
        if index.class_match(head) or head in index.hardware:continue
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
    if head in index.hardware or index.class_match(head) or re.fullmatch(r"антивирус\w*|программ\w*|софт|средств\w*",head):
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
