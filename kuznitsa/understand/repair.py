import re
from bisect import bisect_left
from functools import lru_cache
from rapidfuzz import process
from rapidfuzz.distance import DamerauLevenshtein
from kuznitsa.text import lemma,tokens,morphology
from .quantities import TENS,NUMBERS
from .spell_index import roman

EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,."
RU = "йцукенгшщзхъфывапролджэячсмитьбю"
LAYOUT = str.maketrans(EN+RU,RU+EN)
TRANS = dict(zip("абвгдеёзийклмнопрстуфыэ","abvgdeeziiklmnoprstufye"))
TRANS.update(ж="zh",х="kh",ц="ts",ч="ch",ш="sh",щ="sch",ю="yu",я="ya",ь="",ъ="")
STOP = set("на в с для и а по от до не без кроме или купить хочу под на год года лет мес месяца шт штук рублей руб тысяч лицензию программа программное обеспечение ноутбук принтер картридж что как мне нужен через софт".split())


def completions(prefix,lex):
    if len(prefix)<3:
        return []
    start=bisect_left(lex.headwords,prefix)
    return [w for w in lex.headwords[start:start+40] if w.startswith(prefix) and len(w)<=len(prefix)+6]


def typo_matcher(words):
    """Длина ограничивает расстояние Дамерау. Порядок при равенстве сохраняется."""
    by_length={}
    for word in words:
        by_length.setdefault(len(word),[]).append(word)

    @lru_cache(128)
    def candidates(size,distance):
        return sorted(word for n in range(size-distance,size+distance+1) for word in by_length.get(n,()))

    @lru_cache(4096)
    def nearest(text,limit,distance):
        return process.extract(text,candidates(len(text),distance),scorer=DamerauLevenshtein.distance,
                               limit=limit,score_cutoff=distance)
    return nearest


def repair(q,lex):
    known=lambda w:w in lex.words or (lemma(w),) in lex.entries or w in STOP or w in NUMBERS or w in TENS
    q=re.sub(r"(\d)(?=(?:pk|gr|ядра|ядер|хост|процессор|rjvg|gjkmp))",r"\1 ",q)
    fixed=[]
    changes=[]
    for fragment in q.split():
        # Пунктуация внутри слова бывает буквой русской клавиатуры.
        translated=fragment.translate(LAYOUT)
        if re.search(r"[,\[\];']",fragment) and translated.isalpha() and known(translated):
            fixed.append(translated)
            changes.append({"from":fragment,"to":translated,"kind":"layout","candidates":[translated]})
            continue
        if "-" in fragment and fragment not in lex.phrases:
            candidate=getattr(lex,"compounds",{}).get(fragment.replace("-",""))
            if candidate:
                target,kind=candidate
                fixed.extend(target.split())
                changes.append({"from":fragment,"to":target,"kind":kind,"candidates":[target]})
                continue
        for w in tokens(fragment):
            # Склейка известных слов перед тиражом. Не разделяем артикулы и версии.
            combined=re.fullmatch(r"([а-я]{9,64})([0-9]{1,7})?",w)
            if combined and w not in lex.words:
                body,n=combined.groups()
                parts={0:[]}
                for end in range(3,len(body)+1):
                    for start in sorted(parts):
                        piece=body[start:end]
                        if len(piece)>=3 and piece in lex.words:
                            parts[end]=parts[start]+[piece]
                            break
                if len(parts.get(len(body),[]))>=2:
                    split=parts[len(body)]+([n] if n else [])
                    fixed.extend(split)
                    changes.append({"from":w,"to":" ".join(split),"kind":"split","candidates":[" ".join(split)]})
                    continue
            options={}
            def add(word,kind,base):
                if word!=w:
                    score=base+.012*lex.popularity.get(word,0)
                    if word not in options or score>options[word][0]:
                        options[word]=(score,kind)
            if fixed and fixed[-1] in ("аналог","вместо","замена","дешевле") and not lex.entries.get((lemma(w),)):
                for ending in ("ого","ов","а","я"):
                    if w.endswith(ending) and len(w)-len(ending)>=4:
                        base=w[:-len(ending)]
                        if any(k in ("family","vendor") for k,_,_ in lex.entries.get((lemma(base),),())):
                            add(base,"inflection",1.0)
            if w=="pk" and fixed and fixed[-1].isdigit():add("пк","translit",1.1)
            if any(c.isdigit() for c in w) and w.translate(LAYOUT) in lex.words:add(w.translate(LAYOUT),"layout",1.)
            if w in lex.typos:
                add(lex.typos[w],"typo",1.2)
            if not known(w) and w.isalpha():
                layout=w.translate(LAYOUT)
                if len(w)>=2 and known(layout):
                    add(layout,"layout",1 if layout in lex.words or layout in STOP else .77)
                if w in lex.compact:
                    add(lex.compact[w],"split",1)
                if w in lex.roman:
                    add(lex.roman[w],"translit",1)
                if roman(w)!=w and roman(w) in lex.words and not lex.entries.get((lemma(roman(w)),),[("","","")])[0][2]=="phonetic":
                    add(roman(w),"translit",.96)
                common=w in STOP or bool(re.fullmatch("[а-я]+",w) and morphology().word_is_known(w))
                if not common or len(w)==3:
                    for prefix,kind in [(w,"prefix"),(layout,"layout")]:
                        for cand in completions(prefix,lex):
                            add(cand,kind,.89-.018*(len(cand)-len(w)))
                if len(w)>=4:
                    for cand,dist,_ in lex.nearest_typo(w,12,1 if len(w)<8 else 2):
                        if not common or sorted(w)==sorted(cand) or cand in lex.headword_set and (w.startswith(cand) or cand.startswith(w)) and len(w)>=5:
                            add(cand,"typo",.94-.06*dist+.045*(cand in lex.phrases)+.035*(cand in lex.primary_words))
                    if not common and len(w)>=6:
                        for cand,_,_ in lex.nearest_typo(layout,4,1):
                            add(cand,"layout",.86)
            if options:
                choices=sorted(options,key=lambda k:(-options[k][0],k))
                winner=choices[0]
                changes.append({"from":w,"to":winner,"kind":options[winner][1],"candidates":choices[:4],
                                "scores":{option:round(options[option][0],3) for option in choices[:4]}})
                fixed.extend(winner.split())
            else:
                fixed.append(w)
    return fixed,changes
