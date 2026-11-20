import re
from rapidfuzz import process
from rapidfuzz.distance import DamerauLevenshtein
from kuznitsa.text import lemma,tokens
from .quantities import TENS,NUMBERS

EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,."
RU = "йцукенгшщзхъфывапролджэячсмитьбю"
LAYOUT = str.maketrans(EN+RU,RU+EN)
TRANS = dict(zip("абвгдеёзийклмнопрстуфыэ","abvgdeeziiklmnoprstufye"))
TRANS.update(ж="zh",х="kh",ц="ts",ч="ch",ш="sh",щ="sch",ю="yu",я="ya",ь="",ъ="")
STOP = set("на в с для и а по от до не без кроме или купить хочу под на год года лет мес месяца рублей руб тысяч лицензию программа программное обеспечение ноутбук принтер картридж что как мне нужен через софт".split())


def repair(q,lex):
    words = tokens(q)
    changes = []
    known = lambda w:w in lex.words or (lemma(w),) in lex.entries or w in STOP or w in TENS or w in NUMBERS
    fixed = []
    for w in words:
        to,kind = w,None
        if not known(w) and not re.search(r"\d|[.:#+-]",w):
            layout = w.translate(LAYOUT)
            if known(layout) and len(w)>=2:
                to,kind = layout,"layout"
            elif w in lex.compact:
                to,kind = lex.compact[w],"split"
            elif len(w)>=4:
                latin = "".join(TRANS.get(ch,ch) for ch in w)
                if latin!=w and latin in lex.words:
                    to,kind = latin,"translit"
                else:
                    hit = process.extractOne(w,lex.spell_words,scorer=DamerauLevenshtein.distance,
                                             score_cutoff=1 if len(w)<8 else 2)
                    if hit:
                        to,kind = hit[0],"typo"
        fixed.extend(to.split())
        if kind:
            changes.append({"from":w,"to":to,"kind":kind})
    return fixed,changes
