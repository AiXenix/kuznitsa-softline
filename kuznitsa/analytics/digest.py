from collections import Counter
from .kpi import report


def digest(j,role=None):
    kpi=report(j)
    t=kpi["totals"]
    counts=Counter({r["role"]:r["n"] for r in j.rows("SELECT json_extract(body,'$.role') role,count(*) n FROM insights WHERE status='new' GROUP BY role")})
    texts=dict(customer=f"Из {t['searches']:,} поисков {100*(1-t['zero_rate']):.1f}% вернули результаты.",
        ecom_manager=f"В заказ перешли {100*t['conversion']:.2f}% поисков. Первые три позиции получили клики в {100*t['ctr_top3']:.1f}% поисков.",
        product_manager=f"В журнале {len(kpi['slices'].get('category',[]))} групп категорий. Предложений по спросу к рассмотрению · {counts['product_manager']}.",
        content_manager=f"Пустая выдача в {100*t['zero_rate']:.1f}% поисков. Заявок на улучшение контента и словаря к рассмотрению · {counts['content_manager']}.",
        head_ecom=f"Заказы из поиска принесли {t['revenue_rub']:,.0f} ₽. Осторожная оценка потерь · {kpi['lost_orders']['conservative_rub']:,} ₽.")
    if role and role not in texts:
        raise ValueError("Неизвестная роль")
    return dict(items=[dict(role=k,text=v.replace(","," ")) for k,v in texts.items() if role in (None,k)])


