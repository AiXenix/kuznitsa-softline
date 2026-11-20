import random
from collections import defaultdict
from kuznitsa.schema import Client

DEMOS = [
    ("guest","Гость","smb"),("smb_trade","Торговая компания","smb"),
    ("gov_clinic","Государственная клиника","gov"),("edu_university","Университет","edu"),
    ("ent_factory","Промышленное предприятие","enterprise"),("it_company","ИТ-компания","mid"),
    ("design_bureau","Проектное бюро","mid"),("accounting_firm","Бухгалтерское бюро","smb")]


def clients(offers, seed):
    rng = random.Random(seed)
    choices = defaultdict(list)
    for o in offers:
        if o.lic.action=="new" and o.available and o.price:
            choices[o.category_id].append(o)
    security = sorted(choices["endpoint_security"],key=lambda o:(o.vendor_id!="kaspersky",o.offer_id))
    for i in range(200):
        ident,title,segment = DEMOS[i] if i<len(DEMOS) else (f"client_{i}",f"Организация {i}",rng.choice(["smb","gov","mid","edu","enterprise"]))
        owned, orders = [], []
        if i and offers:
            pool = security if i in (1,2,3) and security else offers
            o = pool[0] if i==1 else rng.choice(pool)
            qty = max(o.lic.qty_min or 1,min(30,o.lic.qty_max or 30))
            owned.append(dict(family_id=o.family_id,edition=o.edition,qty=qty,metric=o.lic.metric,
                              expires_in_days=21 if i==1 else rng.randint(10,270),purchased_days_ago=344,offer_id=o.offer_id))
            orders.append(dict(order_id=f"order_{i}",days_ago=344,items=[dict(offer_id=o.offer_id,qty=qty,price=o.price)]))
        yield Client(client_id=ident,title=title,segment=segment,size_seats=30 if i==1 else rng.randint(20,900),
                     industry=["","trade","healthcare","education","industry","it","design","accounting"][i%8],
                     fleet=dict(os=["linux"] if segment=="gov" else ["windows"],servers=i%17),owned=owned,orders=orders,demo=i<8)


def demo_overrides(path,offers,defaults):
    """Привязать описание профилей к существующим SKU. Пропуски остаются видны в истории."""
    import yaml
    from kuznitsa.text import normalize
    configs = yaml.load(path.read_text(), Loader=yaml.CSafeLoader) if path and path.exists() else {}
    source = {r["id"]:r for r in configs.get("profiles",[])}
    groups = defaultdict(list)
    for o in offers:
        groups[o.family_id].append(o)
    names = {normalize(rows[0].family_name):k for k,rows in groups.items()}
    def resolve(row,audience):
        name=normalize(row.get("product",""))
        fid=row.get("family") or names.get(name)
        if not fid and name:
            fid=next((names[n] for n in sorted(names,key=len,reverse=True) if name.startswith(n+" ")),None)
        qty=row.get("qty") or 1
        options=[o for o in groups.get(fid,[]) if o.lic.action==row.get("action","new") and
                 o.lic.audience in (audience,"business",None) and (o.lic.qty_min or 1)<=qty<=(o.lic.qty_max or qty)]
        return max(options,key=lambda o:(o.lic.audience==audience,o.edition==row.get("edition"),o.available,o.lic.term_months==12,o.popularity),default=None)
    for c in defaults:
        s=source.get(c.client_id)
        if not s:
            yield c
            continue
        for k in ("title","segment","industry","region","fleet","size_seats"):
            if s.get(k) is not None:
                setattr(c,k,s[k])
        aud=c.segment if c.segment in ("gov","edu") else "business"
        c.owned=[]
        for row in s.get("owned",[]):
            o=resolve(row,aud)
            c.owned.append({**row,"family_id":o.family_id if o else row.get("family"),"edition":o.edition if o else row.get("edition"),
                            "offer_id":o.offer_id if o else None})
        c.orders=[]
        for i,order in enumerate(s.get("orders",[])):
            items=[]
            for row in order.get("items",[]):
                o=resolve(row,aud)
                items.append({**row,"offer_id":o.offer_id if o else None,"price":o.price if o else None})
            c.orders.append(dict(order_id=f"{c.client_id}_{i}",days_ago=order["days_ago"],items=items))
        yield c
