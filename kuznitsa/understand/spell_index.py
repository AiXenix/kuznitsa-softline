import re
from collections import defaultdict
from kuznitsa.text import tokens,lemma

LATIN = str.maketrans(dict(zip("абвгдезийклмнопрстуфхыэ", "abvgdeziiklmnoprstufhye"),
                           ж="zh", ц="ts", ч="ch", ш="sh", щ="sch", ю="yu", я="ya", ь="", ъ=""))


def roman(word):
    return word.lower().translate(LATIN)


def spell_terms(lex):
    from .repair import LAYOUT
    compounds=defaultdict(set)
    for phrase in lex.phrases:
        if " " in phrase or "-" in phrase:
            key=re.sub(r"[- ]","",phrase)
            for form,kind in ((key,"split"),(key.translate(LAYOUT),"layout"),(roman(key),"translit"),(cyrillic(key),"translit")):
                compounds[form].add((phrase,kind))
    lex.compounds={key:min(matches) for key,matches in compounds.items() if len({p for p,_ in matches})==1}
    index=defaultdict(set)
    for phrase in lex.phrases:
        for word in tokens(phrase):
            if len(word)>=4 and word.isalpha() and word!=roman(word):
                key=roman(word)
                index[key].add(word)
                if key.endswith("yi"):
                    index[key[:-1]].add(word)
    return {key:min(words) for key,words in index.items()}

# Графемная транскрипция для поиска названий, включая английские сочетания.

_LETTERS = str.maketrans(dict(zip("abcdefghijklmnopqrstuvwxyz","абкдефгхийклмнопкрстуввкиз"), x="кс", j="дж", q="к", w="в", z="з"))
_SOUNDS = (("sch","ш"),("sh","ш"),("ch","ч"),("ph","ф"),("th","т"),("ck","к"),("qu","кв"),
           ("cy","си"),("ce","с"),("ci","си"),("cu","кю"),("oo","у"),("ee","и"),("ou","ау"),
           ("sky","ски"),("end","энд"),("oint","оинт"),("ware","вер"),("soft","софт"),
           ("ty","ти"),("yu","ю"),("ya","я"),("y","и"))


def cyrillic(text):
    for before,after in _SOUNDS:
        text=text.replace(before,after)
    return text.translate(_LETTERS)


def phonetics(lex,kb):
    from .aliases import typo_aliases
    lex.typos=typo_aliases(kb)
    original=list(lex.phrases.items())
    lex.popularity={}
    for phrase,refs in original:
        for kind,ident in sorted(refs):
            if kind not in {"family","vendor","category"}:
                continue
            row=kb.rows[{"family":"families","vendor":"vendors","category":"categories"}[kind]].get(ident,{})
            pop=row.get("popularity") or 3
            for w in tokens(phrase):
                lex.popularity[w]=max(pop,lex.popularity.get(w,0))
            if kind=="category":
                continue
            parts=phrase.split()
            latin=[]
            for w in parts:
                if not re.fullmatch("[a-z0-9.-]+",w):
                    break
                latin.append(w)
            forms={phrase}
            if len(latin)>=2 and kind=="family":
                forms.add(" ".join(latin[:2]))
            if len(latin)>=2 and len(latin)<len(parts):
                forms.add(" ".join(latin))
            for form in forms:
                for alt in {cyrillic(form),roman(form)}-{form}:
                    lex.add(alt,kind,ident,"phonetic")
    lex.primary_words={w for row in kb.rows["vendors"].values() for s in [row.get("name",""),*row.get("aliases",[])[:2]] for w in tokens(s)}
    lex.primary_words.update(w for key,items in lex.entries.items() if any(src=="catalog" for _,_,src in items) for w in key)
    lex.headwords=sorted({w for w in lex.phrases if w.isalpha() and len(w)>=3})


def brand_products(engine):
    """Начала названий линеек после марки. Предпочтение более короткому базовому имени."""
    result=defaultdict(dict)
    for fid,row in engine.kb.rows["families"].items():
        vid=row.get("vendor")
        brand=engine.kb.rows["vendors"].get(vid,{})
        marks={tuple(tokens(s)) for s in [brand.get("name",""),*brand.get("aliases",[])]}
        for alias in [row["name"],row.get("title",""),*row.get("aliases",[])]:
            words=tokens(alias)
            if len(words)<2:
                continue
            for mark in marks:
                if not mark or tuple(words[:len(mark)])!=mark:
                    continue
                for length in range(1,len(words)-len(mark)+1):
                    tail=" ".join(words[len(mark):len(mark)+length])
                    if tail in ("для","для бизнеса"):
                        continue
                    for fragment in (tail,cyrillic(tail),roman(tail)):
                        rank=(length,row.get("popularity",0),-len(words),fid)
                        if rank>result[vid].get(fragment,()):
                            result[vid][fragment]=rank
    return result


def leading_product(engine,word,vendors=()):
    """Опорная линейка для короткого, автоматически дополненного названия."""
    candidates={}
    for phrase,refs in engine.lex.phrases.items():
        if phrase.startswith(word+" "):
            for kind,fid in refs:
                if kind=="family":
                    candidates[fid]=min(len(phrase),candidates.get(fid,len(phrase)))
    for vendor in vendors:
        for fid in engine.vendor_families.get(vendor,()):
            candidates.setdefault(fid,1000)
    def rank(fid):
        row=engine.kb.rows["families"].get(fid,{})
        brand=engine.kb.rows["vendors"].get(row.get("vendor"),{})
        primary=next(iter(brand.get("categories",[])),None)
        return (row.get("category")==primary,row.get("popularity",0),-candidates[fid],fid)
    sold=(fid for fid in candidates if engine.catalog.by["family"].get(fid))
    return max(sold,key=rank,default=None)
