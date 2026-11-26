"""Подтверждённые свойства и дополнительные ключи предложения из прайса."""
import json
import re
from collections import defaultdict
from kuznitsa.text import LOOK, normalize, tokens, lemma
from kuznitsa.schema import Offer


def strings(value):
    if isinstance(value,str) and value.startswith("["):
        try:
            value=json.loads(value)
        except ValueError:
            pass
    if isinstance(value,str):
        value=re.split(r"[;|,\n]",value)
    return [str(s).strip() for s in value or () if str(s).strip()]


def read_offer(line):
    row=json.loads(line)
    attrs={k:v for k,v in (row.get("attrs") or {}).items() if v is not None}
    for field in ("class_id","oldprice"):
        value = row.get(field) or attrs.get(field)
        if value is not None:
            row[field] = str(value) if field != "oldprice" else value
    if row.get("domain") or attrs.get("domain"):
        row["image"] = row.get("image") or row.get("picture") or attrs.get("picture")
        if not row.get("price"):
            row.update(price=None,price_on_request=True)
    # Поддерживаем обе версии канонической схемы D и старые выгрузки только с attrs.
    if row.get("source_ids") or attrs.get("source_ids"):
        row["source_ids"]=list(dict.fromkeys([*strings(row.get("source_ids")),*strings(attrs.get("source_ids"))]))
        attrs["source_ids"]=row["source_ids"]
    if not row.get("source_id") and attrs.get("source_id"):
        row["source_id"]=str(attrs["source_id"])
    for field in ("source_id","added_at","domestic","in_stock","delivery_days","promo"):
        if row.get(field) is not None:
            attrs[field]=row[field]
    for key in ("aliases","certs","extra","prices"):
        value=attrs.get(key)
        if isinstance(value,str) and value.lstrip().startswith(("[","{")):
            try:
                decoded=json.loads(value)
            except ValueError:
                continue
            if isinstance(decoded,dict if key in ("extra","prices") else list):
                attrs[key]=decoded
    for k,v in attrs.items():
        if not isinstance(v,str) and k not in {"aliases","source_ids","certs","extra","prices"}:
            attrs[k]=json.dumps(v,ensure_ascii=False)
    return declared_offer(Offer.model_validate({**row,"attrs":attrs}))


def declared_offer(o):
    a=o.attrs
    if not a and o.domain!="software":return o
    vals={}
    if o.registry is None and a.get("registry_no","").casefold() not in ("","нет","0","false"):vals["registry"]=True
    if not o.certs:
        certs=[k for k in ("fstec","fsb") if str(a.get(k,"")).lower() not in ("","нет","false","0","none")]
        if certs:vals["certs"]=certs
    missing={}
    op=a.get("operation","").lower().replace("ё","е")
    for name,pattern in (("renewal","продлен|renew"),("new","новая|new"),("crossgrade","миграц|crossgrade"),("upgrade","upgrade|апгрейд")):
        if not o.lic.action and re.search(pattern,op):missing["action"]=name
    for name,key in (("qty_min","qty_min"),("qty_max","qty_max"),("term_months","term_months")):
        val=a.get(key,"")
        if not getattr(o.lic,name) and val.isdigit() and int(val)>0:missing[name]=int(val)
    if not o.lic.metric:
        unit=a.get("unit","").lower()
        for k,prefix in (("device","устрой"),("user","польз"),("core","яд"),("cpu","процессор"),("server","сервер"),("device","пк"),("company","организац")):
            if unit.startswith(prefix):missing["metric"]=k
        if o.domain=="software" and "metric" not in missing:
            basis=re.search(r"\b(?:(?:лицензия на (?:1 |один )?|на (?:1 |один ))(?:физический )?(процессор|сервер)|per (processor|server))\b",o.name,re.I)
            if basis:missing["metric"]="cpu" if (basis[1] or basis[2]).lower() in {"процессор","processor"} else "server"
    if o.domain=="software" and o.description:
        # В исходном фиде число узлов указывается также как ёмкость одной лицензии.
        # «Минимальная покупка» относится к числу таких лицензий в заказе.
        cap=re.search(r"(?:^|•)\s*К-во узлов\s+(\d+)\s*шт\.?(?:\s*•|$)",o.description,re.I)
        if cap and int(cap[1])>1 and not o.lic.pack and not o.lic.qty_max and o.lic.qty_min in (None,int(cap[1])):
            missing.update(metric="device",pack=int(cap[1]),qty_min=1)
    if missing:vals["lic"]=o.lic.model_copy(update=missing)
    return o.model_copy(update=vals) if vals else o


def source_key(value):
    # Сохраняем буквы, для которых нет визуального двойника в латинице.
    return re.sub(r"[^\w]|_","",value.casefold().translate(LOOK))


def identifiers(o):
    yield from (o.offer_id,o.sku,o.source_id,o.attrs.get("barcode"))
    yield from strings(o.attrs.get("source_ids"))


def replacements(o):
    return [normalize(s) for s in re.split(r"[;|]",o.attrs.get("analog_of","")) if s.strip()]


class SupplierNames:
    """Разделы и торговые названия поставщика вместе с карточками исходного прайса."""

    def __init__(self, cards):
        from kuznitsa.understand.repair import LAYOUT, typo_matcher
        from kuznitsa.understand.spell_index import roman, cyrillic

        self.names = defaultdict(set)
        self.layout = LAYOUT
        self.forms = defaultdict(set)
        self.tasks = defaultdict(set)
        self.task_words = {}
        self.by_word = defaultdict(set)
        for card in cards.values():
            for o in (card.offers[:1] if card.offers[0].domain else card.offers):
                for task in strings(o.attrs.get("task")):
                    self.tasks[normalize(task)].add(card.id)
                for alias in strings(o.attrs.get("aliases")):
                    self.names["alias",normalize(alias)].add(card.id)
                if not (not card.kb or o.source_id or o.source_ids or o.family_id and o.family_id.startswith("auto_") or o.attrs.get("source_id") or o.attrs.get("series") or " / " in o.name and "," in o.name):
                    continue
                series = o.attrs.get("series")
                if not series and " / " in o.name and "," in o.name:
                    series = normalize(o.name.partition(",")[0]).removeprefix(normalize(o.vendor or "")+" ")
                entries = [("family", o.name), ("family", series), ("family", o.family_name), ("vendor", o.vendor)]
                for category in o.category_path:
                    entries.append(("category", category))
                    if o.vendor:
                        entries.append(("category", category+" "+o.vendor))
                        entries.append(("category", o.vendor+" "+category))
                for kind, name in entries:
                    if name:
                        self.names[(kind,normalize(name))].add(card.id)
        self.compact=defaultdict(set)
        for kind, name in self.names:
            self.compact[name.replace(" ","")].add((kind,name))
            self.forms[name].add((kind,name))
            for variant in (name.translate(LAYOUT),roman(name),roman(name.replace("й","y")),cyrillic(name)):
                self.forms[normalize(variant)].add((kind,name))
                self.forms[normalize(re.sub(r"[-‐‑–]"," ",variant))].add((kind,name))
        for task in self.tasks:
            words=self.task_words[task]=self.terms(task)
            for w in words:
                self.by_word[w].add(task)
        self.series_by_head=defaultdict(set)
        self.qualifiers={}
        for (kind,name),card_ids in self.names.items():
            words=tokens(name)
            if kind!="family" or not words or len(words[0])<4 or words[0] in {"office","studio","server","standard","professional","software","enterprise"}:
                continue
            for cid in card_ids:
                card=cards[cid]
                # Название общего производителя не свидетельствует о родстве его серий.
                if words[0] in tokens(card.offers[0].vendor or "") and len(words)>1 and not card.offers[0].attrs.get("series"):
                    continue
                self.series_by_head[words[0]].add(cid)
                if cid not in self.qualifiers:
                    self.qualifiers[cid]={frozenset(tokens(" ".join(str(v or "") for v in
                        (o.name,o.family_name,o.attrs.get("series"),o.attrs.get("edition"),o.edition,o.version,o.delivery))))
                        for o in card.offers if o.available}
        self.nearest = typo_matcher({name for _,name in self.names})

    @staticmethod
    def terms(text):
        return {lemma(w) for w in tokens(text) if len(w)>2} - {
            "нужный","нужно","программа","задача","чтобы","помочь","помогать","какой","хотеть","как","для","чем"}

    def task(self,q):
        words=self.terms(q)
        if not words:
            return
        options=set().union(*(self.by_word.get(w,()) for w in words))
        best=()
        for task in options:
            terms=self.task_words[task]
            overlap=len(words & terms)
            score=2*overlap/(len(words)+len(terms))
            if task==q or terms==words or overlap>=2 and score>=.72:
                best=max(best,(score,task))
        return best[1] if best else None

    def nearby_variant(self,q):
        version=re.fullmatch(r"(.+?) (?:v|версия )?(\d+(?:\.\d+)*)",q)
        if version:
            ids=self.names.get(("family",version[1]),set())
            if ids and not any(version[2] in facts for cid in ids for facts in self.qualifiers.get(cid,())):
                return ids
        words=tokens(q)
        if not 2<=len(words)<=7 or not re.fullmatch(r"[a-z0-9. -]+",q):
            return
        ids=self.series_by_head.get(words[0])
        if not ids:return
        requested=set(words[1:])
        variant=r"\d+(?:\.\d+)*|[a-z]{1,3}|box|esd|server|desktop|professional|standard|enterprise|cloud|premium|business|ultimate"
        if not all(re.fullmatch(variant,w) for w in requested):return
        if not any(requested<=facts for cid in ids for facts in self.qualifiers[cid]):
            return ids

    def lookup(self, q, verbatim):
        if not self.forms and not self.tasks:
            return
        # Границы названия задают только распознанные слова операции и количества.
        boundary=r"^(?:купить|продлить|продление)\s+|\s+(?:продление|на \d+\s*(?:мест\w*|пк|пользовател\w*|компьютер\w*))$"
        key=re.sub(boundary,"",q)
        options=self.forms.get(key) or self.forms.get(key.replace("-"," "))
        if not options:
            # Адресат уточняет класс, но не является частью названия раздела.
            stem=re.split(r"\s+(?:(?:для|в) (?:мал\w* |небольш\w* )?(?:офис|дом|семь|сервер|компани)|маме\b|папе\b)",key,maxsplit=1)[0]
            if stem!=key:
                matches={entry for entry in self.forms.get(stem,()) if entry[0]=="category"}
                if matches:key,options=stem,matches
        # Назначение из прайса бывает также названием раздела. По точной фразе
        # подбираем варианты с подтверждённой задачей внутри этого ассортимента.
        if q in self.tasks and not any(kind!="category" for kind,_ in options or ()):
            return "task",self.tasks[q],q,q
        if not options and not verbatim:
            options=self.compact.get(key.replace(" ",""))
            parts=key.split()
            for i,part in enumerate(parts):
                if options:break
                mixed=" ".join([*parts[:i],part.translate(self.layout),*parts[i+1:]])
                options=self.forms.get(mixed) or self.compact.get(mixed.replace(" ",""))
            layout=normalize(q.translate(self.layout))
            other=re.sub(boundary,"",layout)
            if not options:
                options=self.forms.get(other) or self.compact.get(other.replace(" ",""))
                if options:q,key=layout,other
        if not options and self.nearby_variant(key):return
        if not options and not verbatim and 5 <= len(key) <= 100:
            near = self.nearest(key, 2, 2 if len(key)>=9 else 1)
            if near and (len(near)==1 or near[0][1]<near[1][1]):
                options = self.forms[near[0][0]]
        if not options:
            task=self.task(q) if self.tasks and not verbatim else None
            if task:
                return "task",self.tasks[task],q,task
            return
        kind,name = min(options,key=lambda pair:(pair[1]!=key,("alias","family","category","vendor").index(pair[0]),pair[1]))
        if verbatim and name!=key:
            return
        corrected = q.replace(key,name,1) if name!=key else q
        return kind,self.names[kind,name],corrected,name
