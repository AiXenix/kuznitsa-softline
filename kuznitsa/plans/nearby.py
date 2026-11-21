"""Предлагает доступные варианты, когда исходная лицензия не подходит."""
from kuznitsa.rank.variants import select
from kuznitsa.rank.business import ranked


def alternative_blocks(engine,f,profile,exc,qty,weights,home,office):
    families=f.get("family",[])
    vendors=set(f.get("vendor",[]))
    categories=set(f.get("category",[]))
    linked=[]
    if home and vendors and not families and not categories:
        # У названного бренда могут быть обучение, мониторинг и другие услуги.
        # Область замены определяют его домашние линейки и их связи.
        families=[fid for fid,row in engine.kb.rows["families"].items()
                  if row.get("vendor") in vendors and "home" in row.get("target_audiences",[])]
    for fid in families:
        row=engine.kb.rows["families"].get(fid,{})
        if row.get("vendor"):vendors.add(row["vendor"])
        if row.get("category"):categories.add(row["category"])
        linked.extend(row.get("analogs",[]))
        linked.extend(x["family"] for x in engine.kb.rows["analogs"].get(fid,{}).get("russian_analogs",[]))
    if office:categories.discard("office_suite")
    if "home_antivirus" in categories:categories.add("endpoint_security")
    choices=[]
    for card in engine.catalog.cards.values():
        if card.vendor in exc.get("vendor",[]) or card.category in exc.get("category",[]) or card.family in exc.get("family",[]):continue
        same_vendor=card.vendor in vendors
        same_category=card.category in categories
        if not (same_category or not categories and same_vendor or card.family in linked):continue
        if office and ("home" in card.title.lower() or not same_category):continue
        junior=card.kb.get("max_seats") or 100000
        choices.append(((linked.index(card.family) if card.family in linked else len(linked),not same_vendor,not same_category,junior,-(card.kb.get("popularity") or 0),card.id),card))
    found=[]; seen=set()
    for _,card in sorted(choices,key=lambda x:x[0]):
        if card.family in seen:continue
        criteria={k:v for k,v in f.items() if k in ("registry","certs","platform","price_max","price_min","origin") and not (k=="platform" and v==["server"])}
        option=select(card,profile,{**criteria,"action":"new","audience":"business"},exc,qty)
        if not option or not option[0].available or option[0].kind!="license":continue
        item=ranked(card,option,.7,False,profile,weights,engine.kb)
        item["position"]=len(found)+1
        found.append(dict(card=item,note="Доступная лицензия для организации. Проверьте назначение и условия."))
        seen.add(card.family)
        if len(found)==3:break
    title=next((engine.names["vendor"][v] for v in sorted(v for v in vendors if v) if v in engine.names["vendor"]),"")
    text=("Для организации проверьте право на использование домашней редакции по лицензионному соглашению (EULA). Ниже — коммерческие варианты." if office else
          f"Для домашнего использования {title} в этой подборке магазина для организаций подходящей лицензии нет.".replace("  "," ") if home else
          "Предложения с запрошенным сочетанием условий сейчас нет.")
    blocks=[dict(type="not_in_catalog",title="Условия покупки",text=text,reason="gap")]
    if found:blocks.append(dict(type="analogs",title="Ближайшие варианты для организации",source=dict(title=title,status="unavailable",note=text),items=found))
    return blocks


def faq_link(engine,home):
    for row in engine.kb.rows["faq"].values():
        for q in row.get("questions",[]):
            if ("домашн" in q and "офис" in q if home else "замен" in q and "ушедш" in q):
                return dict(type="answer",title="Вопрос о лицензировании",source="faq:"+row["id"],faq_id=row["id"],
                            text="Подробнее об условиях покупки и использования.",links=[dict(label=q,q=q)])
