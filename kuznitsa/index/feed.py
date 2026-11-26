"""Два уровня поиска в фиде: страницы продуктов и классы магазина."""
from collections import defaultdict
from functools import lru_cache
import json
import re

import numpy as np
from rapidfuzz import process, fuzz
from kuznitsa.text import normalize, lemma
from kuznitsa.llm.decisions import choice


HARDWARE = {"сервер":"сервера", "ноутбук":"ноутбука", "моноблок":"моноблока",
            "принтер":"принтера", "коммутатор":"коммутатора", "монитор":"монитора", "ибп":"ИБП"}
ALIASES = {"винда":"microsoft windows","365":"microsoft 365","офис":"офисные пакеты","астра линукс":"astra linux","мдаемон":"mdaemon","крипто про":"криптопро",
           "антивирь":"антивирус","макс патрол":"maxpatrol","max patrol":"maxpatrol","кибер бекап":"кибер бэкап"}
TASKS = [(r"вирус|антивир", "антивирусы для организаций"),(r"защит.*почт|почт.*защит","защита почты"),
         (r"чертеж","системы автоматизированного проектирования"),(r"контрагент","проверка контрагентов")]
STOP={"и","по","для","на","в","от","купить"}
QUESTION=re.compile(r"^(что использовать|что выбрать|что подойдет|како(?:й|е|ую) (?:программ|приложен|софт|инструмент)|чем |как проверить|программ\w* для|как защитить)")
COMPLEX=re.compile(r"\n|;|\b(продлен\w*|продлить|до|мест|лицензий|сравни\w*|комплект|аналог|заменить|реестр\w*|куплен\w*|заказ\w*)\b")


@lru_cache(50000)
def words(s):
    return tuple(lemma(w) for w in re.findall(r"[\w]+",normalize(s)) if w not in STOP)


def class_words(text):
    generic={"программа","программный","обеспечение","система","решение","по","работа","утилита"}
    return frozenset(words(text))-generic


class FeedIndex:
    def __init__(self,cat,kb,cfg):
        self.cat=cat
        self.groups=defaultdict(list)
        self.classes={}
        self.postings=defaultdict(set)
        self.terms={}
        self.raw_terms=defaultdict(set)
        self.quality={}
        self.tags=defaultdict(lambda:defaultdict(set))
        self.aliases=ALIASES.copy()
        self.products=lru_cache(512)(self.products)
        self.sections=lru_cache(256)(self.sections)
        tree=cfg.data/"feed_categories.json"
        lines=json.loads(tree.read_text()) if tree.exists() else {}
        for cid,c in cat.cards.items():
            o=c.offers[0]
            path=o.category_path
            section=o.class_id or (path[1] if len(path)>1 else c.category)
            self.groups[section].append(cid)
            self.classes[section]=path[min(1,len(path)-1)] if path else str(section)
            line=lines.get(o.group_id,[""])[0] if o.group_id else ""
            if line:
                c.title=line
            name=words(c.title)
            keys=set(name+words(o.vendor or "")+words(line))
            if o.group_id and not line:
                keys.update(words(o.name.split("(")[0].split(",")[0]))
            for raw in re.findall(r"[\w]+",normalize(c.title+" "+(o.vendor or ""))):
                self.raw_terms[raw].add(cid)
            self.terms[cid]=keys
            for w in keys:self.postings[w].add(cid)
            self.quality[cid]=(o.available,o.price is not None,len(c.offers),-len(c.title))
            for k,values in {"classes":[section,c.category,o.attrs.get("kb_category")],"families":[c.family,o.group_id,c.category,c.title,line],
                             "vendors":[o.vendor,c.vendor]}.items():
                for v in values:
                    if v:self.tags[k][str(v).casefold()].add(cid)
        for group in self.groups.values():group.sort(key=self.quality.get,reverse=True)
        self.card_sections={cid:k for k,group in self.groups.items() for cid in group}
        self.popular=sorted(cat.cards,key=self.quality.get,reverse=True)
        self.vocab=sorted(self.postings)
        self.prefix_vocab=sorted(self.raw_terms)
        from .feed_words import Sounds
        from .feed_tree import TreeVectors
        self.sounds=Sounds(self.vocab)
        descriptions={}
        for offer in cat.offers_by_id.values():
            if offer.group_id and offer.description:
                descriptions.setdefault(offer.group_id,offer.description)
        self.tree=TreeVectors(lines,descriptions,cat.dense,cfg)
        self.class_ids=list(self.groups)
        self.class_names={k:normalize(v) for k,v in self.classes.items()}
        self.class_by_name={v:k for k,v in self.class_names.items()}
        self.class_terms={k:set(words(v)) for k,v in self.classes.items()}
        self.class_vec=cat.dense.cached_embeddings(cfg,[
            self.classes[k]+". "+", ".join(cat.cards[i].title for i in self.groups[k][:4])
            for k in self.class_ids]) if hasattr(cat.dense,"model") else None
        for phrase,row in kb.rows["slang"].items():
            target=row["maps_to"]
            value=target.get("text") or target.get("query") or target.get("platform")
            if value:self.aliases.setdefault(normalize(phrase),str(value).replace("_"," "))
        for ident,row in kb.rows["vendors"].items():
            for alias in (row.get("name"),row.get("name_ru"),*row.get("aliases",[])):
                if alias:
                    self.tags["vendors"][ident].update(self.tags["vendors"].get(str(alias).casefold(),()))
        from kuznitsa.rank.upsell import Recommendations
        self.recommend=Recommendations(self,kb,cfg)
        self.slang={}
        for phrase,row in kb.rows["slang"].items():
            for kind,field in (("family","families"),("vendor","vendors"),("category","classes"),
                               ("line_id","families"),("class_id","classes")):
                target=row["maps_to"].get(kind)
                if target is None:continue
                members=self.tags[field].get(str(target).casefold())
                if members:
                    self.slang[normalize(phrase)]=(field,tuple(sorted(members,key=lambda i:(self.quality[i],i),reverse=True)))
                    break
        rows=kb.rows["hardware_hints"].values()
        self.hardware={}
        by_class={row["hardware_class"]:row for row in rows}
        for row in rows:
            for term in row["trigger_words"]:
                self.hardware[normalize(term)]=row
        from .hardware import hardware_kind
        def hardware_definition(value):
            kind,labels=hardware_kind(value)
            if kind in by_class:return by_class[kind]
            sections=[k for k,title in self.class_names.items() if
                      cat.cards[self.groups[k][0]].offers[0].domain=="hardware" and
                      any(label in words(title) for label in labels)]
            if sections:return dict(hardware_feed_classes=sections,software_classes=[])
            return {}

        for term,row in kb.rows["slang"].items():
            target=row["maps_to"]
            if target.get("attr")!="hardware_class":continue
            definition=hardware_definition(target.get("value",""))
            # Часть сокращений относится к более узкому классу, указанному в примечании.
            match=re.search(r"фид\s+([\d, ]+)",row.get("note",""))
            keys=re.findall(r"\d+",match[1]) if match else []
            if keys or definition:
                base=self.hardware.get(normalize(term),definition)
                self.hardware[normalize(term)]={**base,"hardware_feed_classes":keys or base["hardware_feed_classes"]}
        for alias,kind in {"ноут":"laptop","нетбук":"laptop","сервак":"server","комп":"desktop",
                           "мфушка":"printer_mfp","принтак":"printer_mfp","свитч":"switch","моник":"monitor",
                           "бесперебойник":"ups"}.items():
            definition=hardware_definition(kind)
            if definition:self.hardware.setdefault(alias,definition)
        self.class_aliases={}
        for key,title in self.class_names.items():
            signature=class_words(title)
            if signature:self.class_aliases.setdefault(signature,[]).append(key)
        self.vendor_names={normalize(c.offers[0].vendor):c.vendor for c in cat.cards.values() if c.offers[0].vendor}
        self.vendor_names.update({" ".join(words(name)):ident for name,ident in self.vendor_names.items()})
        for vid,row in kb.rows["vendors"].items():
            actual=next((self.vendor_names[" ".join(words(name))] for name in [row.get("name"),row.get("name_ru"),*row.get("aliases",[])]
                         if name and " ".join(words(name)) in self.vendor_names),None)
            if actual:
                for name in [row.get("name"),row.get("name_ru"),*row.get("aliases",[])]:
                    if name:self.vendor_names.setdefault(" ".join(words(name)),actual)
        self.unsold_sections={normalize(name):parent for key,(name,parent) in lines.items()
                              if key not in cat.cards and parent in self.groups}
        self.unsold_brands=defaultdict(list)
        for name,parent in self.unsold_sections.items():
            if words(name):self.unsold_brands[words(name)[0]].append(parent)
        self.replacements={}
        for row in kb.rows["analogs"].values():
            for phrase in [row.get("product"),*row.get("aliases",[])]:
                if phrase:self.replacements[normalize(phrase)]=row
        self.task_rows=kb.rows["use_cases"]

    def correct(self,q):
        if q in HARDWARE:return q
        if q in self.aliases:return self.aliases[q]
        for a,b in ALIASES.items():
            if a.isdigit() or a=="офис":continue
            if a in q:q=re.sub(r"\b"+re.escape(a)+r"\b",b,q)
        return q

    def products(self,q,prefix=False,domain=None):
        terms=list(words(q))
        if not terms:return ()
        pools=[]
        for w in terms:
            group=self.postings.get(w,set())
            if prefix and w==terms[-1]:
                from bisect import bisect_left
                from bisect import bisect_right
                partial=re.findall(r"[\w]+",normalize(q))[-1]
                i=bisect_left(self.prefix_vocab,partial)
                end=bisect_right(self.prefix_vocab,partial+chr(0x10ffff))
                group=group.union(*(self.raw_terms[v] for v in self.prefix_vocab[i:end]))
            if not group and len(w)>=5:
                best=process.extractOne(w,self.vocab,scorer=fuzz.ratio,score_cutoff=85)
                if best:group=self.postings[best[0]]
            if group:pools.append(group)
        if len(pools)!=len(terms):return ()
        ids=set.intersection(*pools)
        if domain:ids={i for i in ids if self.cat.cards[i].offers[0].domain==domain}
        def score(i):
            c=self.cat.cards[i]
            name=words(c.title)
            exact=tuple(terms)==name
            primary=not re.search(r"поддержк|обучен|курс |сертификат|миграц|продлен",c.title,re.I)
            version=max((int(y) for y in name if re.fullmatch(r"20[012]\d",y)),default=0)
            first=min((name.index(w) for w in terms if w in name),default=99)
            consumer=int("family" in name or "семья" in name)
            starts=prefix and any(t.startswith(terms[-1]) for t in name[:2])
            return (exact,primary,starts,all(w in name for w in terms),-first,self.quality[i][0],
                    name[:len(terms)]==tuple(terms),version,consumer,*self.quality[i][1:],i)
        return tuple(sorted(ids,key=score,reverse=True))

    def sound_products(self,q):
        raw=[w for w in re.findall(r"[\w]+",normalize(q)) if w not in STOP
             and lemma(w) not in ("клиент","лицензия","приложение","продукт")]
        alternatives=[tuple(dict.fromkeys((lemma(w),*self.sounds.lookup(w),*self.sounds.lookup(lemma(w))))) for w in raw]
        if not any(len(opts)>1 for opts in alternatives):return (),q
        pools=[set().union(*(self.postings.get(w,()) for w in opts)) for opts in alternatives]
        matches=set.intersection(*pools)
        if not matches:return (),q
        best=max(matches,key=lambda i:(sum(any(w in words(self.cat.cards[i].title) for w in opts)
                                           for opts in alternatives),self.quality[i],i))
        corrected=" ".join(next(w for w in opts if w in self.terms[best]) for opts in alternatives)
        return self.products(corrected),corrected

    def class_match(self,q):
        signature=class_words(q)
        candidates=self.class_aliases.get(signature,[])
        if candidates:return max(candidates,key=lambda k:len(self.groups[k]))
        return None

    def sections(self,q,hint=""):
        words_hint=set(words(hint or q))
        emb=np.einsum("ij,j->i",self.class_vec,self.cat.dense.encode(q)) if self.class_vec is not None else np.zeros(len(self.class_ids))
        leaf=self.tree.scores(self.cat.dense.encode(q)) if self.class_vec is not None else {}
        scores={}
        exact=normalize(hint or q)
        for i,k in enumerate(self.class_ids):
            common=len(words_hint & self.class_terms[k])/max(len(words_hint),1)
            scores[k]=.6*float(emb[i])+.4*leaf.get(k,0)+common+(exact==self.class_names[k])
        return sorted(scores,key=scores.get,reverse=True)[:8]

    def decide(self,e,q,options,sid,req,calls,focus=()):
        labels={}
        for k in options:
            examples=[i for i in focus if i in self.groups[k]][:3] or self.groups[k][:3]
            title=self.classes[k]
            root=self.cat.cards[self.groups[k][0]].offers[0].category_path[0]
            labels[k]=root+" / "+title+". "+", ".join(self.cat.cards[i].title for i in examples)
        labels["none"]="Подходящего раздела нет"
        from time import perf_counter
        answers,meta=e.decisions.decide_before(perf_counter()+.59,sid,req.model_source,"intent",{"запрос":q},
                         {"section":choice("Какой раздел магазина решает задачу покупателя?",labels)})
        calls.append(meta)
        answer=answers.get("section",{})
        k=answer.get("choice")
        return k if k in options and answer.get("probabilities",{}).get(k,0)>=.55 else None
