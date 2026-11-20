"""Минимальная стоимость покрытия тиража совместимыми пакетами."""
from functools import lru_cache
from math import ceil


@lru_cache(1024)
def counts(prices,target):
    if target<=0:
        return (0,)*len(prices)
    if len(prices)==1:
        return (ceil(target/prices[0][0]),)
    if target>10000:
        # Целочисленная задача с одной строкой ограничений, без массива на N мест.
        from scipy.optimize import Bounds,LinearConstraint,milp
        sizes,costs=zip(*prices)
        solution=milp(costs,integrality=[1]*len(sizes),bounds=Bounds(0,ceil(target/min(sizes))),
                      constraints=LinearConstraint([sizes],target,float("inf")),options={"mip_rel_gap":0})
        if not solution.success:
            raise ArithmeticError("Не удалось подобрать комбинацию пакетов")
        return tuple(round(x) for x in solution.x)
    cost=[0.]*(target+1)
    chosen=[0]*(target+1)
    for n in range(1,target+1):
        cost[n],chosen[n]=min((cost[max(0,n-size)]+amount,i) for i,(size,amount) in enumerate(prices))
    result=[0]*len(prices)
    while target>0:
        i=chosen[target]
        result[i]+=1
        target-=prices[i][0]
    return tuple(result)


def bundle(offers,n,base_required=False,base_size=None):
    cheapest={}
    for o in offers:
        size=o.lic.pack
        if size and o.price is not None and not o.price_on_request and o.available:
            if size not in cheapest or cheapest[size].price>o.price:
                cheapest[size]=o
    if not cheapest:
        return []
    base=(base_size or max(cheapest)) if base_required else 0
    if base and base not in cheapest:
        return []
    prices=tuple((s,cheapest[s].price) for s in sorted(cheapest,reverse=True))
    return [(cheapest[s],m+(s==base)) for (s,amount),m in zip(prices,counts(prices,n-base)) if m or s==base]
