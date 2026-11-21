"""Build a quotation from the journal snapshot shown to the buyer."""
import csv
import re
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from kuznitsa.mock.naming import ACTION, AUD, quantity_word
from kuznitsa.schema import Request
from pydantic import Field


class SpecificationRequest(Request):
    # Each of the 200 rows is validated separately before joining.
    q: str = Field(max_length=200*1501)


HEADERS = ["№", "Запрос клиента", "Найденный товар", "Артикул", "Вендор", "Условия лицензии",
           "Количество", "Цена, ₽", "Сумма, ₽", "Реестр российского ПО", "Примечание"]
DISCLAIMER = "Расчёт предварительный, цены демонстрационные."


def positions(detail):
    query = detail["query"]["raw"]
    qty = (detail["understood"].get("qty") or {}).get("value")
    for kind in ("spec", "kit"):
        block = next((b for b in detail["blocks"] if b["type"] == kind), None)
        if block:
            for line in block["lines"] if kind == "spec" else block["slots"]:
                yield (line.get("raw") or line.get("title"), line.get("card"),
                       line.get("qty") if kind == "spec" else block.get("seats"), line)
            return
    seen=set()
    for block in detail["blocks"]:
        for item in block.get("columns",[]) or block.get("items",[]):
            if not isinstance(item,dict):
                continue
            card=item.get("card") or item
            ident=card.get("card_id")
            if not ident or not card.get("offer") or ident in seen:
                continue
            seen.add(ident)
            note={"status":"substitute","note":item.get("note","")} if block["type"]=="analogs" else {}
            yield query,card,qty,note
            if len(seen)==10:
                return
    if not seen:
        yield query, None, qty, {}


def license_terms(offer):
    model={"subscription":"подписка","perpetual":"бессрочная лицензия"}.get(offer.get("model"))
    terms=[ACTION.get(offer.get("action")),model,AUD.get(offer.get("audience"))]
    if offer.get("term_months"):
        terms.append(f"{offer['term_months']} мес.")
    pack,lo,hi=(offer.get(k) for k in ("pack","qty_min","qty_max"))
    metric=offer.get("metric")
    if pack:
        terms.append(f"пакет {pack} {quantity_word(metric,pack)}")
    elif lo or hi:
        band=f"{lo}–{hi}" if lo and hi else f"от {lo}" if lo else f"до {hi}"
        terms.append(f"ступень {band}, единица — {quantity_word(metric,1)}")
    elif metric:
        terms.append(quantity_word(metric,1))
    return ", ".join(filter(None,terms)) or offer.get("name")


def quote_rows(detail):
    rows, missing = [], []
    for i, (q, card, qty, line) in enumerate(positions(detail), 1):
        card = card or {}
        offer = card.get("offer") or {}
        calc = card.get("calc") or {}
        notes = [line["note"]] if line.get("note") else []
        if not offer:
            suggestions = ", ".join(c.get("title","") for c in line.get("alternatives", []))
            missing.append([i, q, suggestions or "Уточнить название или артикул"])
            notes.append("Требуется уточнение")
        elif offer.get("price_on_request") or offer.get("price") is None:
            notes.append("Цена по запросу")
        if offer.get("available") is False:
            notes.append("Поставка требует подтверждения")
        if card.get("qty_out_of_range"):
            notes.append("Количество вне ступени лицензирования")
        if line.get("status") in ("alternative","substitute","replaced"):
            notes.append("Предложена замена")
        if calc.get("text"):
            notes.append(calc["text"])
        registry = next((b["label"] for b in card.get("badges",[]) if b["kind"]=="registry"),"Нет сведений")
        if isinstance(offer.get("registry"),bool):
            registry="Да" if offer["registry"] else "Нет"
        rows.append([i,q,card.get("title"),offer.get("sku"),(card.get("vendor") or {}).get("name"),
                     license_terms(offer),qty,calc.get("unit_price",offer.get("price")),line.get("total",calc.get("total")),
                     registry,". ".join(notes)])
    return rows,missing


def clean(value):
    return ILLEGAL_CHARACTERS_RE.sub("",value)[:32767] if isinstance(value,str) else value


def make_export(engine, ident, fmt):
    detail = engine.journal.detail(ident)
    day = datetime.fromtimestamp(detail["ts"],timezone.utc).date()
    archive_note=None
    if detail.get("archived_summary"):
        profile=detail.get("client_id") or "guest"
        if profile not in engine.clients:
            archive_note=f"Профиль {profile} отсутствует. Для архивного запроса применены гостевые условия."
            profile="guest"
        detail = engine.search(SpecificationRequest(q=detail["q_raw"],profile_id=profile,
                    category=detail.get("category_ctx"),mode=detail["mode"],source="eval",context="off"))
    rows, missing = quote_rows(detail)
    meta = [["Клиент",detail["profile"]["title"]],["Дата расчёта",day.isoformat()],
            ["Действительно по",(day+timedelta(days=14)).isoformat()]]
    if archive_note:
        meta[0].append(archive_note)
    body = meta+[HEADERS]+rows
    if fmt=="csv":
        out=StringIO(newline="")
        writer=csv.writer(out,delimiter=";")
        amounts=[r[8] for r in rows if r[8] is not None]
        table=body+[["Итого по рассчитанным позициям",sum(amounts) if amounts else None]]
        if missing:
            table+=[["Не найдено"],["№","Запрос клиента","Что предложено взамен"],*missing]
        for row in table+[[DISCLAIMER]]:
            writer.writerow(["'"+v if isinstance(v,str) and v.lstrip().startswith(("=","+","-","@")) else v for v in map(clean,row)])
        content=out.getvalue().encode("utf-8-sig")
    else:
        wb=Workbook()
        ws=wb.active
        ws.title="Коммерческое предложение"
        unresolved=wb.create_sheet("Не найдено")
        for sheet,table,header,widths in [(ws,body,4,[6,42,39,23,22,46,14,17,18,24,44]),
                                         (unresolved,[["№","Запрос клиента","Что предложено взамен"]]+missing,1,[6,55,48])]:
            for row in table:
                sheet.append(list(map(clean,row)))
                for cell in sheet[sheet.max_row]:
                    if isinstance(cell.value,str):
                        cell.data_type="s"
                        cell.alignment=Alignment(wrap_text=True,vertical="top")
            sheet.freeze_panes=f"B{header+1}"
            for cell in sheet[header]:
                cell.font=Font(bold=True,color="FFFFFF")
                cell.fill=PatternFill("solid",fgColor="27475B")
            for i,width in enumerate(widths,1):
                sheet.column_dimensions[get_column_letter(i)].width=width
        end=ws.max_row
        ws.append(["Итого по рассчитанным позициям"]+[None]*7+[f'=IF(COUNT(I5:I{end}),SUM(I5:I{end}),"")' if end>=5 else None])
        for row in ws.iter_rows(min_row=5,min_col=8,max_col=9):
            for cell in row:
                cell.number_format='#,##0.00 "₽"'
        ws.append([DISCLAIMER])
        out=BytesIO()
        wb.save(out)
        content=out.getvalue()
    prefix=re.sub(r"[^A-Za-z0-9_-]","_",ident[:6])
    return content,f"KP-{day:%Y%m%d}-{prefix}.{fmt}"
