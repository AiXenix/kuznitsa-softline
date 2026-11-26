import re
from .kpi import report


def digest(j,role=None):
    if role is not None and role not in ("customer","ecom_manager","head_ecom","content_manager","product_manager"):
        raise ValueError("Неизвестная роль")
    kpi=report(j)
    if kpi.get("data_status")=="incompatible":
        roles=[role] if role else ("head_ecom","ecom_manager","product_manager","content_manager","customer")
        return dict(note=kpi["note"],items=[dict(role=r,scope=kpi["scope"],text=kpi["note"],
                    findings=[dict(text=kpi["note"],href="/api/admin/ingest")]) for r in roles])
    totals=kpi["totals"]
    scope=" ".join(filter(None,[kpi.get("history_note"),kpi["scope_text"]]))
    def fact(text,href):
        return dict(text=re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))"," ",text),href=href)
    rate=f"{totals['zero_rate']*100:.1f}".replace(".",",")
    zero=fact(f"Пустая выдача в {rate} % поисков. Разберите самые частые фразы без ответа.","/api/admin/queries?kind=zero")
    clicks=fact(f"До карточки дошли в {totals['clicked']:,} поисках. Проверьте запросы с низким CTR.","/api/admin/queries?kind=low_ctr")
    orders=fact(f"В истории зарегистрировано заказов · {totals['orders']:,}. Сверьте этапы воронки.","/api/admin/kpi")
    revenue=fact(f"Стоимость зарегистрированных заказов · {totals['revenue_rub']:,.0f} ₽. Сопоставьте с осторожной оценкой потерь.","/api/admin/kpi")
    groups=kpi["slices"]["category"]
    categories=fact(f"Спрос распределён по {len(groups)} группам категорий. Проверьте, где растёт число обращений.","/api/admin/queries?kind=rising")
    loss=fact(f"Осторожная оценка потерь за окно · {kpi['lost_orders']['conservative_rub']:,.0f} ₽. Откройте расчёт по сессиям.","/api/admin/kpi")
    if totals["order_denominator"]<totals["searches"]:
        orders=fact(f"Заказы переданы для {totals['order_denominator']} из {totals['searches']} поисков. Запросите полный отчёт по целям.","/api/admin/ingest")
    if not kpi["lost_orders"].get("available",True):
        loss=fact(f"Суммы заказов переданы для {totals['revenue_denominator']} поисков. Дополните выгрузку перед расчётом потерь.","/api/admin/ingest")
    if totals["searches"] and not totals["revenue_denominator"]:
        revenue=fact("Суммы заказов отсутствуют в выгрузке. Загрузите отчёт с выручкой.","/api/admin/ingest")
    if totals["searches"] and not totals["click_denominator"]:
        clicks=fact("Переходы в карточки отсутствуют в выгрузке. Подключите события кликов для оценки CTR.","/api/admin/ingest")
    options=dict(customer=[zero,clicks,categories],ecom_manager=[orders,clicks,zero],head_ecom=[revenue,loss,orders],
                 content_manager=[zero,clicks,loss],product_manager=[categories,loss,zero])
    if role in (None,"head_ecom"):
        from .upsell_rules import analytics
        cross=analytics(j)["totals"]
        if any(cross.values()):
            options["head_ecom"].append(fact(f"На витрине допродажи показаны {cross['impressions']} раз. "
                f"Кликов — {cross['clicks']}, добавлений в корзину — {cross['carts']}. Проверьте ведущие пары.",
                "/api/admin/upsell/analytics"))
    from .insights import listing
    proposals = listing(j)
    items=[]
    for who,findings in options.items():
        if role and role!=who:
            continue
        item = next((v for v in proposals if v["status"]=="new" and v["role"]==who), None)
        if item:
            ident=next(iter(item["evidence"].get("search_ids",{}).values()),None)
            findings.append(fact(f"{item['title']}. Основание · {item.get('evidence_text') or item['summary']}",
                                 "/inspect/"+ident if ident else "/api/admin/insights?role="+who))
        items.append(dict(role=who,scope=kpi["scope"],findings=findings,text=scope+". "+" ".join(v["text"] for v in findings)))
    return dict(items=items)
