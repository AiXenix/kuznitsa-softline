from collections import Counter
from itertools import groupby


def diversify(cards):
    """Перестановки только внутри одной полосы; резерв заполняет свободные места."""
    result=[]
    vendors=Counter()
    families=set()
    for _,group in groupby(cards,key=lambda c:c["score"]["tier"]):
        reserve=[]
        for c in group:
            family=c["card_id"].split(":")[0]
            vendor=c["vendor"]["id"]
            if len(result)<6 and (vendors[vendor]>=2 or family in families):
                reserve.append(c)
                continue
            result.append(c)
            families.add(family)
            vendors[vendor]+=1
        result.extend(reserve)
    return result
