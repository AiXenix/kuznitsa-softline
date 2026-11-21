import re

UNITS = ("ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать "
         "четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать").split()
NUMBERS = dict(zip(UNITS,range(20)))
NUMBERS.update(одну=1,одна=1,две=2,двух=2,трех=3)
TENS = dict(zip("двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто сто".split(),range(20,101,10)))


def number_before(words,i):
    if i==0:
        return None
    token=words[i-1]
    if token.isdigit() and len(token)<=9:
        return int(token)
    value=NUMBERS.get(token,TENS.get(token))
    if value is not None and value<10 and i>1 and words[i-2] in TENS:
        value+=TENS[words[i-2]]
    return value


def numeric_conditions(words,filters,qty):
    text=" ".join(words)
    if re.search(r"\bна год\b|\bгодов",text):
        filters["term_months"]=12
    for i,word in enumerate(words):
        n=number_before(words,i)
        if n is not None:
            if re.fullmatch(r"год|года|лет|месяц\w*|мес",word):
                filters["term_months"]=n*(12 if word.startswith(("год","лет")) else 1)
            if word in ("шт","штук","лицензий","лицензии") and not qty:
                qty=dict(value=n,metric=None)
    extra=re.search(r"\b(\d{1,9})\s*(?:удал[её]нн\w* )?(pk|пк|сотрудник\w*|процессор\w*|ядер|ядра|хост\w*)\b",text)
    if extra and not qty:
        unit=extra[2]
        metric="cpu" if unit.startswith("процессор") else "server" if unit.startswith("хост") else "user" if unit.startswith("сотрудник") else "core" if unit.startswith("яд") else "device"
        qty=dict(value=int(extra[1]),metric=metric)
        filters["metric"]=metric
    cal=re.search(r"\b(device|user) cal (\d{1,8})\b",text)
    if cal:
        filters["metric"]=cal[1]
        qty=dict(value=int(cal[2]),metric=cal[1])
    if qty and re.search(r"\d+ (?:мест|места)\b",text) and not re.search(r"сотрудник|пользовател",text):
        qty["metric"]=filters["metric"]="device"
    if "для сервера" in text:
        filters.setdefault("metric","server")
    workplaces=re.search(r"\b(\d{1,9})\s+рабочи[хе]\s+мест",text)
    if workplaces:
        qty=dict(value=int(workplaces[1]),metric="device")
        filters["metric"]="device"
    count=re.search(r"\b[xх](\d{1,9})\b",text)
    if count and not qty:
        qty=dict(value=int(count[1]),metric=None)
    # Диапазоны без валюты относятся к числу лицензий.
    band=re.search(r"\b(?:от (\d{1,9}) до (\d{1,9})|(\d{1,9})-(\d{1,9}))(?: (пк|комп\w*|узл\w*|пользовател\w*))?\b",text)
    if band and not re.search(r"руб|тыс|бюджет|цен",text):
        low,high=map(int,(band[1] or band[3],band[2] or band[4]))
        if 0<low<=high:
            qty=dict(value=low,max=high,metric=filters.get("metric"))
            text=text[:band.start()]+text[band.end():]
    text=re.sub(r"(?<=\d) (?=\d{3}(?:\D|$))","",text)
    for m in re.finditer(r"\b(не дороже|в пределах|до|от|дешевле|дороже)\s+(\d{1,12}(?:[.,]\d{1,2})?)\s*(млн|миллион\w*|тыс\w*|[kк]\b)?",text):
        filters["price_max" if m[1] in ("до","дешевле","не дороже","в пределах") else "price_min"]=float(m[2].replace(",","."))*(1_000_000 if (m[3] or "").startswith(("млн","миллион")) else 1000 if m[3] else 1)
    return qty


def spoken_numbers(text):
    vocab={**NUMBERS,**TENS,"полсотни":50,"двести":200,"триста":300,"четыреста":400,"пятьсот":500,
           "шестьсот":600,"семьсот":700,"восемьсот":800,"девятьсот":900}
    from kuznitsa.text import lemma
    text=re.sub(r"\bполутор[аы] сот(?:ни|ен|ням)\b","150",text)
    text=re.sub(r"\bсорока\b","сорок",text)
    text=re.sub(r"\bполутор[аы] год\w*", "18 мес",text)
    text=re.sub(r"\bполтор[аы] год\w*", "18 мес",text)
    parts=text.split()
    result=[]
    i=0
    while i<len(parts):
        start=i
        value=total=0
        while i<len(parts):
            w=parts[i]
            if w not in vocab and w.endswith(("ти","ми","ех","ых","ум","ью","ста","сот","сти","и")):
                base=lemma(w)
                if base in vocab:w=base
            if w in vocab:value+=vocab[w]
            elif w in ("сотня","сотни","сотен"):value=(value or 1)*100
            elif w in ("тысяча","тысячи","тысяч"):total+=(value or 1)*1000;value=0
            else:break
            i+=1
        if i>start:
            # Числовой множитель после цифры обрабатывается вместе с ценой.
            result.extend(parts[start:i] if start and parts[start-1].isdigit() and parts[start].startswith("тыс") else [str(total+value)])
        else:
            result.append(parts[i])
            i+=1
    return " ".join(result)
