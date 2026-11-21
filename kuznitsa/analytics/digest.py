from .kpi import report


def digest(j,role=None):
    if role is not None and role not in ("customer","ecom_manager","head_ecom","content_manager","product_manager"):
        raise ValueError("Неизвестная роль")
    kpi=report(j)
    totals=kpi["totals"]
    scope=kpi["scope"]["label"]
    def fact(text,href):
        return dict(text=text.replace(","," "),href=href)
    zero=fact(f"Пустая выдача в {totals['zero_rate']:.1%} поисков. Разберите самые частые фразы без ответа.","/api/admin/queries?kind=zero")
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
    options=dict(customer=[zero,clicks,categories],ecom_manager=[orders,clicks,zero],head_ecom=[revenue,loss,orders],
                 content_manager=[zero,clicks,loss],product_manager=[categories,loss,zero])
    items=[]
    for who,findings in options.items():
        if role and role!=who:
            continue
        import json
        choice=j.rows("""SELECT body FROM insights WHERE status='new' AND json_extract(body,'$.role')=?
            ORDER BY json_extract(body,'$.impact.conservative_rub') DESC,id LIMIT 1""",(who,))
        if choice:
            item=json.loads(choice[0]["body"])
            ident=next(iter(item["evidence"].get("search_ids",{}).values()),None)
            findings.append(fact(f"{item['title']}. Основание · {item['evidence']['sessions_30d']} сессий за окно предложения.",
                                 "/inspect/"+ident if ident else "/api/admin/insights?role="+who))
        items.append(dict(role=who,scope=kpi["scope"],findings=findings,text=scope+". "+" ".join(v["text"] for v in findings)))
    return dict(items=items)
