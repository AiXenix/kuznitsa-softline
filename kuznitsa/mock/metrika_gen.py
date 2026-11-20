import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime
from urllib.parse import quote_plus
from .querylog_gen import MSK
from kuznitsa.analytics.store import dump

GOALS={"click":301004,"cart":301005,"lead":301006,"order":301007,"suggest_click":301003}
HEADERS=["Поисковая фраза","Поиски","Визиты","Посетители","Отказы","Глубина просмотра","Время на сайте","Доля пустых выдач",
         "Достижения цели: Поиск на сайте","Достижения цели: Добавление в корзину","Достижения цели: Запрос КП",
         "Достижения цели: Заказ оформлен","Доход (₽)"]


def numeric(key):
    return str(10**18+int.from_bytes(hashlib.blake2b(key.encode(),digest_size=8).digest(),"big")%(9*10**18))


def local(ts):
    return datetime.fromtimestamp(ts,MSK).strftime("%Y-%m-%d %H:%M:%S")


def export(engine,dest):
    dest.mkdir(exist_ok=True,parents=True)
    j=engine.journal
    rng=random.Random(20261130)
    events=defaultdict(list)
    for r in j.rows("SELECT e.* FROM events e JOIN searches s USING(search_id) WHERE s.source='history' ORDER BY e.ts,event_id"):
        events[r["search_id"]].append(r)
    visits=defaultdict(list)
    for r in j.rows("""SELECT search_id,q_raw,n_cards,zero,ts,client_id,segment,session_id,category_ctx,prev_search_id,top_cards_json
                       FROM searches WHERE source='history' ORDER BY ts,search_id"""):
        visits[r["session_id"] or r["search_id"]].append(r)
    phrases=defaultdict(lambda:dict(n=0,visits=set(),clients=set(),bounce=0,depth=0,duration=0,zero=0,cart=0,lead=0,order=0,sales=0))
    watch=10**18
    with (dest/"metrika_visits.jsonl").open("w") as vf,(dest/"metrika_hits.jsonl").open("w") as hf:
        for sid,rows in visits.items():
            first=rows[0]
            client=first["client_id"] or "guest"
            vid=numeric(sid)
            cid=numeric(client if client!="guest" else sid)
            hits=[]
            goals=[]
            orders=[]
            seen=set()
            for r in rows:
                q=r["q_raw"]
                stats=phrases[q]
                seen.add(q)
                stats["n"]+=1
                stats["clients"].add(cid)
                stats["zero"]+=r["zero"]
                ident=r["search_id"]
                stream=events[ident]
                def product(oid,pos):
                    o=engine.catalog.offers_by_id.get(oid)
                    return dict(id=oid,name=o.name if o else oid,brand=o.vendor if o else None,price=o.price if o else None,
                                category=o.category_id if o else None,position=pos,list="Search Results")
                offers=next((json.loads(e["payload_json"] or "{}").get("cards",[]) for e in stream if e["type"]=="impression"),[])
                url="https://demo-store.mock/search?q="+quote_plus(q)
                params=dict(search_id=ident,site_search_query=q,search_category_ctx=r["category_ctx"],search_results_count=r["n_cards"],
                            search_zero=r["zero"],search_engine="legacy",ecommerce=dict(currencyCode="RUB",impressions=[product(o,i) for i,o in enumerate(offers,1)]))
                if r["prev_search_id"]:
                    params["inherited"]={"from_search_id":r["prev_search_id"]}
                hits.append((r["ts"],url,[301001]+([301002] if r["zero"] else []),params,"Поиск · "+q))
                for e in stream:
                    kind=e["type"]
                    if kind=="impression":
                        continue
                    goal=[GOALS[kind]] if kind in GOALS else []
                    params=dict(search_id=ident,event_id=e["event_id"],event_type=kind,payload=json.loads(e["payload_json"] or "{}"))
                    if e["offer_id"]:
                        item=product(e["offer_id"],e["position"])
                        item.update(quantity=e["qty"],card_id=e["card_id"])
                        action={"products":[item]}
                        if kind=="order":
                            action["actionField"]=dict(id=e["event_id"],revenue=e["value"])
                            orders.append((e["event_id"],e["value"] or 0))
                            stats["sales"]+=e["value"] or 0
                        params.update(ecommerce={"currencyCode":"RUB",{"cart":"add","order":"purchase"}.get(kind,kind):action},margin_value=e["margin_value"])
                    if kind in ("cart","order","lead"):
                        stats[kind]+=1
                    event_url={"click":"/product/"+str(e["card_id"]),"cart":"/cart","order":"/checkout/success"}.get(kind,"/events/"+kind)
                    hits.append((e["ts"],"https://demo-store.mock"+event_url,goal,params,kind))
            hits.sort(key=lambda x:x[0])
            duration=int(hits[-1][0]-hits[0][0])
            referer=""
            for ts,url,g,p,title in hits:
                watch+=1
                goals+=g
                hit=dict(watchID=str(watch),visitID=vid,clientID=cid,dateTime=local(ts),URL=url,referer=referer,title=title,goalsID=g,params=p)
                hf.write(dump({"ym:pv:"+k:v for k,v in hit.items()})+"\n")
                referer=url
            bounce=int(301004 not in goals and duration<15)
            profile=engine.clients.get(client)
            visit=dict(visitID=vid,clientID=cid,dateTime=local(hits[0][0]),startURL=hits[0][1],endURL=referer,bounce=bounce,
                pageViews=len(hits),visitDuration=duration,trafficSource=rng.choices(["organic","direct","ad","email","referral"],[42,31,15,7,5])[0],
                regionCity=profile.region if profile else "",deviceCategory=rng.choices(["desktop","mobile","tablet"],[86,12,2])[0],
                goalsID=goals,purchaseID=[x for x,_ in orders],purchaseRevenue=[v for _,v in orders],purchaseCurrency=["RUB"]*len(orders),
                parsedParamsKey1=["client_id","segment","industry"],parsedParamsKey2=[client,first["segment"],profile.industry if profile else "unknown"])
            vf.write(dump({"ym:s:"+k:v for k,v in visit.items()})+"\n")
            for q in seen:
                s=phrases[q]
                s["visits"].add(vid)
                s["depth"]+=len(hits)
                s["duration"]+=duration
                s["bounce"]+=bounce
    with (dest/"metrika_search_phrases.csv").open("w",encoding="utf-8-sig",newline="") as out:
        writer=csv.writer(out,delimiter=";")
        writer.writerow(HEADERS)
        for q,s in sorted(phrases.items()):
            v=len(s["visits"])
            writer.writerow([q.replace("\n"," | "),s["n"],v,len(s["clients"]),s["bounce"]/v,s["depth"]/v,round(s["duration"]/v),
                             s["zero"]/s["n"],s["n"],s["cart"],s["lead"],s["order"],round(s["sales"],2)])
    return dict(directory=str(dest),phrases=len(phrases),visits=len(visits),hits=watch-10**18)
