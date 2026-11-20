from .validate import validate, LIST_FIELDS, missing_references
from dataclasses import dataclass, field
from pathlib import Path
import yaml


def many(v):
    return v if isinstance(v,list) else [] if v is None else [v]


GROUPS = "vendors categories families roles industries use_cases faq analogs compliance slang crosssell".split()



@dataclass
class Knowledge:
    rows: dict = field(default_factory=lambda: {g:{} for g in GROUPS})
    errors: list = field(default_factory=list)
    syntax: list = field(default_factory=list)
    dangling: list = field(default_factory=list)

    def report(self):
        return dict(counts={g:len(r) for g,r in self.rows.items()}, errors=self.errors,
                    syntax=self.syntax, dangling=self.dangling)


def load(root: Path):
    kb = Knowledge()
    for group in GROUPS:
        paths = sorted((root/group).glob("*.yaml")) if group=="families" else [root/(group+".yaml")]
        for p in paths:
            if not p.exists():
                continue
            try:
                data = yaml.load(p.read_text(), Loader=yaml.CSafeLoader)
            except (yaml.YAMLError, UnicodeError) as exc:
                kb.syntax.append(f"{p}: {exc}")
                continue
            for i,row in enumerate(many(data)):
                key = {"slang":"term","analogs":"family"}.get(group,"id")
                try:
                    ident = row[key]
                    if not isinstance(ident,str):
                        raise ValueError(key)
                    row = dict(row)
                    for k in LIST_FIELDS:
                        if k in row:
                            row[k] = many(row[k])
                    if group == "families":
                        if not isinstance(row.get("name"),str):
                            raise ValueError("name")
                        lic = row.get("license") or {}
                        row["license"] = {k:many(v) for k,v in lic.items()}
                        for k in ("catalog","registry"):
                            if k in row:
                                row[k] = {"yes":True,"no":False}.get(row[k],row[k])
                        if any(not isinstance(e,dict) or not e.get("id") for e in row.get("editions",[])):
                            raise ValueError("editions")
                    if group=="slang" and not isinstance(row.get("maps_to"),dict):
                        raise ValueError("maps_to")
                    if group=="crosssell" and (not isinstance(row.get("when"),dict) or not isinstance(row.get("suggest"),list)
                            or any(not isinstance(v,dict) or not v.get("reason") for v in row["suggest"])):
                        raise ValueError("when / suggest")
                    validate(group,row)
                    if ident in kb.rows[group]:
                        kb.errors.append(f"{p.name} [{i+1}]: повтор {ident}")
                        continue
                    kb.rows[group][ident] = row
                except (KeyError,TypeError,ValueError,AttributeError) as exc:
                    kb.errors.append(f"{p.name} [{i+1}]: {exc}")
    from .titles import apply_titles
    apply_titles(kb,root/"overrides/families.yaml")
    kb.dangling.extend(missing_references(kb))
    return kb
