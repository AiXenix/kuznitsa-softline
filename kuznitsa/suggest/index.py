from bisect import bisect_left
from collections import Counter,defaultdict
from functools import lru_cache
from time import perf_counter
import re

from rapidfuzz import process
from rapidfuzz.distance import DamerauLevenshtein
from kuznitsa.understand.repair import LAYOUT
from kuznitsa.understand.spell_index import roman
from kuznitsa.text import normalize,tokens


@lru_cache(262144)
def key(text):
    return re.sub(r"[^а-яa-z0-9]+"," ",normalize(text)).strip()


GROUPS={"family":("products","Продукты"),"category":("categories","Категории"),"vendor":("vendors","Вендоры"),
        "query":("queries","Поисковые запросы"),"answer":("answers","Ответы на вопросы")}


class SuggestIndex:
    def __init__(self,lex,names,kb=None,catalog=None,recent=()):
        rows=defaultdict(dict)
        self.aliases=defaultdict(set)
        self.translit={}
        self.family_rank={}
        self.feed_suggest=None
        if catalog and getattr(catalog,"is_feed",False) and getattr(catalog,"feed",None) and kb:
            from kuznitsa.plans.feed_suggest import FeedSuggestIndex
            self.feed_suggest=FeedSuggestIndex(catalog.feed,kb,lex)
        if catalog:
            for fid,cids in catalog.by["family"].items():
                offers=[o for cid in cids for o in catalog.cards[cid].offers]
                row=kb.rows["families"].get(fid,{})
                audiences=set(row.get("license",{}).get("audiences",[]))
                vendor=kb.rows["vendors"].get(row.get("vendor"),{})
                core=(vendor.get("categories") or [None])[0]==row.get("category")
                self.family_rank[fid]=(row.get("popularity",3),max((o.popularity for o in offers),default=0),core,
                                       (row.get("category") or "").startswith("home_") or audiences=={"home"})

        def add(phrase,kind,ident,title,rank):
            term=key(phrase)
            if not term or not title:
                return
            item=(kind,ident,title)
            rows[term][item]=max(rank,rows[term].get(item,0))
        for phrase,refs in lex.phrases.items():
            for kind,ident in sorted(refs):
                title=names.get(kind,{}).get(ident)
                if kb and kind=="family":
                    row=kb.rows["families"].get(ident,{})
                    brand=kb.rows["vendors"].get(row.get("vendor"),{})
                    if title and key(title)==key(brand.get("name","")) and row.get("name"):
                        title=row["name"]
                if kb and kind=="vendor" and re.search("[а-я]",phrase):
                    title=kb.rows["vendors"].get(ident,{}).get("name_ru") or title
                if not title:
                    continue
                self.aliases[(kind,ident)].add(key(phrase))
                pop=kb.rows["families"].get(ident,{}).get("popularity",3) if kb and kind=="family" else 3
                add(phrase,kind,ident,title,10+pop)
                if kb and kind=="family":
                    full=kb.rows["families"].get(ident,{}).get("name","")
                    if title and key(full)!=key(title) and key(phrase) in key(full):
                        add(phrase,kind,ident,full,11+pop)
                parts=key(phrase).split()
                for i in range(1,len(parts)):
                    if len(parts[i])>=3:
                        add(" ".join(parts[i:]),kind,ident,title,pop)
                if catalog and kind in ("category","vendor"):
                    for cid in catalog.by[kind].get(ident,()):
                        c=catalog.cards[cid]
                        label=names["family"].get(c.family)
                        if label and key(label)==key(c.offers[0].vendor or ""):
                            label=c.kb.get("name") or label
                        add(phrase,"family",c.family,label,c.kb.get("popularity",3))
                if kind=="family":
                    add("аналог "+phrase,"query",ident,"аналог "+phrase,5 if len(parts)==1 else 2)
        if kb:
            for row in kb.rows["categories"].values():
                for query in row.get("typical_queries",[]):
                    add(query,"query",query,query,10)
            # Из истории публикуем только название известного класса и типовое
            # условие покупки, без свободного текста организации.
            counts=Counter(key(q) for q in recent if q)
            for q,n in counts.most_common():
                match=re.fullmatch(r"(.+?) (на \d{1,5} (?:пк|мест|юзеров)|для (?:бизнеса|школы|организаций)|из реестра)",q)
                if match and any(k=="category" for k,_ in lex.phrases.get(match[1],())):
                    add(q,"query",q,q,12+min(n,12))
            for row in kb.rows["roles"].values():
                for phrase in row.get("aliases",[]):
                    if phrase.startswith("арм "):
                        query="комплект "+phrase[4:]
                        add(query,"query",row["id"],query,8)
            for group,kind,field in [("faq","answer","questions"),("use_cases","query","phrases"),("compliance","query","aliases"),("roles","query","aliases")]:
                for ident,row in kb.rows[group].items():
                    for phrase in row.get(field,[]):
                        add(phrase,kind,ident,phrase,5)
        self.phrases=sorted(rows)
        self.entries=rows
        for phrase in sorted(rows,key=lambda s:(len(s),s)):
            if re.search("[а-я]",phrase):
                form=roman(phrase)
                for alt in (form,form.replace("i","y"),form.replace(" ","")):
                    self.translit.setdefault(alt,phrase)
        self.roman_keys=sorted(self.translit)

    def prefix(self,q,segment="smb",owned=()):
        groups=defaultdict(dict)
        for i in range(bisect_left(self.phrases,q),len(self.phrases)):
            phrase=self.phrases[i]
            if not phrase.startswith(q):
                break
            for (kind,ident,label),rank in self.entries[phrase].items():
                if kind=="family" and ident in self.family_rank:
                    pop,sales,core,home=self.family_rank[ident]
                    score=(int(ident in owned)*2+int(phrase==q and key(label)==q),home if segment=="individual" else not home,
                           pop,core,rank,sales,-len(label),label)
                else:
                    score=(rank+(phrase==q),-len(phrase),label)
                if ident not in groups[kind] or score>groups[kind][ident][0]:
                    groups[kind][ident]=(score,dict(text=label,kind=kind,meta=ident))
        return [dict(type=g,title=t,items=[v[1] for v in sorted(groups[k].values(),key=lambda r:r[0],reverse=True)[:6]])
                for k,(g,t) in GROUPS.items() if groups[k]]

    def complete(self,q,profile=None):
        segment=profile.segment if profile else "smb"
        owned={p.get("family_id") for p in profile.owned} if profile else set()
        groups=self.prefix(q,segment,owned)
        # Латинское написание русского слова может уже совпасть с индексированным алиасом.
        roman_key=self.translit.get(q)
        if groups:
            return groups,(roman_key if roman_key and re.fullmatch("[a-z ]+",q) and
                not any(key(i["text"]).startswith(q) for g in groups for i in g["items"]) else None)
        layout=key(q.translate(LAYOUT))
        if layout and layout!=q and (groups:=self.prefix(layout,segment,owned)):
            return groups,layout
        start=bisect_left(self.roman_keys,q)
        if start<len(self.roman_keys) and self.roman_keys[start].startswith(q):
            corrected=self.translit[self.roman_keys[start]]
            return self.prefix(corrected,segment,owned),corrected
        if len(q)>=4:
            matches=process.extract(q,self.phrases,scorer=DamerauLevenshtein.distance,score_cutoff=1 if len(q)<8 else 2,limit=5)
            if matches:
                corrected=min(matches,key=lambda m:(m[1],-max(self.entries[m[0]].values()),m[0]))[0]
                return self.prefix(corrected,segment,owned),corrected
        return [],None


def suggest(engine,q,profile_id="guest",category=None):
    start=perf_counter()
    engine._rules()
    norm=key(q)
    profile=engine.clients.get(profile_id)
    if getattr(engine.catalog,"is_feed",False):
        from kuznitsa.plans.feed_suggest import suggestions
        return suggestions(engine,q,norm,profile or engine.clients["guest"],start)
    groups,corrected=engine.suggestions.complete(norm,profile) if norm else ([],None)
    if corrected:
        groups.insert(0,dict(type="corrections",title="Исправление написания",items=[dict(kind="correction",text=corrected,q=corrected,meta="repair")]))
    if norm and len(norm)>=3 and any(c.isdigit() for c in norm):
        codes=engine.catalog.prefix_skus(norm,5)
        if codes:
            groups.insert(0,dict(type="products",title="Артикулы",items=[dict(text=o.sku,kind="sku",meta=o.card_id) for o in codes]))
    if profile and norm:
        renewal="продлить".startswith(norm) or norm.startswith("продлить ")
        prefix=norm.partition(" ")[2] if renewal else corrected or norm
        items=[]
        for owned in sorted(profile.owned,key=lambda row:row.get("expires_in_days") if row.get("expires_in_days") is not None else float("inf")):
            if renewal and owned.get("expires_in_days") is None:
                continue
            fid=owned.get("family_id")
            title=owned.get("product") or engine.names["family"].get(fid)
            row=engine.kb.rows["families"].get(fid,{})
            aliases=engine.suggestions.aliases.get(("family",fid),set()) | engine.suggestions.aliases.get(("vendor",row.get("vendor")),set())
            if title and (not prefix or any(alias.startswith(prefix) for alias in aliases)):
                query="Продлить "+title
                days=owned.get("expires_in_days")
                hint=(f"До окончания лицензии {days} дн." if days is not None and days>=0 else
                      "Срок лицензии истёк" if days is not None else "Лицензия организации")
                items.append(dict(text=query if days is not None else title,kind="license",meta=owned.get("card_id") or fid,
                                  hint=hint,q=query if days is not None else title))
        if items:
            groups.insert(0 if renewal else len(groups),dict(type="licenses",title="Ваши лицензии",items=items[:6]))
    return dict(q=q,corrected=corrected,groups=groups,ms=round((perf_counter()-start)*1000,2))
