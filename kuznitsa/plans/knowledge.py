from collections import defaultdict
from functools import lru_cache
from math import log
from kuznitsa.text import tokens,lemma,normalize

GROUPS={"use_case":"use_cases","role":"roles","industry":"industries","faq":"faq","category":"categories"}
STOP=set("для под программа программный по чем чтобы как есть можно что какой на это при ли в и из от о".split())


class KnowledgeIndex:
    def __init__(self,kb,lex):
        self.kb=kb
        self.postings={}
        for kind,group in GROUPS.items():
            posting=defaultdict(list)
            for ident,row in kb.rows[group].items():
                texts=[row.get("title",""),*row.get("aliases",[]),*row.get("phrases",[]),*row.get("questions",[]),*row.get("synonyms",[])]
                for term in set(lemma(w) for t in texts for w in tokens(t))-STOP:
                    posting[term].append(ident)
            self.postings[kind]=posting
        for group in ("roles","industries","use_cases"):
            for row in kb.rows[group].values():
                for slot in row.get("slots",[row]):
                    if slot.get("families"):
                        continue
                    families=[]
                    for name in slot.get("products",[]):
                        for _,_,entries in lex.match(tokens(name)):
                            families.extend(v for k,v,_ in entries if k=="family")
                    slot["families"]=list(dict.fromkeys(families))

    @lru_cache(512)
    def nearest(self,kind,text):
        score=defaultdict(float)
        n=len(self.kb.rows[GROUPS[kind]])
        for w in set(map(lemma,tokens(text)))-STOP:
            hits=self.postings[kind].get(w,[])
            for fid in hits:
                score[fid]+=log(1+n/len(hits))
        return sorted(score,key=score.get,reverse=True)[:8]
