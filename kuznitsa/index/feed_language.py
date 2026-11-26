"""Названия классов, издателей и редакций, подтверждённые снимком магазина."""
from collections import Counter, defaultdict
import re

from kuznitsa.text import lemma
from kuznitsa.understand.quantities import NUMBERS
from .feed import STOP, words, class_words


ORDINALS=dict(zip("первый второй третий четвертый пятый шестой седьмой восьмой девятый десятый".split(),range(1,11)))
VERSION_WORD=r"(?:верси[яию]|версией|version)"
VERSION_NUMBER=r"(?:\d+(?:\.\d+)*|[а-я]+)"
DESCRIPTORS=("ос","скзи","криптопровайдер","антивирус","сканер уязвимостей","дистрибутив","вебинар","видеоконференция",
             "подписка","семейная подписка","лицензия","офисный пакет","защита рабочих станций")
EDITION_WORDS={"home and business":"для дома и бизнеса"," se":" special edition"," epp":" endpoint protection platform"}
CORPORATE={"inc","ltd","limited","corporation","corp","llc","gmbh","software","ооо","ао","зао"}


def version_forms(text):
    def number(match):
        raw=match["number"]
        if raw[0].isdigit():return raw
        value=ORDINALS.get(lemma(raw),NUMBERS.get(lemma(raw)))
        return str(value) if value is not None else match[0]
    if " " not in text:return text
    text=re.sub(rf"\b{VERSION_WORD}\s+(?P<number>{VERSION_NUMBER})\b",number,text)
    text=re.sub(rf"\b(?P<number>{VERSION_NUMBER})\s+{VERSION_WORD}\b",number,text)
    text=re.sub(r"\bv\.?\s*(?=\d)","",text)
    text=re.sub(r"\b((?:19|20)\d\d)\s+(?:года?\b|г\.)",r"\1",text)
    return text


def edition_form(index,text):
    literal=text
    text=re.sub(r"^ms (?=\w)","microsoft ",text)
    for source,dest in EDITION_WORDS.items():
        text=re.sub(re.escape(source)+r"\b",dest,text)
    if literal!=text and index.products(literal,fuzzy=False):
        return literal
    return text


class FeedLanguage:
    def __init__(self,index,kb):
        self.descriptors={words(x) for x in DESCRIPTORS}
        self.descriptors.update(words(label) for label in index.classes.values())
        # Одно и то же имя может обозначать несколько разделов. Не фиксируем
        # за таким именем случайный раздел из порядка обхода YAML.
        targets=defaultdict(set)
        for ident,row in kb.rows["categories"].items():
            labels=[row.get("title",""),row.get("title_short","")]
            labels.extend(re.split(r"\s+и\s+|\s*\(",row.get("title_short",""))[:1])
            self.descriptors.update(words(str(s)) for s in [*row.get("synonyms",[]),*row.get("slang",[])] if s)
            sections=Counter(index.card_sections[cid] for cid in index.tags["classes"].get(ident,()))
            target=max(sections,key=lambda k:(sections[k],k)) if sections else None
            for label in filter(None,labels):
                self.descriptors.add(words(label))
                if target:
                    signature=class_words(label)
                    if signature:targets[signature].add(target)
        self.category_alias={k:next(iter(v)) for k,v in targets.items() if len(v)==1}
        by_short=defaultdict(set)
        self.vendor_cards=defaultdict(list)
        for cid,vid in index.card_vendors.items():
            if vid:self.vendor_cards[vid].append(cid)
        for name,vid in index.vendor_names.items():
            short=" ".join(w for w in words(name) if w not in CORPORATE)
            if short:by_short[short].add(vid)
        for short,vids in by_short.items():
            if len(vids)==1:index.vendor_names.setdefault(short,next(iter(vids)))

    def class_prefixes(self,index,text):
        parts=text.split()
        for end in range(min(7,len(parts)-1),0,-1):
            label=" ".join(parts[:end])
            if parts[end-1] in STOP:continue
            if words(label) in self.descriptors or index.class_match(label):
                yield " ".join(parts[end:])

    def section(self,index,label):
        return index.class_match(label) or self.category_alias.get(class_words(label))
