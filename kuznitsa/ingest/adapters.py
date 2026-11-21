"""Yield named tables of (source row number, dict or None for a broken row)."""
import csv
import json
import re
from collections import Counter
from itertools import chain, islice
from pathlib import Path
from zipfile import ZipFile
from openpyxl.utils.cell import column_index_from_string, range_boundaries
from .ut_tables import TOTAL,hierarchy,price_types
from lxml import etree
from openpyxl import load_workbook

from .mapping import field_for,retail_header


def encoding(path):
    with path.open("rb") as f:
        import codecs
        try:
            decoder = codecs.getincrementaldecoder("utf-8-sig")()
            for block in iter(lambda:f.read(262144), b""):
                decoder.decode(block)
            decoder.decode(b"",final=True)
            return "utf-8-sig"
        except UnicodeDecodeError:
            return "cp1251"


def delimiter_for(sample):
    try:
        guessed=csv.Sniffer().sniff(sample).delimiter
        if not guessed.isalnum() and (guessed.strip() or guessed=="\t"):
            return guessed
    except csv.Error:
        pass
    # Sniffer considers ASCII only and struggles with ragged price lists.
    lines=[line for line in sample.splitlines()[:25] if line.strip()]
    candidates=set("\t;,|")
    for line in lines[:3]:
        candidates.update(re.findall(r"[^\w\s\"']",line))
    def score(c):
        widths=Counter(line.count(c) for line in lines if c in line)
        return (sum(widths.values()),max(widths.values(),default=0),c in "\t;,|",c)
    return max(candidates,key=score)


def csv_rows(stream, delimiter):
    # Keep just the lines consumed by the current logical record. A missing
    # closing quote can otherwise absorb every remaining product up to EOF.
    consumed=[]
    def lines():
        for line in stream:
            consumed.append(line)
            yield line
    reader=csv.reader(lines(),delimiter=delimiter,strict=True)
    while True:
        consumed.clear()
        try:
            row=next(reader)
        except StopIteration:
            return
        except csv.Error:
            yield None
            for line in consumed[1:]:
                try:
                    yield next(csv.reader([line],delimiter=delimiter,strict=True))
                except csv.Error:
                    yield None
        else:
            yield row


def spreadsheet(rows, explicit, layout=None, sheet=""):
    prefix=list(islice(rows,50))
    explicit_headers=set(explicit.values())
    def recognized(h):
        return field_for(h) or (h if h in explicit_headers else None)
    def score(row):
        return len({key for h in (row or ()) if h is not None and (key:=recognized(str(h).strip()))})
    if not prefix:
        return
    idx=max(range(len(prefix)),key=lambda i:score(prefix[i]))
    unit_row=re.compile(r"руб[.]?|₽|шт[.]?|ед[.]?|usd|rub|eur|%|мес[.]?|дн[.]?",re.I)
    def tier(line):
        cells=[str(v).strip() for v in line or () if v is not None and str(v).strip()]
        return cells and (any(retail_header(v) for v in cells) and all(isinstance(v,str) for v in line if v is not None) or
                all(unit_row.fullmatch(v) for v in cells) or
                score(cells)>=2 and all(recognized(v) or unit_row.fullmatch(v) for v in cells))
    start=idx+1
    while start<min(idx+4,len(prefix)) and tier(prefix[start]):
        start+=1
    layers=[line for line in prefix[max(0,start-4):start] if line]
    header=[]
    for j in range(len(prefix[idx] or ())):
        parts=list(dict.fromkeys(str(line[j]).strip() for line in layers if j<len(line) and line[j] not in ("",None)))
        candidates=[" ".join(parts[-n:]) for n in (2,3) if len(parts)>=n]
        candidates+=list(reversed(parts))
        label=next((v for v in candidates if recognized(v)),None)
        if label and field_for(label)=="prices":
            # A merged “Виды цен” heading belongs to all columns underneath it.
            leaf=next((v for v in reversed(parts) if not unit_row.fullmatch(v)),label)
            if leaf!=label:
                label=leaf
        header.append(label or next((v for v in reversed(parts) if not unit_row.fullmatch(v)),""))
    # Retain the leaf labels of unknown columns, even underneath a merged group.
    for j,label in enumerate(header):
        if header.count(label)>1:
            leaf=(prefix[idx] or [])[j]
            if leaf and str(leaf)!=label:
                header[j]=str(leaf)
    records=sheet_records(rows,prefix,start,header,score,layout,sheet,explicit)
    if layout is None:
        yield from records
    else:
        yield from hierarchy(records,header,explicit,layout,sheet)


def sheet_records(rows,prefix,start,header,score,layout,sheet,explicit):
    retail,alternatives=price_types(header,prefix[start:],sheet,explicit)
    name_idx=next((i for i,h in enumerate(header) if field_for(h)=="name" or h==explicit.get("name")),None)
    group=[]
    for num,row in enumerate(chain(prefix[start:],rows),start+1):
        if row is None:
            yield num,None
        elif any(v is not None and v!="" for v in row):
            values=list(dict.fromkeys(str(v).strip() for v in row if v is not None and str(v).strip()))
            first=values[0].casefold() if values else ""
            if TOTAL.fullmatch(first) or (name_idx is not None and name_idx<len(row) and TOTAL.fullmatch(str(row[name_idx]).strip())):
                continue
            if first in {"группа","раздел","подраздел","подгруппа","section","subsection"} and len(values)==2:
                group=(group[:1] if first in {"подраздел","подгруппа","subsection"} else [])+[values[1]]
                continue
            if len(values)==1 and row.count(values[0])>1 and not (layout and any(layout.values()) and name_idx is not None):
                level=next(i for i,v in enumerate(row) if v not in (None,""))
                group=group[:level]+[values[0]]
                continue
            if score(row)>=2 and sum(str(v).strip() in header for v in row if v is not None)>=2:
                continue
            data=dict(zip(header,row)) if len(row)<=len(header) else None
            if alternatives and data:
                data["prices"]={h:data[h] for h in alternatives if data.get(h) not in (None,"")}
                for label in alternatives:
                    if field_for(label)!="cost":
                        data.pop(label,None)
                data["_retail_price"]=retail
            if group and data and not any(field_for(k)=="category_path" and v for k,v in data.items()):
                data["category_path"]="/".join(group)
            yield num,data


def json_tables(obj, label):
    from .variants import nested_records
    if isinstance(obj,list):
        yield label,enumerate((variant for r in obj for variant in nested_records(r)),1)
    elif isinstance(obj,dict):
        from .variants import flatten
        wrappers={"products","cards","items","records","entries","results","edges","товары","карточки"}
        def product_lists(node,prefix):
            for key,value in node.items():
                nested=prefix+"/"+key
                if key.casefold() in wrappers and isinstance(value,list):
                    yield nested,value
                elif isinstance(value,dict):
                    yield from product_lists(value,nested)
        groups=list(product_lists(obj,label))
        if groups:
            for k,v in groups:
                yield from json_tables(v,k)
            return
        if any(field_for(k) in ("name","sku","offer_id") for k in flatten(obj)):
            yield label,enumerate(nested_records(obj),1)
            return
        for k,v in obj.items():
            if isinstance(v,(list,dict)):
                yield from json_tables(v,label+"/"+k)


def xlsx_rows(path, sheet,layout):
    # read_only worksheets stream cell values but omit merge metadata. Read only
    # the range references, then propagate the top-left value inside each range.
    starts={}
    indents={i:sheet.parent._alignments[style.alignmentId].indent
             for i,style in enumerate(sheet.parent._cell_styles) if sheet.parent._alignments[style.alignmentId].indent}
    with ZipFile(path) as book, book.open(sheet._worksheet_path) as xml:
        for _,node in etree.iterparse(xml,events=("end",),tag=("{*}mergeCell","{*}row"),resolve_entities=False,no_network=True):
            if etree.QName(node).localname=="mergeCell":
                left,top,right,bottom=range_boundaries(node.get("ref"))
                starts.setdefault(top,[]).append((left,right,bottom))
            else:
                num=int(node.get("r","0"))
                if node.get("outlineLevel"):
                    layout["outline"][num]=int(node.get("outlineLevel"))
                for cell in node.iterfind("{*}c[@s]") if indents else ():
                    indent=indents.get(int(cell.get("s")))
                    if indent and cell.get("r"):
                        col=column_index_from_string(re.match(r"[A-Z]+",cell.get("r"))[0])
                        layout["indent"][num,col]=indent
            node.clear()
            while node.getprevious() is not None:
                del node.getparent()[0]
    active=[]
    for i,values in enumerate(sheet.values,1):
        row=list(values)
        for left,right,bottom in starts.get(i,()):
            if left<=len(row):
                active.append((left,right,bottom,row[left-1]))
        for left,right,_,value in active:
            row[left-1:right]=[value]*(right-left+1)
        yield row
        active=[area for area in active if area[2]>i]


def tables(path, explicit, commerce=None):
    path=Path(path)
    ext=path.suffix.lower()
    if ext in (".csv",".tsv",".txt"):
        csv.field_size_limit(max(csv.field_size_limit(), 32*1024*1024))
        with path.open(encoding=encoding(path),errors="replace",newline="") as f:
            sample=f.read(32768)
            f.seek(0)
            yield str(path),spreadsheet(csv_rows(f,delimiter_for(sample)),explicit)
    elif ext==".xlsx":
        wb=load_workbook(path,data_only=True,read_only=True)
        try:
            for ws in wb:
                layout={"indent":{},"outline":{}}
                yield f"{path}/{ws.title}",spreadsheet(xlsx_rows(path,ws,layout),explicit,layout,ws.title)
        finally:
            wb.close()
    elif ext in (".jsonl",".ndjson"):
        with path.open(encoding=encoding(path),errors="replace") as f:
            def lines():
                for num,line in enumerate(f,1):
                    if line.strip():
                        try:
                            row=json.loads(line)
                        except ValueError:
                            row=None
                        yield num,row if isinstance(row,dict) else None
            yield str(path),lines()
    elif ext==".json":
        yield from json_tables(json.loads(path.read_text(encoding=encoding(path))),str(path))
    elif ext in (".yml",".xml"):
        from .variants import Commerce,is_commerce
        if is_commerce(path):
            yield str(path),(commerce or Commerce()).read(path)
            return
        cats={}
        rates={}
        def offers():
            for _,e in etree.iterparse(str(path),events=("end",),tag=("currency","category","offer"),resolve_entities=False,no_network=True):
                if e.tag=="currency":
                    rates[e.get("id")]=e.get("rate")
                elif e.tag=="category" and e.getparent().tag=="categories":
                    cats[e.get("id")]=(e.text,e.get("parentId"))
                elif e.tag=="offer":
                    row={c.tag:c.text for c in e if c.tag!="param"}
                    row.update(e.attrib)
                    if row.get("currencyId") in rates:
                        row["currency_rate"]=rates[row["currencyId"]]
                    row["sku"]=row.get("vendorCode") or row.get("id")
                    model=row.pop("model",None)
                    if not row.get("name"):
                        row["name"]=" ".join(filter(None,[row.get("typePrefix"),row.get("vendor"),model]))
                    row["attrs"]={c.get("name"):c.text for c in e.findall("param") if c.get("name") and c.text}
                    row["category_path"]=category_path(cats,row.pop("categoryId",None))
                    yield e.sourceline,row
                e.clear()
                while e.getprevious() is not None:
                    del e.getparent()[0]
        yield str(path),offers()
    else:
        raise ValueError(f"Неизвестный формат файла {path}")


def category_path(cats, key):
    path=[]
    seen=set()
    while key in cats and key not in seen:
        seen.add(key)
        title,key=cats[key]
        if title:
            path.append(title)
    return path[::-1]
