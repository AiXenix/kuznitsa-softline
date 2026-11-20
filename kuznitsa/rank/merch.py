from fnmatch import fnmatchcase
from kuznitsa.text import normalize


def matches(condition,ctx):
    for key,field in (("intent","intent"),("category","category_id"),("segment","segment")):
        if condition.get(key) and ctx.get(field)!=condition[key]:
            return False
    q=ctx.get("q_norm") or normalize(ctx.get("q_raw",""))
    return (not condition.get("phrase") or q==normalize(condition["phrase"])) and (
        not condition.get("pattern") or fnmatchcase(q,normalize(condition["pattern"])))


def apply(rules,ctx,cards):
    cards=list(cards)
    fired=[]
    banners=[]
    labels=dict(pin="Закреплено",boost="Поднято",bury="Опущено",ban="Скрыто",banner="Показана плашка")
    for rule in rules:
        kind=rule["kind"]
        if kind not in labels or not matches(rule["conditions"],ctx):
            continue
        a=rule["action"]
        ident=a.get("card_id")
        if kind=="banner":
            banners.append(dict(kind=kind,text=a["text"],rule_id=rule["id"]))
        else:
            index=next((i for i,c in enumerate(cards) if c["card_id"]==ident),None)
            if index is None:
                continue
            c=cards[index]
            if kind=="ban":
                cards.pop(index)
            elif kind=="pin":
                cards.insert(min(len(cards)-1,a.get("position",1)-1),cards.pop(index))
            else:
                # Переставляем только карточки одного яруса, в т. ч. после закрепления.
                positions=[i for i,x in enumerate(cards) if x["score"]["tier"]==c["score"]["tier"]]
                cohort=[cards[i] for i in positions]
                factor=a.get("factor",1.25 if kind=="boost" else .8)
                current=cohort.index(c)
                adjusted=c["score"]["score"]*factor
                new=current
                if kind=="boost":
                    while new>0 and cohort[new-1]["score"]["score"]<adjusted:
                        new-=1
                else:
                    while new+1<len(cohort) and cohort[new+1]["score"]["score"]>adjusted:
                        new+=1
                cohort.insert(new,cohort.pop(current))
                for i,x in zip(positions,cohort):
                    cards[i]=x
        fired.append(dict(kind=kind,card_id=ident,rule_id=rule["id"],summary=labels[kind]+" правилом магазина"))
    return dict(cards=cards,banners=banners,fired=fired)
