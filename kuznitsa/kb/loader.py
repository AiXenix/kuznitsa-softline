from .validate import validate, LIST_FIELDS, missing_references
from dataclasses import dataclass, field
from pathlib import Path
import yaml
import re
from .extensions import unknown_fields,prune_families


def many(v):
    return v if isinstance(v,list) else [] if v is None else [v]


GROUPS = "vendors categories families roles industries use_cases faq analogs compliance slang crosssell okved".split()



@dataclass
class Knowledge:
    rows: dict = field(default_factory=lambda: {g:{} for g in GROUPS})
    errors: list = field(default_factory=list)
    syntax: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    auto: dict = field(default_factory=lambda: dict(vendors=0,categories=0,families=0))
    import_links: dict = field(default_factory=lambda: {g:{} for g in ("roles","industries","analogs","use_cases")})
    systems: dict = field(default_factory=dict)
    dangling: list = field(default_factory=list)

    sources: dict = field(default_factory=lambda: {g:dict(base=0,extensions=0,auto=0) for g in [*GROUPS,"for_whom","system_compat"]})

    def report(self):
        return dict(counts={g:sum(v.values()) for g,v in self.sources.items()}, errors=self.errors, warnings=self.warnings, auto=self.auto,
                    syntax=self.syntax, dangling=self.dangling,sources=self.sources)


def _read(kb,path):
    try:
        return yaml.load(path.read_text(), Loader=yaml.CSafeLoader)
    except (yaml.YAMLError, UnicodeError) as exc:
        kb.syntax.append(f"{path}: {exc}")


def _merge(kb,group,p,data,source,origins):
    for i,row in enumerate(many(data)):
        key = {"slang":"term","analogs":"family","okved":"code"}.get(group,"id")
        try:
            ident = row[key]
            if not isinstance(ident,str):
                raise ValueError(key)
            unknown=unknown_fields(group,row)
            if unknown:
                fields=", ".join(unknown)
                kb.warnings.append(f"{p.name} [{ident}]: пропущена строка с неизвестным полем {fields}")
                continue
            row = dict(row)
            if group=="faq":
                for field in ("tags","related_products","related_families","related_categories"):
                    row.setdefault(field,[])
            if group=="use_cases":
                row.setdefault("products",[])
            if group=="compliance":
                row.setdefault("effect",{})
            for k in LIST_FIELDS:
                if k in row:
                    row[k] = many(row[k])
            if group=="faq" and (not row.get("questions") or not isinstance(row.get("answer"),str)):
                raise ValueError("questions / answer")
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
            if source=="auto" and not ident.startswith("auto_"):
                kb.warnings.append(f"{p.name}: пропущен идентификатор {ident} без префикса auto_")
                continue
            if ident in kb.rows[group]:
                kb.warnings.append(f"{p.name} [{i+1}]: повтор {ident}")
                continue
            kb.rows[group][ident] = row
            kb.sources[group][source]+=1
            origins[group][ident]=source
        except (KeyError,TypeError,ValueError,AttributeError) as exc:
            kb.errors.append(f"{p.name} [{i+1}]: {exc}")


def load(root: Path, data_dir=None):
    kb = Knowledge()
    origins={g:{} for g in GROUPS}
    for group in GROUPS:
        paths = ([root/(group+".yaml"), *sorted(root.glob(group+"_*.yaml"))] if group!="families"
                 else sorted((root/group).glob("*.yaml"),key=lambda p:("_r" in p.stem,p.name)))
        for p in paths:
            if p.is_file():
                extension=bool(re.search(r"_r\d+",p.stem)) if group=="families" else p.stem!=group
                _merge(kb,group,p,_read(kb,p),"extensions" if extension else "base",origins)
    if data_dir and (p:=data_dir/"kb_auto.yaml").is_file():
        data=_read(kb,p)
        if isinstance(data,dict):
            for key in data.keys()-kb.auto.keys():
                kb.warnings.append(f"{p.name}: пропущена неизвестная группа {key}")
            for group in kb.auto:
                _merge(kb,group,p,data.get(group,[]),"auto",origins)
        elif data is not None:
            kb.errors.append(f"{p.name}: ожидается словарь групп")
    from .titles import apply_titles
    apply_titles(kb,root/"overrides/families.yaml")
    from .purposes import load_purposes
    load_purposes(kb,root,_read)
    prune_families(kb,origins)
    kb.dangling.extend(v for v in missing_references(kb) if v not in kb.dangling)
    kb.warnings.extend("Ссылка отсутствует: "+v for v in kb.dangling)
    kb.auto={g:kb.sources[g]["auto"] for g in kb.auto}
    for group in ("roles","industries"):
        for row in kb.rows[group].values():
            if row.get("parent") and row["parent"] not in kb.rows[group]:
                kb.warnings.append(f"{row['id']}: неизвестный parent {row.pop('parent')}")
        for row in kb.rows[group].values():
            parent=kb.rows[group].get(row.get("parent"))
            if parent and parent.get("aliases"):
                shared={str(phrase).casefold() for phrase in row.get("aliases",[])}
                parent["aliases"]=[phrase for phrase in parent["aliases"] if str(phrase).casefold() not in shared]
    for code,row in list(kb.rows["okved"].items()):
        if row.get("industry") not in kb.rows["industries"] or not row.get("title"):
            kb.warnings.append(f"ОКВЭД {code}: отсутствует отрасль или название")
            del kb.rows["okved"][code]
            kb.sources["okved"][origins["okved"][code]]-=1
    from kuznitsa.ingest.auto import reverse_links
    kb.import_links=reverse_links(kb.rows["families"])
    return kb
