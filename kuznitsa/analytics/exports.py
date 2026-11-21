"""Отчёт для передачи коллеге. Источники те же, что у панелей консоли."""
from io import BytesIO
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from . import digest,gaps,kpi,insights

ROLE_NAMES={"head_ecom":"Руководитель e-com","content_manager":"Контент-менеджер","product_manager":"Продукт-менеджер",
            "ecom_manager":"Менеджер e-com","customer":"Покупатель"}


def sections(engine,role):
    j=engine.journal
    snapshot=kpi.report(j)
    yield "Период",[("Источник",snapshot["scope_text"])]
    if snapshot.get("data_status")=="incompatible":
        yield "Что сделать сегодня",[(snapshot["note"],)]
        return
    yield "Показатели",[(t["label"],t["value"] if t["value"] is not None else "Нет данных",t["unit"]) for t in snapshot["tiles"]]
    if role=="head_ecom":
        comparison = [("Показатель", "До", "После", "Ед.", "Изменение", "Выборка", "Метод")]
        for pair in snapshot["pairs"]:
            if pair["before"] is None or pair["after"] is None:
                continue
            rate = pair["unit"] == "rate"
            scale = 100 if rate else 1
            comparison.append((pair["label"], round(scale * pair["before"], 2), round(scale * pair["after"], 2),
                               "%" if rate else "₽", pair["delta_text"], pair["scope_text"], pair["note"]))
        if len(comparison) > 1:
            yield "До и после", comparison
        loss=snapshot["lost_orders"]
        rows=[("Осторожная оценка потерь",loss["conservative_rub"],"₽"),("Базовая оценка потерь",loss["expected_rub"],"₽"),("Метод",loss["formula_note"])]
        pair=next((p for p in snapshot["pairs"] if p["key"]=="lost_orders_rub"),{})
        if pair.get("before") is not None and loss.get("available",True):
            rows.append(("Прогноз возврата · снижение потерь",pair["before"]-pair["after"],"₽",pair["note"]))
        yield "Онлайн-заказы",rows if loss.get("available",True) else [("Для оценки нужны суммы заказов",)]
    if role=="ecom_manager":
        yield "Воронка", [(step["label"], step["count"]) for step in snapshot["funnel"]]
        if snapshot.get("funnel_daily"):
            from .goals import STAGES
            rows = [("Дата", "Этап", "Метрика", "Журнал", "Принято", "Источник")]
            for day in snapshot["funnel_daily"]:
                for key, stage in day["stages"].items():
                    rows.append((day["day"], STAGES[key][1], stage["metrika"], stage["journal"],
                                 stage["count"], "Журнал" if stage["source"]=="journal" else "Метрика"))
            yield "Цели по дням", rows
    if role=="content_manager":
        report=gaps.report(engine)
        yield "Спрос вне каталога",[(i["title"],i["searches"],"поисков") for i in report["items"]]
        labels=dict(platforms="Совместимость с ОС",registry="Сведения о реестре",qty_range="Диапазоны лицензирования",
                    description="Описание",price="Цена")
        rows = []
        for card in report["card_defects"]:
            demand = (card["impressions"], "показов") if card["impressions"] is not None else (
                card.get("clicked_searches", 0), "поисков с кликом · показы не переданы")
            rows.append((card["title"], ", ".join(labels.get(k,k) for k in card["fields"]), *demand))
        yield "Исправить карточки", rows
    if role=="product_manager":
        from .dashboard import query_rows
        yield "Частые запросы",[(i["q"],i["count"],"поисков") for i in query_rows(j,"top")[:20]]
        yield "Рост за 30 дней",[(i["q"],i["previous"],i["recent"],"прошлое и текущее окно") for i in query_rows(j,"rising")[:20]]
    yield "Что сделать сегодня",[(v["text"],v["href"]) for v in digest.digest(j,role)["items"][0]["findings"]]
    yield "Предложения агента",[(i["title"],i.get("evidence_text",i["summary"]),i.get("impact_text",""),i["impact"]["formula_note"])
        for i in insights.listing(j) if i["role"]==role and i["status"]=="new"]


def display(value):
    if isinstance(value,int):
        return f"{value:,}".replace(","," ")
    if isinstance(value,float):
        return f"{value:,.2f}".replace(","," ").replace(".",",").removesuffix(",00")
    return str(value).replace("\n"," ")


def export(engine,role,fmt):
    from fastapi.responses import Response
    title="Кузница Softline · "+ROLE_NAMES[role]
    if fmt=="md":
        lines=["# "+title,"","AiXenix",""]
        for section,rows in sections(engine,role):
            lines.extend(["## "+section,""])
            for row in rows:
                lines.append("- "+" · ".join(display(v) for v in row if v is not None))
            if not rows:
                lines.append("За период данных нет.")
            lines.append("")
        body="\n".join(lines).encode()
        mime="text/markdown"
    else:
        book=Workbook()
        book.remove(book.active)
        book.properties.creator="AiXenix"
        book.properties.title=title
        for section,rows in sections(engine,role):
            sheet=book.create_sheet(section)
            sheet.append([section])
            widths={}
            for number, row in enumerate(rows, start=2):
                sheet.append(row)
                for index in range(1, len(row) + 1):
                    cell = sheet.cell(number, index)
                    if isinstance(cell.value,str):
                        cell.data_type="s"
                    widths[cell.column]=max(widths.get(cell.column,17),len(str(cell.value or ""))+2)
            for col,width in widths.items():
                sheet.column_dimensions[get_column_letter(col)].width=min(95,width)
        buf=BytesIO()
        book.save(buf)
        body=buf.getvalue()
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(body,media_type=mime,headers={"Content-Disposition":f'attachment; filename="AiXenix-{role}.{fmt}"'})
