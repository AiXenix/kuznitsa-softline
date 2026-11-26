"""Подбор раздела действующего прайса по его собственным названиям и товарам."""
import hashlib
import re
from collections import defaultdict
import numpy as np
from kuznitsa.text import tokens,lemma
from kuznitsa.llm.decisions import choice

REPLACEMENT=re.compile(r"^(?:(?:российск|отечествен)\w* )?(?:чем заменить|аналог(?:и)?|альтернатив\w*|замена|вместо)\s+(?:для )?")
TASK=re.compile(r"\b[а-я]{3,}(?:ть|ться)\b|\b(?:linux|postgres\w*|exchange|pgsql|software|players?)\b")
PURCHASE=re.compile(r"^(?:купить|заказать|приобрести)\s+")


class Sections:
    def __init__(self,catalog,cfg):
        self.labels={}
        self.groups=defaultdict(list)
        self.descriptions={}
        self.terms={}
        texts=[]
        paths=defaultdict(lambda:defaultdict(list))
        self.category={}
        self.members={}
        for i,card in enumerate(catalog.cards.values()):
            o=card.offers[0]
            if o.domain:continue
            if not card.category or not o.category_path or not (o.source_id or o.source_ids or o.attrs.get("series") or not card.kb):
                continue
            paths[card.category][tuple(o.category_path)].append(i)
        for category,branches in paths.items():
            for path,indices in branches.items():
                key=category if len(branches)==1 else category+"_"+hashlib.sha256("\0".join(path).encode()).hexdigest()[:12]
                self.category[key]=category
                self.groups[key]=indices
                self.members[key]=[catalog.ids[i] for i in indices]
                self.labels[key]=path[-1]
        for section,indices in self.groups.items():
            examples=[]
            terms=set()
            for i in indices:
                card=catalog.cards[catalog.ids[i]]
                sample=card.title+" "+card.offers[0].description[:140]
                terms.update(map(lemma,tokens(sample)))
                if len(examples)<3:examples.append(sample)
            text=self.labels[section]+". "+"; ".join(examples)
            self.terms[section]=terms|set(map(lemma,tokens(self.labels[section])))
            self.descriptions[section]=text[:350]
            texts.append(text)
        self.dense=catalog.dense
        self.matrix=self.dense.cached_embeddings(cfg,texts) if self.dense.matrix is not None and texts else None

    def candidates(self,q):
        terms=set(map(lemma,tokens(q)))
        semantic=self.dense.scores(q,len(self.dense.matrix)) if self.matrix is not None else None
        labels=np.einsum("ij,j->i",self.matrix,self.dense.encode(q)) if semantic is not None else None
        scores={}
        for i,(key,indices) in enumerate(self.groups.items()):
            lexical=len(terms & self.terms[key])/max(1,len(terms))
            scores[key]=lexical if labels is None else .48*float(labels[i])+.47*float(max(semantic[indices]))+.05*lexical
        return sorted(scores.items(),key=lambda x:(-x[1],x[0]))[:8]

    def resolve(self,q,smart,deadline,sid,req,calls,trace):
        if "category" in req.ignore:
            return None,[],"rules",0.
        candidates=self.candidates(q)
        best,score=candidates[0]
        purchase=PURCHASE.match(q)
        if purchase and score<.40:
            subject=q[purchase.end():]
            words={lemma(word) for word in tokens(subject) if len(word)>2}
            if not (TASK.search(subject) or re.search("[a-z]",subject) or any(words & self.terms[key] for key,_ in candidates)):
                return None,[],"rules",0.
        if not (REPLACEMENT.match(q) or TASK.search(q)) and score<.30:
            return None,[],"rules",0.

        selected=best if score>=.40 and (len(candidates)==1 or score-candidates[1][1]>=.055) else None
        source="embed" if self.matrix is not None else "rules"
        if smart:
            options={k:self.descriptions[k] for k,_ in candidates}
            options["none"]="Подходящего раздела нет"
            answers,meta=smart.decide_before(deadline,sid,req.model_source,"intent",{"запрос":q},{
                "section":choice("Какой раздел прайса решает задачу покупателя? Для замены оцени назначение исходного продукта. При отсутствии соответствия выбери none.",options)})
            calls.append(meta)
            answer=answers.get("section",{})
            picked=answer.get("choice")
            probabilities=answer.get("probabilities",{})
            meta["probabilities"]=probabilities
            if picked in self.labels and picked in options and probabilities.get(picked,0)>=.55:
                selected,score,source=picked,probabilities[picked],"jev"
            elif picked=="none" and probabilities.get("none",0)>=.55:
                selected=None
        trace.add("section","Раздел загруженного каталога",self.labels[selected] if selected else "Предложено уточнить раздел",
                  candidates=dict(candidates),source=source,probability=score,calls=[meta] if smart else [])
        return selected,[k for k,_ in candidates[:3]],source,score
