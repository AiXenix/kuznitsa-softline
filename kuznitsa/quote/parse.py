"""Read a procurement spreadsheet, retaining supplier row numbers for diagnostics."""
import csv
import re
from io import BytesIO,StringIO
from pathlib import Path
from zipfile import BadZipFile,ZipFile

from lxml import etree
from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from openpyxl.utils.exceptions import InvalidFileException
from kuznitsa.ingest.mapping import field_for
from kuznitsa.ingest.nameparse import normalize

LIMIT=2*1024*1024
UNITS=r"шт\.?|pcs|seats?|пк|мест\w*|лиц\.?|лицензи\w*|users?|устройств\w*|ядер|core"
SUFFIX=re.compile(rf"(?:\s+[-—–x×]\s*|\s+)(\d+)\s*({UNITS})\.?\s*$",re.I)
LABELS={"title":"номенклатура|продукция|позиция|item|item description|product title|product description|item name|description",
        "qty":"количество|кол во|кол|qty|quantity|count|количество единиц",
        "unit":"ед изм|ед|единица|единица измерения|unit|uom|units"}


class FileError(ValueError):
    def __init__(self,status,code,message):
        super().__init__(message)
        self.status,self.code=status,code


def column(text):
    key=normalize(text)
    for k,values in LABELS.items():
        if key in values.split("|"):
            return k
    field=field_for(text)
    return {"name":"title","sku":"sku"}.get(field)


def sheets(data):
    # Bound expanded XML and the rectangular grids openpyxl can allocate.
    with ZipFile(BytesIO(data)) as archive:
        if sum(i.file_size for i in archive.infolist())>32*1024*1024:
            raise FileError(413,"file_too_large","После распаковки таблица слишком велика.")
        for item in archive.namelist():
            if item.startswith("xl/worksheets/") and item.endswith(".xml"):
                with archive.open(item) as stream:
                    maxcol=maxrow=0
                    for _,node in etree.iterparse(stream,events=("end",),tag=("{*}dimension","{*}mergeCell","{*}c"),resolve_entities=False,no_network=True):
                        ref=node.get("ref") or node.get("r")
                        if ref:
                            _,_,c,r=range_boundaries(ref)
                            maxcol,maxrow=max(maxcol,c or 1),max(maxrow,r or 1)
                            if maxrow*maxcol>400000 or maxcol>512:
                                raise FileError(413,"file_too_large","Диапазон ячеек слишком велик.")
                        node.clear()
    wb=load_workbook(BytesIO(data),data_only=True)
    try:
        for ws in wb:
            merged={}
            for area in ws.merged_cells.ranges:
                value=ws.cell(area.min_row,area.min_col).value
                merged.update(dict.fromkeys(area.cells,value))
            yield [[merged.get((i,j),v) for j,v in enumerate(row,1)] for i,row in enumerate(ws.values,1)]
    finally:
        wb.close()


def table(rows):
    rows=[[str(v).strip() if v is not None else "" for v in row] for row in rows]
    if not rows:
        return
    idx=max(range(min(len(rows),50)),key=lambda i:len({column(v) for v in rows[i]}-{None}))
    header=rows[idx]
    fields={column(v):j for j,v in enumerate(header) if column(v)}
    start=idx+1 if fields else 0
    if not fields:
        idx=0
        # Text-only supplier headings followed by numeric data.
        if len(rows)>1 and any(v.isdigit() for v in rows[1]) and not any(v.isdigit() for v in rows[0]):
            start=1
    header=rows[idx] if start else []
    sample=rows[start:start+25]
    numbers={j for j,h in enumerate(header) if h=="№" or normalize(h) in {"no","номер","п п","номер п п"}}
    for j in range(max(map(len,sample),default=0)):
        vals=[r[j] for r in sample if j<len(r) and r[j]]
        if j in fields.values() or j in numbers or not vals:
            continue
        checks=[("unit",lambda s:re.fullmatch(UNITS,s,re.I)),("sku",lambda s:re.fullmatch(r"(?=.*\d)(?=.*[A-Za-z-])[A-Za-z0-9./-]{5,}|\d{12,14}",s)),
                ("qty",str.isdigit)]
        for key,test in checks:
            if key not in fields and sum(bool(test(s)) for s in vals)>=len(vals)*.8:
                fields[key]=j
                break
    if "title" not in fields:
        unused=[j for j in range(max(map(len,sample),default=0)) if j not in fields.values() and j not in numbers]
        if unused:
            fields["title"]=max(unused,key=lambda j:sum(len(r[j]) for r in sample if j<len(r)))
    labels={k:(header[j] if j<len(header) else None) for k,j in fields.items()}
    for i,row in enumerate(rows[start:],start+1):
        yield i,{k:row[j] for k,j in fields.items() if j<len(row)},labels


def parse(data,name):
    ext=Path(name).suffix.lower().lstrip(".")
    if ext not in {"xlsx","txt","tsv","csv"}:
        raise FileError(415,"file_unsupported","Поддерживаются файлы XLSX, CSV, TSV и TXT.")
    if not data.strip():
        raise FileError(400,"file_empty","Файл пуст.")
    if ext=="xlsx":
        batches=sheets(data)
    else:
        try:
            text=data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text=data.decode("cp1251",errors="replace")
        if ext=="txt":
            batches=None
        else:
            try:
                delimiter=csv.Sniffer().sniff(text[:8192],delimiters=";,\t").delimiter
            except csv.Error:
                delimiter=max("\t;,",key=lambda d:sum(d in s for s in text.splitlines()[:30]))
            csv.field_size_limit(max(csv.field_size_limit(),LIMIT))
            batches=[list(csv.reader(StringIO(text),delimiter=delimiter))]
    info=dict(name=Path(name).name,kind=ext,rows_total=0,positions=0,columns=dict.fromkeys(("title","qty","sku","unit")),skipped=[])
    if batches is None:
        def records():
            for i,line in enumerate(text.splitlines(),1):
                m=SUFFIX.search(line)
                yield i,dict(title=line[:m.start()] if m else line,qty=m[1] if m else "1",unit=m[2] if m else ""),{}
    else:
        def records():
            for batch in batches:
                yield from table(batch)
    positions=[]
    try:
        for num,row,labels in records():
            info["columns"].update(labels)
            info["rows_total"]+=1
            title=re.sub(r"[\r\n;]+"," ",row.get("title","")).strip(" \t•")
            reason=None
            qty=row.get("qty","1") or "1"
            if ext=="txt":
                title=re.sub(r"^(?:\d+[.)]|[-•])\s+","",title)
            if not title:
                reason="Пустое название"
            elif ext=="txt" and re.match(r"^(?:здравствуйте|добрый (?:день|вечер)|прошу (?:выставить|подобрать)|с уважением)\b",title,re.I):
                reason="Сопроводительный текст письма"
            elif re.fullmatch(r"(?:всего|итого|(?:grand )?total)(?:\s+(?:по таблице|позиций|по заявке|по документу|к оплате|amount))?[:. ]*",title,re.I):
                reason="Строка итога"
            elif not re.fullmatch(r"[1-9]\d{0,8}(?:[.,]0+)?",qty):
                reason="Некорректное количество"
            elif len(positions)>=200:
                reason="Превышен предел 200 позиций"
            else:
                amount=int(re.split(r"[.,]",qty)[0])
                sku=re.sub(r"[\r\n;]+"," ",row.get("sku","")).strip()
                query=" ".join(filter(None,[title,sku,"—",str(amount),"шт"]))
                if len(query)>1500:
                    reason="Слишком длинное название"
                else:
                    positions.append(dict(query=query,title=title,sku=sku,qty=amount,unit=row.get("unit","")))
            if reason:
                info["skipped"].append(dict(row=num,reason=reason))
    except FileError:
        raise
    except (BadZipFile,InvalidFileException,IndexError,KeyError,ValueError,TypeError,etree.XMLSyntaxError,OSError) as exc:
        raise FileError(400,"no_positions","Не удалось прочитать таблицу спецификации.") from exc
    if not positions:
        raise FileError(400,"no_positions","В файле нет позиций с названием и количеством.")
    info["positions"]=len(positions)
    return positions,info
