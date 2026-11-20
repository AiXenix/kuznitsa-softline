from bisect import bisect_left
from time import perf_counter
from kuznitsa.understand.repair import LAYOUT
from kuznitsa.text import normalize


class SuggestIndex:
    def __init__(self,lex,names):
        self.phrases=sorted(lex.phrases)
        self.entries=lex.phrases
        self.names=names

    def prefix(self,q):
        groups={"family":{},"vendor":{},"category":{}}
        for i in range(bisect_left(self.phrases,q),len(self.phrases)):
            phrase=self.phrases[i]
            if not phrase.startswith(q):
                break
            for kind,ident in self.entries[phrase]:
                rows=groups.get(kind)
                if rows is not None and len(rows)<6:
                    label=self.names[kind].get(ident)
                    if label:
                        rows[ident]=dict(text=label,kind=kind,meta=ident)
        return [dict(type=g,title=title,items=list(groups[k].values()))
                for k,g,title in [("family","products","Продукты"),("category","categories","Категории"),("vendor","vendors","Вендоры")] if groups[k]]


def suggest(engine,q,profile_id="guest",category=None):
    start=perf_counter()
    norm=normalize(q)
    groups=engine.suggestions.prefix(norm) if norm else []
    corrected=None
    if norm and not groups:
        translated=norm.translate(LAYOUT)
        groups=engine.suggestions.prefix(translated)
        if groups:
            corrected=translated
    return dict(q=q,corrected=corrected,groups=groups,ms=round((perf_counter()-start)*1000,2))
