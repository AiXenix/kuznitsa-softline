"""Offline SKU parsing. Evidence keeps the source text alongside each decision."""
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz, process


TOKEN = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class Evidence:
    value: object
    fragment: str
    source: str = "name"
    confidence: float = .95


def normalize(value):
    return " ".join(TOKEN.findall(str(value).casefold().replace("ё", "е")))


# Order matters where configuration words overlap with the product name.
RULES = {
    "action": {"renewal":r"renewal|rnwl|rnw|продл\w*", "crossgrade":r"cross[- ]?grade|кросс[- ]?грейд|миграция|переход",
               "upgrade":r"upgrade|апгрейд|обновлен\w*", "addon":r"add[- ]?on|докуп\w*|расширение",
               "support":r"support|тп|техподдерж\w*|поддержк\w*", "new":r"new|base|базовая лицензия|новая лицензия"},
    "model":{"perpetual":r"perpetual|бессроч\w*", "subscription":r"subscription|подписк\w*"},
    "audience":{"edu":r"edu|academic\w*|академическ\w*|для образован\w*|для школ\w*",
                "gov":r"gov|для гос\w*", "home":r"home|для дома", "med":r"med|для мед\w*",
                "nonprofit":r"nonprofit|для нко", "business":r"business|для бизнеса|для организаций"},
    "metric":{"concurrent":r"concurrent|одновременн\w* подключени\w*", "mailbox":r"mailbox\w*|почтов\w* ящик\w*",
              "device":r"devices?|nodes?|пк|компьютер\w*|устройств\w*|уз(?:ел|л\w*)|раб(?:оч\w*|\.)?\s*мест\w*",
              "user":r"users?|пользовател\w*|сотрудник\w*", "core":r"cores?|corelic|ядер|ядр\w*",
              "cpu":r"cpus?|процессор\w*", "vm":r"vms?|вм|виртуальн\w* машин\w*",
              "server":r"servers?|сервер\w*", "company":r"company|организаци\w*", "site":r"sites?|площад\w*",
              "storage":r"storage|ед\. хранения"},
    "delivery":{"esd":r"esd|электронн\w* поставк\w*", "box":r"box|короб\w*", "paper":r"paper|бумажн\w*",
                "media":r"media|dvd|носител\w*", "service":r"service|услуга"},
    "language":{"ru":r"russian|русский|rus|(?<!\.)ru", "multi":r"multi\w*|многоязыч\w*", "en":r"en|english|английск\w*"},
}
PATTERNS = {field: [(value,re.compile(r"(?<!\w)(?:"+pattern+r")(?!\w)", re.I)) for value,pattern in rules.items()]
            for field,rules in RULES.items()}
TERM = re.compile(r"(?<!\w)(\d+)\s*(years?|months?|[ym]|год(?:а|ов)?|лет|г\.?|мес\w*\.?)(?!\w)", re.I)
BAND = re.compile(r"(?<![\w.])(?:от\s+)?(\d+)\s*(?:[-–—‑]|до)\s*(\d+)(?![\w.])|(?<!\w)(\d+)\+(?!\w)", re.I)
UNITS = "|".join(RULES["metric"].values())
PACK = re.compile(r"(?<![\w.])(\d+)\s*("+UNITS+r"|лиц\.?|lic|шт\.?|pk)(?!\w)", re.I)
SKU_PREFIXES = {"winsvrstdcore":("windows_server","standard"), "dr web desktop security suite":("drweb_enterprise_security_suite","desktop")}


class AliasIndex:
    def __init__(self):
        self.aliases = {}
        self.starts = defaultdict(set)

    def add(self, alias, ident):
        key = normalize(alias)
        if key:
            words = key.split()
            self.starts[words[0]].add(len(words))
            self.aliases.setdefault(key,ident)

    def match(self, text, fuzzy=False):
        key = normalize(text)
        if key in self.aliases:
            return Evidence(self.aliases[key],text)
        words = list(TOKEN.finditer(text))
        tokens = key.split()
        best = None
        for i,token in enumerate(tokens[:len(words)]):
            for n in self.starts.get(token,()):
                if i+n > len(words):
                    continue
                phrase = " ".join(tokens[i:i+n])
                if phrase in self.aliases and (best is None or len(phrase)>best[0]):
                    best = len(phrase), Evidence(self.aliases[phrase],text[words[i].start():words[i+n-1].end()])
        if best:
            return best[1]
        if fuzzy and len(key)>=5:
            hit = process.extractOne(key,self.aliases.keys(),scorer=fuzz.ratio,score_cutoff=90)
            if not hit and " " in key:
                hit = process.extractOne(key,self.aliases.keys(),scorer=fuzz.token_sort_ratio,score_cutoff=90)
            if hit:
                return Evidence(self.aliases[hit[0]],text,confidence=hit[1]/100)
        return None


class Parser:
    def __init__(self, kb):
        self.kb = kb.rows
        self.index = {}
        self.editions = {}
        self.by_vendor = defaultdict(AliasIndex)
        for group in ("vendors","families","categories"):
            index = self.index[group] = AliasIndex()
            # Official titles take precedence over an overlapping alias of another product.
            for ident,row in self.kb[group].items():
                for alias in (ident,row.get("name",""),row.get("title","")):
                    index.add(alias,ident)
                    if group=="families" and row.get("vendor"):
                        self.by_vendor[row["vendor"]].add(alias,ident)
            for ident,row in self.kb[group].items():
                for alias in [ident,row.get("name",""),row.get("name_ru",""),row.get("title",""),row.get("title_short",""),
                              *row.get("aliases",[]),*row.get("synonyms",[]),*row.get("sku_name_examples",[])]:
                    index.add(alias,ident)
                    if group=="families" and row.get("vendor"):
                        self.by_vendor[row["vendor"]].add(alias,ident)
                if group=="families":
                    editions = self.editions[ident] = AliasIndex()
                    for ed in row.get("editions",[]):
                        for alias in [ed["id"],ed.get("title",""),ed.get("name",""),*ed.get("aliases",[])]:
                            editions.add(alias,ed["id"])
        # A legal name can be followed by its brand in parentheses. Add only
        # unambiguous derived names after *all* curated aliases have priority.
        legal_names=defaultdict(set)
        for ident,row in self.kb["vendors"].items():
            name,separator,_=str(row.get("name_ru") or "").partition("(")
            if separator and len(normalize(name).split())>=2:
                legal_names[normalize(name)].add(ident)
        for name,owners in legal_names.items():
            if len(owners)==1:
                self.index["vendors"].add(name,next(iter(owners)))
        for alias,(fid,_) in SKU_PREFIXES.items():
            if fid in self.editions:
                self.index["families"].add(alias,fid)
                self.by_vendor[self.kb["families"][fid]["vendor"]].add(alias,fid)
        self.parse = lru_cache(8192)(self.parse)
        self.lookup = lru_cache(8192)(self.lookup)
        # Hundreds of SKU configurations often have the same product heading.
        self.heading_match = lru_cache(8192)(lambda index,heading:index.match(heading))

    def lookup(self, group, text):
        return self.index[group].match(text, fuzzy=True)

    def parse(self, name, vendor_id=None, family=None):
        fields = {}
        fragments = []
        def record(key,value,match):
            fields[key] = Evidence(value,match.group())
            fragments.append(match.span())

        split = re.search(r",|\bRussian(?: Edition)?\b",name,re.I)
        for field,rules in PATTERNS.items():
            # "Windows Home ... BUSINESS" has a retail edition and a distinct buyer segment.
            starts = (split.end(),0) if split and field in ("audience","metric","action","model") else (0,)
            for start in starts:
                for value,pattern in rules:
                    m = pattern.search(name,start)
                    if m:
                        record(field,value,m)
                        break
                if field in fields:
                    break
        term = TERM.search(name)
        if term:
            months = term[2].lower().startswith(("m","мес"))
            record("term_months",int(term[1])*(1 if months else 12),term)
            fields.setdefault("model",Evidence("subscription",term.group()))
        band = BAND.search(name)
        if band:
            record("qty_min",int(band[1] or band[3]),band)
            if band[2]:
                record("qty_max",int(band[2]),band)
        pack = PACK.search(name)
        if pack and not (band and band.start()<=pack.start()<band.end()):
            record("pack",int(pack[1]),pack)
        if pack:
            for value,pattern in PATTERNS["metric"]:
                if pattern.fullmatch(pack[2]):
                    record("metric",value,pack)
                    break
        for value,pattern in [("fstec","фстэк|fstec"),("fsb",r"\bфсб\b|\bfsb\b"),("mo","минобороны")]:
            m = re.search(pattern,name,re.I)
            if m:
                old = fields.get("certs")
                record("certs",(old.value if old else [])+[value],m)
        registry = re.search(r"(?:вне реестра|не (?:входит в |в )реестр(?:е)?|(?:из |в )?реестр(?:е|а)?(?: российского по)?)",name,re.I)
        if registry:
            record("registry",not registry.group().lower().startswith(("вне","не ")),registry)
        clean = list(name)
        for begin,end in fragments:
            clean[begin:end] = " "*(end-begin)
        core = re.sub(r"\b(?:право на использование по|russian edition|edition|licenses?|лицензи\w*|лиц|пакет(?: на)?)\b"," ","".join(clean),flags=re.I)
        core = re.sub(r"[\s,;:.–—-]+"," ",core).strip() or name
        fields["core"] = Evidence(core,name,confidence=.75)
        heading = name[:split.start()].strip() if split else name
        def entity(index):
            match = self.heading_match(index,heading)
            return match if match or heading==name else index.match(name)

        vendor = entity(self.index["vendors"])
        vid = vendor_id or (vendor.value if vendor else None)
        if vendor:
            fields["vendor_id"] = vendor
        index = self.by_vendor.get(vid) if vid else self.index["families"]
        if family in self.editions and (not vid or self.kb["families"][family].get("vendor")==vid):
            found=Evidence(family,family,"column",1)
        elif family:
            found = (index.match(family,True) or entity(index)) if index else None
        else:
            found = entity(index) if index else None
            if not found and index and vid:
                found = index.match(core,True)
        if found:
            fid = found.value
            fields["family_id"] = found
            f = self.kb["families"][fid]
            if f.get("vendor"):
                fields["vendor_id"] = Evidence(f["vendor"],found.fragment,"kb")
            fields["category_id"] = Evidence(f.get("category"),found.fragment,"kb")
            ed = entity(self.editions[fid])
            if ed:
                fields["edition"] = ed
            elif fid=="windows_server" and "winsvrstdcore" in name.lower():
                fields["edition"] = Evidence("standard",re.search("stdcore", name, re.I).group())
            for version in sorted(map(str,f.get("versions",[])),key=len,reverse=True):
                m = re.search(r"(?<![\w.])"+re.escape(version)+r"(?![\w.])",name,re.I)
                if m and not any(a<=m.start()<b for a,b in fragments):
                    record("version",version,m)
                    break
            metrics = f.get("license",{}).get("metrics",[])
            if len(metrics)==1:
                fields.setdefault("metric",Evidence(metrics[0],found.fragment,"kb",.85))
            models = f.get("license",{}).get("models",[])
            if len(models)==1:
                fields.setdefault("model",Evidence(models[0],found.fragment,"kb",.85))
        if not found:
            ed = re.search(r"\b(?:Pro(?:fessional)?|Standard|Advanced|Enterprise|Стандартный|Расширенный|КОРП)\b",core,re.I)
            if ed:
                fields["edition"]=Evidence(ed.group().lower(),ed.group(),confidence=.85)
                fields["core"]=Evidence((core[:ed.start()]+core[ed.end():]).strip() or core,name,confidence=.75)
        if "version" not in fields:
            m = re.search(r"(?<![\w.])(?:v(?:er(?:sion)?)?\.?\s*)?(?:20(?:0[0-9]|[1-3][0-9])|\d{1,2}(?:\.\d+){1,3})(?![\w.])",name,re.I)
            if m and not any(a<=m.start()<b for a,b in fragments):
                record("version",re.sub(r"^v(?:er(?:sion)?)?\.?\s*","",m.group(),flags=re.I),m)
        return fields
