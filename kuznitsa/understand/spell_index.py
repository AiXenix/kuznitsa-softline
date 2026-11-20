from collections import defaultdict
from kuznitsa.text import tokens

LATIN = str.maketrans(dict(zip("абвгдезийклмнопрстуфхыэ", "abvgdeziiklmnoprstufhye"),
                           ж="zh", ц="ts", ч="ch", ш="sh", щ="sch", ю="yu", я="ya", ь="", ъ=""))


def roman(word):
    return word.lower().translate(LATIN)


def spell_terms(lex):
    index=defaultdict(set)
    for phrase in lex.phrases:
        for word in tokens(phrase):
            if len(word)>=4 and word.isalpha() and word!=roman(word):
                key=roman(word)
                index[key].add(word)
                if key.endswith("yi"):
                    index[key[:-1]].add(word)
    return {key:min(words) for key,words in index.items()}
