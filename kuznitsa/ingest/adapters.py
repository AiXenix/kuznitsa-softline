"""Yield named tables of (source row number, dict or None for a broken row)."""
import csv
import json
import re
from collections import Counter
from itertools import chain, islice
from pathlib import Path
from zipfile import ZipFile
from openpyxl.utils.cell import range_boundaries
from lxml import etree
from openpyxl import load_workbook

from .mapping import field_for


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


def spreadsheet(rows, explicit):
    prefix=list(islice(rows,50))
    def score(row):
        return sum(field_for(str(h)) is not None or h in explicit.values() for h in (row or ()) if h is not None)
    if not prefix:
        return
    idx=max(range(len(prefix)),key=lambda i:score(prefix[i]))
    header=[str(h).strip() if h is not None else "" for h in (prefix[idx] or ())]
    for num,row in enumerate(chain(prefix[idx+1:],rows),idx+2):
        if row is None:
            yield num,None
        elif any(v is not None and v!="" for v in row):
            yield num, (dict(zip(header,row)) if len(row)<=len(header) else None)


def json_tables(obj, label):
    if isinstance(obj,list):
        yield label, enumerate((r if isinstance(r,dict) else None for r in obj),1)
    elif isinstance(obj,dict):
        for k,v in obj.items():
            if isinstance(v,(list,dict)):
                yield from json_tables(v,label+"/"+k)


def xlsx_rows(path, sheet):
    # read_only worksheets stream cell values but omit merge metadata. Read only
    # the range references, then propagate the top-left value inside each range.
    starts={}
    with ZipFile(path) as book, book.open(sheet._worksheet_path) as xml:
        for _,node in etree.iterparse(xml,events=("end",),tag=("{*}mergeCell","{*}row"),resolve_entities=False,no_network=True):
            if etree.QName(node).localname=="mergeCell":
                left,top,right,bottom=range_boundaries(node.get("ref"))
                starts.setdefault(top,[]).append((left,right,bottom))
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


def tables(path, explicit):
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
                yield f"{path}/{ws.title}",spreadsheet(xlsx_rows(path,ws),explicit)
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
        cats={}
        def offers():
            for _,e in etree.iterparse(str(path),events=("end",),tag=("category","offer"),resolve_entities=False,no_network=True):
                if e.tag=="category" and e.getparent().tag=="categories":
                    cats[e.get("id")]=(e.text,e.get("parentId"))
                elif e.tag=="offer":
                    row={c.tag:c.text for c in e if c.tag!="param"}
                    row.update(e.attrib)
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
