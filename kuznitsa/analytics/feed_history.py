"""Модель 90 дней поискового спроса на товары переданного каталога."""
from collections import Counter
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
import random
from time import time

from kuznitsa.mock.querylog_gen import MSK, describe, distort
from kuznitsa.plans.naive import match
from kuznitsa.text import normalize
from .lineage import save_mock
from .store import dump

NOTE = "История синтетическая, параметры — из задания организаторов."


def generate(e, seed, today=None):
    rng = random.Random(seed)
    end = datetime.fromisoformat(today).date() if today else datetime.now(MSK).date()
    cards = sorted(e.catalog.cards.values(),key=lambda c:c.id)
    priced = [c for c in cards if any(o.available and o.price and o.price<=2500000 for o in c.offers)]
    if not cards:
        raise ValueError("В каталоге нет карточек")
    # Чаще ищут ассортимент с ценой и возможностью покупки.
    popular = rng.sample(priced,min(180,len(priced))) + rng.sample(cards,min(120,len(cards)))
    by_phrase = {}
    for c in popular:
        title = c.title.strip()
        o = next((v for v in c.offers if v.available and v.price),c.offers[0])
        family = o.family_name or title
        section = (o.category_path or [family])[-1]
        for phrase in [title,family,o.sku,distort(family,"typo",c,rng),f"Как выбрать {section.lower()} для организации?"]:
            if phrase and len(phrase)<=250:
                by_phrase.setdefault(phrase,c)
        for word,slang in (("антивирус","антивирь"),("windows","винда"),("office","офис"),("backup","резервилка")):
            if word in title.lower():
                by_phrase.setdefault(slang,c)

    for marker,questions in [
        ("антивирус",["что использовать против вирусов","антивирь для офиса"]),
        ("резервн",["чем сохранить копию базы","резервилка"]),
        ("чертеж",["программа для чертежей"]),
        ("почтов",["чем защитить почту"]),
        ("ноутбук",["какой ноутбук взять в командировку"]),
        ("удаленный доступ",["как подключиться к рабочему компьютеру из дома"]),
    ]:
        target=next((c for c in cards if marker in normalize(" ".join(c.offers[0].category_path))),None)
        if target:
            for phrase in questions:
                by_phrase.setdefault(phrase,target)

    @lru_cache(None)
    def lookup(q):
        offers=match(e.catalog,q,limit=None)
        hits=offers[:10]
        return hits,len(offers),describe(e,q,hits)

    good,miss,commercial=[],[],[]
    for q,c in by_phrase.items():
        hits,_,_=lookup(q)
        found=[o for o in hits[:5] if o.card_id==c.id]
        (good if found else miss).append(q)
        if any(o.available and o.price and o.price<=2500000 for o in found):
            commercial.append(q)
    if not good:
        raise ValueError("По названиям и артикулам фида обычный поиск не нашёл целевые карточки")
    journal=e.journal
    truth=[]
    tally=Counter()
    # Каждый день имеет свой объём с учётом выходных; общее число равно 45 тысячам.
    days=rng.choices(range(90),weights=[.7 if (end-timedelta(days=d)).weekday()>=5 else 1 for d in range(90)],k=45000)
    with journal.transaction() as db:
        db.execute("DELETE FROM events WHERE search_id IN (SELECT search_id FROM searches WHERE search_id GLOB 's_mock_*')")
        db.execute("DELETE FROM searches WHERE search_id GLOB 's_mock_*'")
        db.execute("INSERT OR REPLACE INTO kv VALUES ('settings:history_source','mock',?)",(time(),))
        db.execute("INSERT OR REPLACE INTO kv VALUES ('settings:active_replay','',?)",(time(),))
        retry=None
        for i,day in enumerate(days):
            ident=f"s_mock_feed_{i}"
            if retry:
                q,sid,ts,segment=retry
                retry=None
            else:
                roll=rng.random()
                q=rng.choice(miss if roll<.35 and miss else commercial if roll<.80 and commercial else good)
                sid=f"feed_{i}"
                segment=rng.choices(["smb","mid","enterprise","gov","edu"],[40,30,15,10,5])[0]
                ts=datetime.combine(end-timedelta(days=day),datetime.min.time(),MSK).timestamp()+rng.randrange(8*3600,21*3600)
            c=by_phrase[q]
            hits,count,(intent,reason,category,_,filters,entities)=lookup(q)
            ids=[o.card_id for o in hits]
            journal.insert("searches",dict(search_id=ident,ts=ts,session_id=sid,client_id="guest",segment=segment,
                source="history",engine="legacy",mode="naive",q_raw=q,q_norm=normalize(q),q_corrected=normalize(q),
                intent=intent,category_ctx=category or c.category,n_cards=count,zero=int(not count),fail_reason=reason,
                top_cards_json=dump(ids),blocks_json=dump(["products"] if hits else []),filters_json=filters,entities_json=entities))
            truth.append(dump(dict(search_id=ident,q=q,target_card=c.id,target_category=c.category)))
            def event(kind,**kw):
                journal.event(ts+{"impression":1,"click":8,"cart":22,"order":45,"exit":16,"lead":33,"reformulate":17}[kind],
                              dict(event_id=ident+"_"+kind,search_id=ident,session_id=sid,type=kind,**kw))
            if hits:
                event("impression",payload={"cards":ids[:5]})
            targets=[(p,o) for p,o in enumerate(hits[:5],1) if o.card_id==c.id]
            if not targets:
                tally["failed"]+=1
                if rng.random()<.40:
                    event("exit")
                    tally["exits_after_failure"]+=1
                elif i+1<len(days):
                    follow=c.title if c.title in by_phrase and c.title!=q else rng.choice(good)
                    event("reformulate",payload={"to":follow})
                    retry=(follow,sid,ts+30,segment)
            elif rng.random()<.70:
                p,o=next(((p,o) for p,o in targets if o.available and o.price),targets[0])
                fields=dict(offer_id=o.offer_id,card_id=o.card_id,position=p)
                event("click",**fields)
                if o.available and o.price and o.price<=2500000 and rng.random()<.26:
                    qty=min(rng.choice([1,1,2,5]),int(2500000/o.price))
                    event("cart",qty=qty,**fields)
                    if rng.random()<.64:
                        tally["orders"]+=1
                        event("order",qty=qty,value=round(qty*o.price,2),margin_value=round(qty*o.price*o.margin,2),**fields)
                elif o.price_on_request and rng.random()<.14:
                    event("lead",**fields)
        save_mock(db,Path(journal.path).parent,truth,seed,end,model="feed")
    return dict(author="AiXenix",note=NOTE,searches=len(truth),unique=len(by_phrase),**tally)
