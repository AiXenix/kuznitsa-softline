"""Обратный указатель русских произношений слов из каталога."""
from collections import defaultdict
from functools import lru_cache
import re
from rapidfuzz import fuzz,process
from kuznitsa.understand.spell_index import cyrillic, roman


def sound_key(s):
    s=s.lower().replace("й","и").replace("э","е").replace("ц","с").replace("ь","")
    return re.sub(r"(.)\1+",r"\1",s)


def pronunciations(word):
    yield cyrillic(word)
    text=word
    for a,b in (("special","спешл"),("micro","майкро"),("small","смол"),("zoom","зум"),
                ("any","эни"),("team","тим"),("view","вью"),("auto","авто"),("acle","акл"),
                ("iere","ьер"),("ight","айт"),("igh","ай"),("tion","шн"),("urity","ьюрити"),("ice","ис"),
                ("ff","ф"),("ea","и"),("ai","ей"),("ay","ей"),("oa","оу"),("ph","ф")):
        text=text.replace(a,b)
    yield cyrillic(text)
    if len(word)<=5:
        yield word.translate(str.maketrans("abcdefghijklmnopqrstuvwxyz","абцдефгхийклмнопкрстуввхыз"))


class Sounds:
    def __init__(self,vocab):
        self.index=defaultdict(set)
        self.latin=defaultdict(set)
        for word in vocab:
            if re.fullmatch("[a-z]{2,}",word):
                for p in pronunciations(word):
                    self.index[sound_key(p)].add(word)
            elif re.fullmatch("[а-я]{2,}",word):
                self.latin[roman(word)].add(word)
        self.keys=sorted(self.index)
        self.lookup=lru_cache(2048)(self.lookup)

    def lookup(self,word):
        if word in self.latin:return sorted(self.latin[word])
        if not re.fullmatch("[а-я]{2,}",word):return ()
        key=sound_key(word)
        if key in self.index:return sorted(self.index[key])
        if len(key)<5:return ()
        found=process.extractOne(key,self.keys,scorer=fuzz.ratio,score_cutoff=84)
        return sorted(self.index[found[0]]) if found else ()
