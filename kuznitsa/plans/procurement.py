"""Область подбора по классификаторам закупки."""
import re

from kuznitsa.text import tokens


def classification(kb,lex,text):
    match=re.search(r"\b(окпд2|ктру)\s+(\d+(?:\.\d+)+)",text)
    if not match:
        return [],None
    code=match[2]
    # Позиции КТРУ начинаются с группы ОКПД2. В KB есть также общие
    # справочные записи о классификаторах без предметного раздела.
    by_code={}
    for row in kb.rows["compliance"].values():
        for alias in row.get("aliases",[]):
            if not isinstance(alias,str):
                continue
            found=re.fullmatch(r"(окпд2|ктру) (\d+(?:\.\d+)+)",alias.lower())
            if found:
                by_code[found[1],found[2]]=row
    parts=code.split(".")
    while parts:
        prefix=".".join(parts)
        row=by_code.get((match[1],prefix)) or by_code.get(("окпд2",prefix))
        if row:
            categories=[]
            for phrase in row.get("aliases",[]):
                terms=re.sub(r"^(?:код )?(?:окпд2?|ктру)\s+", "",str(phrase).lower())
                if not re.search(r"\d",terms):
                    categories.extend(v for _,_,entries in lex.match(tokens(terms)) for kind,v,_ in entries if kind=="category")
            if not categories:
                for definition in re.findall(r"\(([^)]+)\)",row.get("explain","")):
                    categories.extend(v for _,_,entries in lex.match(tokens(definition)) for kind,v,_ in entries if kind=="category")
            return list(dict.fromkeys(categories)),row
        parts.pop()
    return [],None


def offer_codes(offer):
    fields={"окпд2":"окпд2","okpd2":"окпд2","ктру":"ктру","ktru":"ктру"}
    for key,value in offer.attrs.items():
        kind=fields.get(key.strip().lower())
        if kind:
            for match in re.finditer(r"(?<!\d)\d{2}(?:\.\d+)+(?:-\d+)?(?!\d)",value):
                code=match.group()
                yield kind,code
                while (end:=max(code.rfind("."),code.rfind("-")))>=0:
                    code=code[:end]
                    yield kind,code
