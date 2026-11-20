"""Reader for the optional catalog-specific knowledge supplement (§26.4)."""
import yaml
from kuznitsa.kb.validate import validate


def merge_auto(kb, data):
    path=data/"kb_auto.yaml"
    counts=dict(vendors=0,categories=0,families=0)
    if not path.exists():
        return counts
    try:
        rows=yaml.load(path.read_text(),Loader=yaml.CSafeLoader) or {}
        if not isinstance(rows,dict):
            raise ValueError("ожидался YAML-объект")
        for group in counts:
            for row in rows.get(group,[]):
                ident=row["id"]
                if not ident.startswith("auto_") or ident in kb.rows[group]:
                    continue
                if group=="families":
                    row={"license":{},"catalog":True,"aliases":[],"editions":[],"summary":"",**row}
                validate(group,row)
                kb.rows[group][ident]=row
                counts[group]+=1
    except (TypeError,AttributeError,UnicodeError,ValueError,KeyError,yaml.YAMLError) as exc:
        kb.errors.append(f"{path}: {exc}")
    return counts
