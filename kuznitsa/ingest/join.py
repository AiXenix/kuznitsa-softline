"""Join complementary supplier tables on exact, unambiguous identifiers."""
from collections import defaultdict

from .variants import ID_FIELDS as KEYS


def identifiers(row):
    aliases=row.get("source_ids",[])
    aliases=aliases if isinstance(aliases,list) else [aliases]
    return list(dict.fromkeys(str(v).strip() for v in [
        *(row.get(k) for k in KEYS),*aliases,*row.get("_aliases",[])] if v not in (None,"")))


def expand(tables,stats):
    """A parent describes the product. Each explicit variant or price band is an offer."""
    parents=defaultdict(set)
    for label,rows in tables.items():
        for i,(_,row) in enumerate(rows):
            if row.get("name") and not row.get("_parent_id"):
                for key in identifiers(row):
                    parents[key.casefold()].add((label,i))
    consumed=set()
    for label,rows in tables.items():
        for i,(line,child) in enumerate(rows):
            parent=child.get("_parent_id")
            tier="price" in child and ("qty_min" in child or "qty_max" in child) and not child.get("name")
            if not (parent or tier):
                continue
            ids=[parent] if parent else identifiers(child)
            targets=[parents[str(k).casefold()] for k in ids if parents.get(str(k).casefold())]
            matches=set.intersection(*targets) if targets else set()
            if len(matches)!=1:
                continue
            key=next(iter(matches))
            base=tables[key[0]][key[1]][1]
            row={**base,**child}
            row.pop("_product",None)
            row.pop("_parent_id",None)
            row["source_ids"]=list(dict.fromkeys(identifiers(child)+identifiers(base)))
            row["family_name"]=base.get("family_name") or base.get("series") or base["name"]
            for field in ("attrs","_extra","_field_currency"):
                row[field]={**base.get(field,{}),**child.get(field,{})}
            if tier:
                row["_tier"]=True
            rows[i]=(line,row)
            consumed.add(key)
    for label,idx in consumed:
        stats["matched"][label]+=1
    return {label:[pair for i,pair in enumerate(rows) if (label,i) not in consumed]
            for label,rows in tables.items() if any((label,i) not in consumed for i in range(len(rows)))}


def matched_columns(tables):
    """Discover alternate ID headings by overlap of distinct, near-unique values."""
    columns={}
    for label,rows in tables.items():
        values=defaultdict(list)
        for _,row in rows:
            for key,value in {**row.get("_extra",{}),**{k:row[k] for k in KEYS if k in row}}.items():
                text=str(value).strip().casefold()
                if text and len(text)<=100:
                    values[key].append(text)
        columns[label]={key:set(v) for key,v in values.items() if len(set(v))>=.9*len(v)}
    found=defaultdict(set)
    for label,fields in columns.items():
        for key,values in fields.items():
            if key in KEYS:
                continue
            for other,targets in columns.items():
                if label==other:
                    continue
                for candidate,ids in targets.items():
                    if candidate not in KEYS and not any(any(c.isdigit() for c in v) for v in values):
                        continue
                    common=len(values & ids)
                    if common>=2 and common>=.7*min(len(values),len(ids)):
                        found[label].add(key)
    return found


def merge(rows,stats):
    tables=defaultdict(list)
    for label,n,row in rows:
        tables[label].append((n,row))

    extra=matched_columns(tables)
    stats["join_columns"]={label:sorted(keys) for label,keys in extra.items()}
    for label,keys in extra.items():
        for _,row in tables[label]:
            aliases=[row["_extra"][k] for k in sorted(keys) if k in row.get("_extra",{})]
            if aliases:
                row.setdefault("source_id",aliases[0])
                row.setdefault("_aliases",[]).extend(aliases)
    tables=expand(tables,stats)

    def authority(label):
        sample=tables[label][:30]
        return (not any(r.get("name") for _,r in sample),label.lower().endswith((".xml",".yml")),
                -sum(len(r) for _,r in sample)/len(sample))

    result=[]
    index=defaultdict(set)
    for label in sorted(tables,key=authority):
        additions=[]
        for n,row in tables[label]:
            aliases=identifiers(row)
            keys=[str(v).strip().casefold() for v in aliases]
            matches=[index[k] for k in keys if index.get(k)]
            candidates=set.intersection(*matches) if matches else set()
            # A shared internal code outranks a part number reused in other tiers.
            for field in ("source_id","id"):
                primary=index.get(str(row.get(field,"")).strip().casefold())
                if primary:
                    identities={str(result[i][2].get("source_id") or "").casefold() for i in primary}
                    if len(primary)==1 or (len(identities)==1 and "" not in identities
                            and not any(result[i][2].get("_tier") for i in primary)):
                        candidates={min(primary)}
                        break
            if len(candidates)==1 and row.get("name"):
                previous,_,record=result[next(iter(candidates))]
                if (".xlsx/" in label.lower() and previous.rpartition("/")[0]==label.rpartition("/")[0]
                        and row==record):
                    # A repeated product on a continuation sheet belongs in the duplicate report.
                    candidates=set()
            if len(candidates)==1:
                i=next(iter(candidates))
                primary=result[i][2]
                for field,value in row.items():
                    if field in ("_aliases","source_ids"):
                        continue
                    if field not in primary:
                        primary[field]=value
                    elif field in ("attrs","_extra","_field_currency") and isinstance(primary[field],dict) and isinstance(value,dict):
                        primary[field]={**value,**primary[field]}
                    elif str(primary[field])!=str(value):
                        stats["conflicts"][field]+=1
                        if len(stats["examples"])<20:
                            stats["examples"].append(dict(file=label,row=n,field=field,kept=primary[field],incoming=value))
                primary.setdefault("_aliases",[]).extend(aliases)
                stats["matched"][label]+=1
            else:
                i=len(result)
                result.append((label,n,row))
            additions.append((keys,i))
        for keys,i in additions:
            for key in keys:
                index[key].add(i)
    return result
