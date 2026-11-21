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
    # Поддерживаем обе версии канонической схемы D и старые выгрузки только с attrs.
    if row.get("source_ids") or attrs.get("source_ids"):
        row["source_ids"]=list(dict.fromkeys([*strings(row.get("source_ids")),*strings(attrs.get("source_ids"))]))
        attrs["source_ids"]=row["source_ids"]
    if not row.get("source_id") and attrs.get("source_id"):
        row["source_id"]=str(attrs["source_id"])
    for field in ("source_id","added_at","domestic","in_stock","delivery_days","promo"):
        if row.get(field) is not None:
            attrs[field]=row[field]
    for key in ("aliases","certs","extra"):
        value=attrs.get(key)
        if isinstance(value,str) and value.lstrip().startswith(("[","{")):
            try:
                decoded=json.loads(value)
            except ValueError:
                continue
            if isinstance(decoded,dict if key=="extra" else list):
                attrs[key]=decoded
    for k,v in attrs.items():
        if not isinstance(v,str) and k not in {"aliases","source_ids","certs","extra"}:
            attrs[k]=json.dumps(v,ensure_ascii=False)
    return declared_offer(Offer.model_validate({**row,"attrs":attrs}))


def declared_offer(o):
    a=o.attrs
    if not a:return o
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
        for k,prefix in (("device","устрой"),("user","польз"),("core","яд"),("server","сервер"),("device","пк"),("company","организац")):
            if unit.startswith(prefix):missing["metric"]=k
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
            for o in card.offers:
                for task in strings(o.attrs.get("task")):
                    self.tasks[normalize(task)].add(card.id)
                for alias in strings(o.attrs.get("aliases")):
                    self.names["alias",normalize(alias)].add(card.id)
                if not (not card.kb or o.source_id or o.source_ids or o.family_id and o.family_id.startswith("auto_") or o.attrs.get("source_id") or o.attrs.get("series") or " / " in o.name and "," in o.name):
                    continue
                series = o.attrs.get("series")
                if not series and " / " in o.name and "," in o.name:
                    series = normalize(o.name.partition(",")[0]).removeprefix(normalize(o.vendor or "")+" ")
                entries = [("family", series), ("family", o.family_name), ("vendor", o.vendor)]
                for category in o.category_path:
                    entries.append(("category", category))
                    if o.vendor:
                        entries.append(("category", category+" "+o.vendor))
                        entries.append(("category", o.vendor+" "+category))
                for kind, name in entries:
                    if name:
                        self.names[(kind,normalize(name))].add(card.id)
        for kind, name in self.names:
            self.forms[name].add((kind,name))
            for variant in (name.translate(LAYOUT),roman(name),cyrillic(name)):
                self.forms[normalize(variant)].add((kind,name))
                self.forms[normalize(re.sub(r"[-‐‑–]"," ",variant))].add((kind,name))
        for task in self.tasks:
            words=self.task_words[task]=self.terms(task)
            for w in words:
                self.by_word[w].add(task)
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

    def lookup(self, q, verbatim):
        if not self.forms and not self.tasks:
            return
        # Границы названия задают только распознанные слова операции и количества.
        boundary=r"^(?:купить|продлить|продление)\s+|\s+(?:продление|на \d+\s*(?:мест\w*|пк|пользовател\w*|компьютер\w*))$"
        key=re.sub(boundary,"",q)
        options=self.forms.get(key) or self.forms.get(key.replace("-"," "))
        # Назначение из прайса бывает также названием раздела. По точной фразе
        # подбираем варианты с подтверждённой задачей внутри этого ассортимента.
        if q in self.tasks and not any(kind!="category" for kind,_ in options or ()):
            return "task",self.tasks[q],q,q
        if not options and not verbatim:
            layout=normalize(q.translate(self.layout))
            other=re.sub(boundary,"",layout)
            if other!=layout and other in self.forms:
                q,key,options=layout,other,self.forms[other]
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
