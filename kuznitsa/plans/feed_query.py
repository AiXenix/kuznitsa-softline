"""Условия запроса, которые можно проверить по строкам фида."""
import re
from kuznitsa.index.feed import words
from kuznitsa.text import normalize
from kuznitsa.rank.variants import select

QUANTITY=re.compile(r"\b(?:на\s+)?(\d{1,7})\s*(?:рабоч\w*\s+)?(пользовател\w*|сотрудник\w*|уз(?:ел|ла|лов)|устройств\w*|компьютер\w*|мест\w*|лицензи\w*|пк)\b")
RENEW=re.compile(r"\b(?:продл(?:ить|ение|ения)|renewal)\b")
HOME=re.compile(r"\b(?:домашн\w*|для дома|для семьи)\b")
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

def split_conditions(q):
    m=QUANTITY.search(q)
    qty=None
    if m and int(m[1]):
        unit=m[2]
        metric="user" if unit.startswith(("польз","сотруд")) else None if unit.startswith(("лиценз","мест")) else "device"
        qty=dict(value=int(m[1]),metric=metric)
        q=q[:m.start()]+" "+q[m.end():]
    renewal=bool(RENEW.search(q))
    return " ".join(RENEW.sub("",q).strip(" ,;:-").split()),qty,renewal


def vendor_class(index,q):
    parts=q.split()
    for length in range(min(len(parts)-1,5),0,-1):
        for vendor,rest in [(parts[:length],parts[length:]),(parts[-length:],parts[:-length])]:
            alias=" ".join(vendor)
            group=index.vendor_names.get(alias) or index.vendor_names.get(" ".join(words(alias)))
            if not group:continue
            label=" ".join(rest)
            section=index.class_match(label)
            if not section:
                device=index.hardware.get(label,{})
                section=next((str(k) for k in device.get("hardware_feed_classes",[]) if str(k) in index.groups),None)
            if not section and re.fullmatch(r"антивирус\w*",label):
                section=index.class_by_name.get("антивирусы для организаций")
            if section:return group,section
    return None,None


def matching_variants(index,ids,profile,qty,renewal,conditions=None):
    filters=dict(conditions or {})
    if qty and qty["metric"]:filters["metric"]=qty["metric"]
    if renewal:filters["action"]="renewal"
    selected={}
    for cid in ids:
        card=index.cat.cards[cid]
        selection=select(card,profile,filters,{},qty)
        if not selection and filters.get("audience") and not qty and not renewal:
            offer=next((o for o in card.offers if all(getattr(o.lic,k)==v for k,v in filters.items())),None)
            if offer:selection=(offer,None,None)
        if selection:selected[cid]=selection
    return selected


CONTEXT = re.compile(r"\s+(?:для|под|чтобы|на|в)\s+",re.I)
TERM = re.compile(r"\b(\d{1,2})\s*(мес\w*|год\w*|лет)\b")
AUDIENCES = [("home",r"для дома|домашн|личн\w* использ"),("edu",r"школ|университет|учебн|образован"),
             ("gov",r"госучрежден|госорган|государствен"),("business",r"компани|организац|офис|бухгалтер")]


def product_context(engine,text):
    """Выделить продаваемую линейку перед описанием применения."""
    index=engine.catalog.feed
    split=CONTEXT.search(text)
    if not split:return None
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
    phrase=re.sub(r"^ms\s+","microsoft ",phrase)
    if phrase.endswith(" se"):
        phrase=phrase[:-3]+" special edition"
    hits=index.products(phrase)
    spoken,_=index.sound_products(phrase)
    # Затемнение названия нечётким соседом («Фотошоу» и «Фотошоп»)
    # особенно заметно, когда за маркой идёт описание работы.
    literal=[cid for cid in hits if set(words(phrase))<=index.terms[cid]]
    vendor=index.vendor_names.get(head) or index.vendor_names.get(" ".join(words(head)))
    brand=sorted(index.cat.by["vendor"].get(vendor,()),key=index.quality.get,reverse=True) if vendor else ()
    supported=tuple(dict.fromkeys(candidates or brand or spoken or literal or hits))
    if not supported:return None
    tail=text[split.start():]
    context={}
    audience=next((key for key,pattern in AUDIENCES if re.search(pattern,tail)),None)
    if audience:context["audience"]=audience
    term=TERM.search(tail)
    if term:context["term_months"]=int(term[1])*(1 if term[2].startswith("мес") else 12)
    return supported,context
