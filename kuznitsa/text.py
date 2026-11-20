import re
import unicodedata
from functools import lru_cache
from pymorphy3 import MorphAnalyzer

LOOK = str.maketrans("авекмнорстху","abekmhopctxy")
TOKEN = re.compile(r"c\+\+|c#|\.net|[\w]+(?:[.:-][\w]+)*")


def normalize(s):
    s = unicodedata.normalize("NFKC", s).lower().replace("ё","е")
    s = re.sub("[‐‑–—−]", "-", s)
    s = re.sub(r"\b1[cс]:?", "1с ", s)
    s = re.sub(r"\b(win(?:dows)?|office)\s*(?=\d)",lambda m:"windows " if m[1].startswith("win") else "office ",s)
    s = re.sub(r"\b([mo])365\b",lambda m:("office" if m[1]=="o" else "microsoft")+" 365",s)
    s = re.sub(r"(\d)(пк|мес|комп|лет|год|шт|узл|польз|юзер)",r"\1 \2",s)
    s = re.sub(r"[a-zа-я0-9]+",lambda m:m[0].translate(LOOK) if re.search("[a-z]",m[0]) else m[0],s)
    s = re.sub(r"(windows \d+)(pro|home|enterprise)\b",r"\1 \2",s)
    return " ".join(s.split())


def sku_key(s):
    return re.sub("[^a-z0-9]","",s.lower().translate(LOOK))


@lru_cache(1)
def morphology():
    return MorphAnalyzer()


@lru_cache(60000)
def lemma(w):
    if re.fullmatch("[а-я]+",w) and len(w)>2:
        return morphology().parse(w)[0].normal_form.replace("ё","е")
    return w


def tokens(s):
    return TOKEN.findall(normalize(s))
