import random
from math import log
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
        options=options or groups.get(fid,[])
        return max(options,key=lambda o:(o.edition==row.get("edition"),o.lic.audience==audience,
                                         o.lic.metric==row.get("metric"),o.lic.term_months==row.get("term_months",12),
                                         o.available,-abs(qty-(o.lic.pack or qty)),o.popularity),default=None)
    for product_info in source.values():
        for own in product_info.get("owned",[]):
            if own.get("family") in groups:
                names[normalize(own["product"])]=own["family"]
    for c in defaults:
        s=source.get(c.client_id)
        if not s:
            yield c
            continue
        for k in ("title","segment","industry","region","fleet","size_seats","preferences"):
            if s.get(k) is not None:
                setattr(c,k,s[k])
        aud=c.segment if c.segment in ("gov","edu") else "business"
        c.owned=[]
        for row in s.get("owned",[]):
            o=resolve(row,aud)
            c.owned.append({**row,"family_id":o.family_id if o else row.get("family"),"edition":o.edition if o else row.get("edition"),
                            "card_id":o.card_id if o else None,"offer_id":o.offer_id if o else None})
        c.orders=[]
        for i,order in enumerate(s.get("orders",[])):
            items=[]
            for row in order.get("items",[]):
                own=next((p for p in c.owned if p["product"]==row["product"]),{})
                o=resolve({**own,**row},aud)
                items.append({**row,"offer_id":o.offer_id if o else None,"card_id":o.card_id if o else None,"price":o.price if o else None})
            c.orders.append(dict(order_id=f"{c.client_id}_{i}",days_ago=order["days_ago"],items=items))
        yield c


def configured_clients(spec,offers,seed):
    import yaml
    if not (spec/"clients.yaml").exists():
        yield from demo_overrides(spec/"profiles.yaml",offers,clients(offers,seed))
        return
    data=yaml.load((spec/"clients.yaml").read_text(),Loader=yaml.CSafeLoader)
    demos=yaml.load((spec/"profiles.yaml").read_text(),Loader=yaml.CSafeLoader)["profiles"]
    defaults=(Client(client_id=r["id"],title=r["title"],segment=r.get("segment") or "smb",demo=True) for r in demos)
    yield from demo_overrides(spec/"profiles.yaml",offers,defaults)
    rng=random.Random(seed+data["meta"]["seed_offset"])
    def weighted(weights):
        return rng.choices(list(weights),weights=list(weights.values()))[0]
    def draw(bounds):
        return rng.randint(bounds["min"],bounds["max"])
    pools=defaultdict(list)
    for o in offers:
        if o.available and o.lic.action=="new" and o.price:
            pools[o.category_id].append(o)
    seq=0
    portfolio=data["portfolio_rules"]
    for segment,rule in data["segments"].items():
        for j in range(round(data["meta"]["synthetic_clients_count"]*rule["share"])):
            seq+=1
            ident=f"cli_{seq:04d}"
            industry=weighted(rule["industries"])
            legal=rng.choice(data["company_naming"]["legal_forms"][segment])
            stems=data["company_naming"]["stems_by_industry"]
            title=f"{legal} «{rng.choice(stems.get(industry,stems['default']))} {seq}»"
            sizes=rule["seats"]
            seats=draw(sizes) if sizes["dist"]=="uniform" else min(sizes["max"],max(sizes["min"],round(rng.lognormvariate(log(sizes["median"]),.65))))
            fleet=data["fleet_os_profiles"][weighted(rule["fleet_os_weights"])]
            os_list=fleet["os"] if "os" in fleet else rng.choices(fleet["os_choices"],weights=fleet["probs"])[0]
            cats=portfolio["core_categories_by_segment"][segment]
            candidates=[o for c in cats for o in pools[c] if o.lic.audience in (None,"business",segment,"home" if segment=="individual" else "business")]
            rng.shuffle(candidates)
            chosen=defaultdict(list)
            cohort=j<portfolio["expiring_cohort_target"]["segment_mix_in_cohort"].get(segment,0)
            if cohort:
                candidates.sort(key=lambda o:o.lic.model!="subscription")
            for o in candidates:
                chosen[o.family_id].append(o)
            owned,orders=[],[]
            for n,variants in enumerate(list(chosen.values())[:draw(rule["owned_products_count"])]):
                desired=weighted(portfolio["term_distribution"])
                term=int(desired.split("_")[1][:-1]) if desired.startswith("subscription_") else None
                if cohort and n==0:
                    term=12
                o=max(variants,key=lambda o:(not (cohort and n==0) or o.lic.model=="subscription",
                                              o.lic.term_months==term,
                                              (o.lic.qty_min or 1)<=seats<=(o.lic.qty_max or seats),
                                              o.lic.audience==segment))

                exp=(rng.randint(14,45) if cohort and n==0 else draw(portfolio["expiring_cohort_target"]["other_subscriptions_expires_in_days"])) if o.lic.model=="subscription" else None
                ago=max(1,round((o.lic.term_months or 12)*365/12)-exp) if exp else rng.randint(60,700)
                qty=max(o.lic.qty_min or 1,min(seats,o.lic.qty_max or seats))
                owned.append(dict(family_id=o.family_id,edition=o.edition,metric=o.lic.metric,qty=qty,offer_id=o.offer_id,
                                  card_id=o.card_id,product=o.family_name,purchased_days_ago=ago,expires_in_days=exp))
                orders.append(dict(order_id=f"{ident}_{n}",days_ago=ago,items=[dict(offer_id=o.offer_id,card_id=o.card_id,qty=qty,price=o.price)]))
            region=weighted({r["name"]:r["weight"] for r in data["regions"]})
            yield Client(client_id=ident,title=title,segment=segment,industry=industry,size_seats=seats,region=region,
                         fleet=dict(os=os_list,servers=round(seats*rule["servers_ratio"])),owned=owned,orders=orders,
                         preferences=dict(budget=weighted(rule["budget_weights"]),registry_required=rng.random()<rule["registry_required_prob"],
                                          certs_required=[v for v in weighted(rule["certs_required_probs"]).split("_") if v!="none"]))


def date_client(client,today):
    from datetime import timedelta
    for p in client.owned:
        for key,source,sign in [("expires_at","expires_in_days",1),("purchased_at","purchased_days_ago",-1)]:
            if p.get(source) is not None:
                p[key]=str(today+timedelta(days=sign*p[source]))
    for order in client.orders:
        order["date"]=str(today-timedelta(days=order["days_ago"]))
    return client
