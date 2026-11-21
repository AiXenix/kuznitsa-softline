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
    for m in re.finditer(r"\b(до|от|дешевле|дороже)\s+(\d{1,12}(?:[.,]\d{1,2})?)\s*(тыс\w*|к\b)?",text):
        filters["price_max" if m[1] in ("до","дешевле") else "price_min"]=float(m[2].replace(",","."))*(1000 if m[3] else 1)
    return qty
