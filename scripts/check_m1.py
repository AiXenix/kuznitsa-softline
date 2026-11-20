"""Снимок выдачи и времени ответа. Запуск из корня: python -m scripts.check_m1."""
from collections import defaultdict
from math import ceil
from random import Random
from statistics import median
from time import perf_counter

from kuznitsa.engine import Engine
from kuznitsa.schema import Request


def run():
    started=perf_counter()
    engine=Engine.open()
    offers=sum(len(c.offers) for c in engine.catalog.cards.values())
    print(f"Загрузка с готовыми индексами заняла {perf_counter()-started:.2f} с. В каталоге {len(engine.catalog.cards)} карточек, {offers} предложений.")
    sku=next(iter(engine.catalog.skus.values())).sku
    samples=["каспер продление на 30 компов","rfcgthcrbq ghjlktybt yf 30 rjvgjd","антивирус на 50 пк","виндовс 11 про","astra linux",
             sku,sku.translate(str.maketrans("ABCEHKMOPTXY","АВСЕНКМОРТХУ")),"офис","autocad","антивирус не касперский","касперский до 3000","купить ноутбук","asdfgh"]
    queries=[(q,"smb_trade" if i<2 else "guest") for i,q in enumerate(samples)]
    queries += [("антивирус на 30 пк",p) for p in ("smb_trade","gov_clinic","edu_university")]
    rng=Random(20261126)
    times=defaultdict(list)
    responses={}
    order=queries.copy()
    for iteration in range(6):
        rng.shuffle(order)
        for q,p in order:
            r=engine.search(Request(q=q,profile_id=p,source="eval",mode="fast"))
            responses[q,p]=r
            if iteration:
                times[q,p].append(r["timing_ms"]["total"])
    all_times=sorted(x for series in times.values() for x in series)
    print(f"После одного прогрева каждого сочетания запроса и профиля выполнено {len(all_times)} поисков в перемешанном порядке. "
          f"Медиана {median(all_times):.1f} мс, p95 {all_times[ceil(.95*len(all_times))-1]:.1f} мс, максимум {max(all_times):.1f} мс. "
          "Замер включает запись поиска в SQLite и использует кэш векторов запросов.")
    print("\n| Запрос · профиль | Что понял поиск | Первые карточки по порядку | Медиана, мс |\n|---|---|---|---:|")
    for q,p in queries:
        r=responses[q,p]
        cards=[i.get("card",i) for b in r["blocks"] if b["type"] in ("products","analogs") for i in b["items"]]
        u=r["understood"]
        chips=[c["label"] for c in u["chips"] if c["source"]=="query"]
        summary=u["intent_title"]+(" · "+", ".join(chips) if chips else "")
        if r["query"]["corrections"]:
            summary+=" · исправлено на «"+r["query"]["corrected"]+"»"
        desc=[]
        for c in cards[:3]:
            label=c["title"]
            if p!="guest":
                label+=f" ({c['offer']['audience']}, {c['offer']['action']})"
            desc.append(label)
        print(f"| {q} · {p} | {summary} | {' · '.join(desc) or '—'} | {median(times[q,p]):.1f} |")


if __name__=="__main__":
    run()
