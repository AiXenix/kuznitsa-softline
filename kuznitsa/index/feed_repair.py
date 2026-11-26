"""Восстановление написания с подтверждением всех частей запроса по снимку."""
from collections import defaultdict
from functools import lru_cache
import re

from kuznitsa.text import lemma,normalize,tokens
from kuznitsa.understand.repair import LAYOUT,repair,typo_matcher
from kuznitsa.understand.spell_index import roman


def compact(text):
    return "".join(re.findall(r"[а-яa-z0-9]+",normalize(text)))


def roman_keys(text):
    for ending in ("й","y"):
        yield roman(text.replace("й",ending))


# Обозначения редакций, которые встречаются в русских и английских названиях.
EDITIONS={"специальный":"special","стандартный":"standard","профессиональный":"professional",
          "pro":"professional","профессиональная":"professional"}


class FeedRecovery:
    def __init__(self,index,kb):
        self.index=index
        self.spell=typo_matcher(w for w in index.vocab if len(w)>=4)
        self.names=defaultdict(set)
        self.titles=defaultdict(list)
        for card in index.cat.cards.values():
            for form in set(roman_keys(compact(card.title))):
                self.titles[form].append(card.id)
            for name in (card.title,card.offers[0].vendor or ""):
                parts=tokens(name.removeprefix("Программа "))[:8]
                for end in range(1,len(parts)+1):
                    phrase=" ".join(parts[:end])
                    key=compact(phrase)
                    if len(key)<3:continue
                    for form in set(roman_keys(key)):
                        self.names[form].add(phrase)
        self.aliases={}
        for phrase,(field,ids) in index.slang.items():
            if field in {"families","vendors"}:
                for form in roman_keys(compact(phrase)):
                    self.aliases.setdefault(form,phrase)
        # У класса может быть разговорное название, а у линейки — только описание назначения.
        self.capabilities=defaultdict(set)
        self.descriptions=[]
        self.russian_terms={}
        for fid,row in kb.rows["families"].items():
            ids=index.tags["families"].get(fid)
            if not ids:continue
            for phrase in [row.get("summary",""),*row.get("use_cases",[])]:
                description=len(self.descriptions)
                terms=set()
                for w in tokens(phrase or ""):
                    if len(w)<3 or not re.fullmatch("[а-я]+",w):continue
                    word=self.feature(w)
                    terms.add(word)
                    self.capabilities[word].add(description)
                    for form in roman_keys(w):self.russian_terms[form]=w
                self.descriptions.append((len(terms),ids))
        self.confirmed=lru_cache(512)(self.confirmed)
        self.full_name=lru_cache(512)(self.full_name)

    @staticmethod
    def feature(word):
        root=lemma(word)
        if root in {"сетевой","сеть"}:return "сеть"
        if root in {"сканер","сканирование","сканировать"}:return "сканер"
        return root

    def full_name(self,raw):
        for text,kind in [(raw,"translit"),(raw.translate(LAYOUT),"layout")]:
            for key in roman_keys(compact(text)):
                ids=self.titles.get(key)
                if ids:
                    order=sorted(ids,key=lambda i:(normalize(self.index.cat.cards[i].title)==normalize(text),
                                                    self.index.quality[i],i),reverse=True)
                    return order,self.index.cat.cards[order[0]].title,kind
        return (),raw,None

    def confirmed(self,phrase):
        index=self.index
        terms=tokens(normalize(phrase))
        from .feed import STOP
        terms=[lemma(w) for w in terms if w not in STOP]
        if not terms:return (),phrase
        pools=[]
        for term in terms:
            variants={term}
            if term in EDITIONS:variants.add(EDITIONS[term])
            if not any(v in index.postings for v in variants) and len(term)>=4 and term.isalpha():
                distance=1 if len(term)<8 else 2
                variants.update(w for w,_,_ in self.spell(term,6,distance))
            pool=set().union(*(index.postings.get(v,()) for v in variants))
            if not pool:return (),phrase
            pools.append((variants,pool))
        hits=set.intersection(*(p for _,p in pools))
        if not hits:return (),phrase
        def rank(cid):
            title=tokens(index.cat.cards[cid].title)
            title_terms={lemma(w) for w in title}
            return (sum(bool(opts & title_terms) for opts,_ in pools),
                    sum(w in title_terms for w in terms),index.line_popularity.get(cid,()),-len(title),index.quality[cid],cid)
        ordered=tuple(sorted(hits,key=rank,reverse=True))
        available=index.terms[ordered[0]]
        spelling=" ".join(term if term in available else min(variants & available)
                          for term,(variants,_) in zip(terms,pools))
        return ordered,spelling

    def lookup(self,engine,base):
        index=self.index
        if len(base)>150 or len(base.split())>10:return (),base,None
        # Известное полное имя снятой линейки нельзя заменять соседним по опечатке.
        if base in index.unsold_sections or base in index.replacements:return (),base,None
        forms=[(base,"typo"),(base.translate(LAYOUT),"layout")]
        if any(ch.isalpha() for ch in base):
            fixed,changes=repair(base,engine.lex)
            if changes:
                kinds={c["kind"] for c in changes}
                forms.append((" ".join(fixed),changes[0]["kind"] if len(kinds)==1 else "catalog"))
        for phrase,kind in forms:
            key=compact(phrase)
            if len(key)<3:continue
            for form in roman_keys(key):
                alias=self.aliases.get(form)
                if alias:
                    return index.slang[alias][1],alias,"translit" if kind=="typo" else kind
                for name in sorted(self.names.get(form,()),key=lambda s:(s!=phrase,len(s),s)):
                    hits=index.products(name)
                    if hits:return hits,name,"translit" if kind=="typo" and name!=phrase else kind
            mapped,_=engine._phrases.apply(phrase)
            mapped=index.correct(mapped)
            hits,spelling=self.confirmed(mapped)
            if hits:return hits,spelling,kind
        for phrase,kind in forms:
            decoded=[self.russian_terms.get(w) or engine.lex.roman.get(w,w) for w in tokens(phrase)]
            terms={self.feature(w) for w in decoded}
            if len(terms)<2 or not all(w in self.capabilities for w in terms):continue
            descriptions=set.intersection(*(self.capabilities[w] for w in terms))
            supported={}
            for i in descriptions:
                length,ids=self.descriptions[i]
                for cid in ids:supported[cid]=min(length,supported.get(cid,length))
            if supported:
                ids=sorted(supported,key=lambda cid:(-supported[cid],index.quality[cid],cid),reverse=True)
                return tuple(ids)," ".join(decoded),"translit" if decoded!=tokens(phrase) else kind
        return (),base,None
