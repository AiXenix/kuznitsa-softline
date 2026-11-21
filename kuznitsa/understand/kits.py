"""Поиск адресата комплекта по названиям, речевым вариантам и назначению слотов."""
import re
from collections import Counter
from functools import lru_cache
from math import log1p
import numpy as np
from rapidfuzz import process,fuzz
from kuznitsa.text import tokens,lemma,normalize
from kuznitsa.llm.decisions import choice

STOP=set("по для на в из и к с под программа программный обеспечение софт прога лицензия рабочий место комплект набор стек арм бизнес нужно нужный какой что поставить взять купить закупить человек пользователь сотрудник пк компьютер автоматизация организация это мы наш новый хотеть подобрать".split())
CUE=re.compile(r"\b(комплект|набор|софт|прог[аиуы]|программы|арм|стек|оснастить|автоматизация|какие|закупить|что нужно|что поставить|рабочее место|по для|по в|из программ|из лицензий|инструмент\w*|открыва\w*|запуска\w*|организовать|оснаща\w*|оборуду\w*|переход\w*|стек|чем оснастить|что закупить|какое по|какой софт|что (?:ставить|купить|взять)|рабоч\w* мест\w*)\b")


def terms(s):
    return {v for w in tokens(s) if (v:=lemma(w)) not in STOP and not v.isdigit() and len(v)>1}


@lru_cache(8192)
def dative(word):
    from kuznitsa.text import morphology
    return morphology().parse(word)[0].tag.case=="datv"


class KitIndex:
    def __init__(self,kb):
        self.rows={}
        self.phrases={}
        self.notes={}
        self.exact={}
        self.df=Counter()
        self.docs=[]
        self.owners=[]
        for kind,group in (("role","roles"),("industry","industries")):
            for ident,row in kb.rows[group].items():
                key=(kind,ident)
                self.rows[key]=row
                labels=[str(value) for value in [row["title"],*row.get("aliases",[])]]
                self.phrases[key]=[terms(s) for s in labels]
                self.df.update(set.union(*self.phrases[key]))
                notes=" ".join(x.get("note","") for x in row.get("slots",[]))
                self.notes[key]=terms(notes)
                self.exact[key]={normalize(s) for s in labels}
                for desc in (row["title"]," · ".join(labels[:5]),row["title"]+". "+notes[:350]):
                    self.docs.append(desc)
                    self.owners.append(key)
        self.vocabulary={k:set.union(*phrases) for k,phrases in self.phrases.items()}
        self.rarity={w:log1p(len(self.rows)/(1+count)) for w,count in self.df.items()}
        self.denominators={k:[(2+sum(self.rarity[w] for w in phrase))**.65 for phrase in phrases]
                           for k,phrases in self.phrases.items()}
        self.candidates=lru_cache(512)(self.candidates)
        self.vocab=sorted(self.df)
        self.matrix=None

    def attach(self,dense,cfg):
        if dense.matrix is not None and self.docs:
            self.matrix=dense.cached_embeddings(cfg,self.docs)

    def candidates(self,text,dense):
        q=terms(text)
        if not q:
            return []
        weights={w:1. for w in q}
        for w in q-set(self.df):
            if len(w)<4:
                continue
            for v,score,_ in process.extract(w,self.vocab,scorer=fuzz.ratio,limit=2,score_cutoff=78):
                weights[v]=max(weights.get(v,0),.75*score/100)
        semantic={}
        if self.matrix is not None:
            sims=np.einsum("ij,j->i",self.matrix,dense.encode(" ".join(sorted(q))))
            for k,v in zip(self.owners,sims):
                semantic[k]=max(semantic.get(k,0),float(v))
        rank=[]
        for k in self.rows:
            best=0.
            for phrase,denominator in zip(self.phrases[k],self.denominators[k]):
                hits=weights.keys() & phrase
                if hits:
                    overlap=sum(weights[w]*self.rarity[w] for w in hits)
                    best=max(best,overlap/denominator)
            exact=text in self.exact[k]
            score=best+.85*semantic.get(k,0)+.08*min(4,len(q & self.notes[k]))+6*exact
            if len(q)>=2 and q<=self.vocabulary[k]:
                score+=.85
            rank.append((score,k))
        scores={k:s for s,k in rank}
        for i,(s,k) in enumerate(rank):
            parent=(k[0],self.rows[k].get("parent"))
            if parent in scores and s>.9 and s>=scores[parent]-.15:
                rank[i]=(max(s,scores[parent]+.05),k)
        return sorted(rank,reverse=True)[:8]

    def pick(self,engine,req,text,entities,f,intent,deadline,sid,calls,can_ask):
        matched=[(e["type"],e["id"]) for e in entities if e["type"] in ("role","industry")]
        code=re.search(r"\bоквэд\s*[:№]?\s*(\d+(?:\.\d+)*)",text)
        if code:
            prefix=code[1]
            while prefix:
                row=engine.kb.rows["okved"].get(prefix)
                if row:
                    return ("industry",row["industry"]),[],("okved",prefix,row["title"]),1.
                prefix=prefix[:-1].rstrip(".")
            return None,[],("okved",code[1],None),0.
        words=tokens(text)
        if len(entities)==2 and {e["type"] for e in entities}=={"category","vendor"}:
            first,last=sorted(e["span"] for e in entities)
            if first[0]==0 and first[1]==last[0] and last[1]==len(words):
                return None,[],None,0.
        for entity in entities:
            if entity["type"]!="role":
                continue
            end=entity["span"][1]
            if any(e["type"]=="industry" and e["span"][0]>=end for e in entities) and words[end:end+1] in (["в"],["на"],["при"]):
                return ("role",entity["id"]),[],None,.98
        if matched and intent=="role_kit" and len(set(matched))==1 and matched[0][1].startswith("kit_"):
            key=matched[0]
            if terms(text)<=self.vocabulary[key]:
                return key,[],None,.98
        beneficiary=len(words)>=3 and any(len(w)>4 and w.isalpha() and dative(w) for w in words)
        cue=CUE.search(text)
        if intent in ("question","account","compare","sku") or f.get("action") and (f.get("family") or f.get("vendor")):
            return None,[],None,0.
        if intent=="compliance" and any(e["type"]=="compliance" for e in entities) and not re.search(r"комплект|оснастить|набор|открыва",text):
            return None,[],None,0.
        if intent=="task" and not cue:
            return None,[],None,0.
        if not matched and not cue and not beneficiary:
            return None,[],None,0.
        if not matched and not terms(text):
            return None,[],None,0.
        if any(e["type"] in ("family","category","vendor") and e["span"][0]==0 for e in entities) and not CUE.match(text) and not (cue and len(words)>=5) and not (beneficiary and len(words)>=5):
            return None,[],None,0.
        if not cue and not beneficiary and matched and intent not in ("role_kit","industry","service") and text not in self.exact.get(matched[0],{}):
            return None,[],None,0.
        if (f.get("action") and not cue) or re.search(r"\b(не |сертификат|почему|чем отличается)",text):
            return None,[],None,0.
        ranked=self.candidates(text,engine.catalog.dense)
        if not ranked:
            return None,[],None,0.
        score,best=ranked[0]
        gap=score-(ranked[1][0] if len(ranked)>1 else 0)
        if not matched and not cue and (score<1.25 or gap<.15):
            return None,[],None,0.
        if not matched and re.match(r"^(?:софт|программы?|по) для ",text) and any(e["type"] in ("family","category","use_case") for e in entities) and score<1.55:
            return None,[],None,0.
        if best[1].startswith("kit_") and re.match(r"^(софт|по|программы) (для|в) ",text):
            industry=next(((s,k) for s,k in ranked if k[0]=="industry" and s>=score-.65),None)
            if industry:
                score,best=industry
                # Покупатель назвал организацию. Похожий комплект её открытия
                # подходит только при явном запросе на открытие или оснащение.
                ranked=[(s,k) for s,k in ranked if not k[1].startswith("kit_")]
        if score<.62:
            return None,[],None,0.
        confidence=min(.99,.48+.11*score+.20*gap)
        if can_ask and text not in self.exact[best]:
            selected,probability=self.ask(engine.decisions,ranked,text,req.model_source,deadline,sid,calls)
            if selected:
                return selected,[],None,probability
            if probability>=.55 and not matched:
                return None,[key for _,key in ranked[:3]],None,probability
        supported=len(set(matched))==1 and best in matched
        if (score>=1.05 and (gap>=.10 or supported)) or (score>=.82 and gap>=.20):
            return best,[],None,confidence
        if intent in ("role_kit","industry") and not matched and score<1.05:
            return None,[],None,0.
        return None,[k for _,k in ranked[:3]],None,confidence

    def ask(self,decisions,ranked,text,source,deadline,sid,calls):
        criteria={}
        keys={}
        for _,key in ranked:
            kind,ident=key
            row=self.rows[key]
            group="Профессия" if kind=="role" else "Отрасль"
            note=next((slot.get("note","") for slot in row.get("slots",[])),"")
            criteria[ident]=f"{row['title']} · {group} · {note}"
            keys[ident]=key
        criteria["none"]="Ничего из перечисленного"
        question=choice("Для кого покупатель выбирает программы? Выберите самую конкретную профессию или вид организации. "
                        "Для организации в целом выбирайте отрасль.",criteria)
        answers,meta=decisions.decide_before(deadline,sid,source,"intent",{"запрос":text},{"kit":question})
        meta["probabilities"]={name:a["probabilities"] for name,a in answers.items()}
        calls.append(meta)
        answer=answers.get("kit",{})
        ident=answer.get("choice")
        probability=answer.get("probabilities",{}).get(ident,0.)
        if probability>=.55 and ident in keys:
            meta["selected_kit"]=ident
            return keys[ident],probability
        return None,probability
