import re
import yaml
from .validate import LIST_FIELDS,validate


def clean(text):
    text = re.sub(r"(?:\s*\([^()]*\))+$", "", text).strip() or text
    return re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", text, flags=re.I)


def apply_titles(kb, path):
    overrides = {}
    if path.exists():
        try:
            overrides = yaml.load(path.read_text(), Loader=yaml.CSafeLoader) or {}
        except (yaml.YAMLError,UnicodeError) as exc:
            kb.syntax.append(f"{path}: {exc}")
    if not isinstance(overrides,dict):
        kb.errors.append(f"{path}: ожидалось отображение семейств")
        overrides={}
    families=kb.rows["families"]
    for fid in overrides.keys()-families.keys():
        kb.dangling.append(f"overrides.families → {fid}")
    for fid,f in families.items():
        patch=overrides.get(fid,{})
        if not isinstance(patch,dict):
            kb.errors.append(f"overrides.{fid}: ожидалось отображение")
            patch={}
        editions=patch.get("editions") or {}
        updated={**f,**{k:v for k,v in patch.items() if k!="editions"}}
        try:
            from .loader import many
            for key in set(patch).intersection(LIST_FIELDS)-{"editions"}:
                updated[key]=many(updated[key])
            if "license" in patch:
                updated["license"]={k:many(v) for k,v in (patch["license"] or {}).items()}
            validate("families",updated)
            if "title" in patch and not isinstance(patch["title"],str):
                raise ValueError("title")
            if not isinstance(editions,dict) or any(not isinstance(v,str) for v in editions.values()):
                raise ValueError("editions")
        except (AttributeError,TypeError,ValueError) as exc:
            kb.errors.append(f"overrides.{fid}: {exc}")
            editions={}
        else:
            f.update(updated)
        title=f["title"]=f.get("title") or clean(f["name"])
        f["aliases"]=list(dict.fromkeys([*f.get("aliases",[]),f["name"],title]))
        for ed in f.get("editions",[]):
            old=ed.get("name",ed["id"])
            label=editions.get(ed["id"]) if isinstance(editions,dict) else None
            if label is None:
                label=re.sub("^"+re.escape(title)+r"(?=$|[\s:–—-])","",clean(old),flags=re.I).strip(" -:–—")
            ed["title"]=label
            ed["aliases"]=list(dict.fromkeys([*ed.get("aliases",[]),old,label]))
