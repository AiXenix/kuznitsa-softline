"""Редакция и версия, привязанные к названию продаваемой линейки."""
from dataclasses import dataclass
from functools import lru_cache
import re

from kuznitsa.text import normalize
from .feed_language import sold_as

FORMS = {
    "home": "хоум хом домашняя домашний домашнее дома",
    "pro": "про проф профессионал профешнл профессиональный профессиональная professional",
    "enterprise": "энтерпрайз корпоративная корпоративный",
    "standard": "стандарт стандард стандартный стандартная",
    "business": "бизнес бизнеса",
    "premium": "премиум", "ultimate": "ультимейт", "education": "эдьюкейшн",
    "plus": "плюс", "server": "сервер",
}
LEVEL = {form:level for level,forms in FORMS.items() for form in [level,*forms.split()]}
JOIN = {"энд","и","and","&"}
# Названия продукта в разговорной речи. Совпадение всегда проверяется по карточке.
BRANDS = {"офис":"office","винда":"windows","виндовс":"windows","виндоус":"windows",
          "касперский":"kaspersky","каспер":"kaspersky","автокад":"autocad"}


@dataclass(frozen=True)
class EditionMatch:
    query: str
    cards: tuple
    neighbors: tuple
    audience: str | None
    note: str


def terms(text):
    return re.findall(r"[\w]+(?:\.\d+)*|&",normalize(text))


@lru_cache(8192)
def title_parts(title):
    tokens=terms(title)
    versions=[v for v in tokens if re.fullmatch(r"\d+(?:\.\d+)*",v)]
    return {LEVEL[w] for w in tokens if w in LEVEL}, versions


def resolve(index, text):
    tokens=terms(text)
    if not tokens or not any(w in LEVEL for w in tokens[1:]):
        return None
    end=len(tokens)
    while end and (tokens[end-1] in LEVEL or tokens[end-1] in JOIN or re.fullmatch(r"\d+(?:\.\d+)*",tokens[end-1])):
        end-=1
    suffix=tokens[end:]
    levels=list(dict.fromkeys(LEVEL[w] for w in suffix if w in LEVEL))
    if not end or not levels:
        return None
    versions=[w for w in suffix if w[0].isdigit()]
    if len(versions)>1:
        return None
    if tokens[end-1] in {"для","и","and","&"}:
        return None
    head=" ".join(tokens[:end])
    brand=BRANDS.get(head,index.aliases.get(head,head))
    # Сокращение названия раздела само по себе не удостоверяет продукт.
    candidates=tuple(i for i in index.products(brand,domain="software",fuzzy=False)
                     if sold_as(index.cat.cards[i],brand))
    if not candidates and head in index.slang:
        kind,members=index.slang[head]
        if kind=="families":
            candidates=tuple(i for i in members if index.cat.cards[i].offers[0].domain=="software")
    if not candidates and head in index.vendor_names:
        candidates=tuple(index.language.vendor_cards[index.vendor_names[head]])
        candidates=tuple(i for i in candidates if index.cat.cards[i].offers[0].domain=="software")
    if not candidates:
        return None
    wanted=set(levels)
    version=next(iter(versions),"")
    hits=[i for i in candidates if wanted<=title_parts(index.cat.cards[i].title)[0]]
    if not hits:
        return None
    def release(s):
        return tuple(map(int,s.split(".")))
    def rank(cid):
        card=index.cat.cards[cid]
        found,numbers=title_parts(card.title)
        number=max(map(release,numbers),default=(0,))
        distance=min((abs(release(v)[0]-release(version)[0]) for v in numbers),default=10000) if version else 0
        return (version in numbers,-distance,-len(found-wanted),number,index.quality[cid],cid)
    hits.sort(key=rank,reverse=True)
    note=""
    if version and version not in title_parts(index.cat.cards[hits[0]].title)[1]:
        note=f"Версия {version} этой редакции в каталоге отсутствует. Ближайший вариант — {index.cat.cards[hits[0]].title}."
    if version and not note:
        hits=[i for i in hits if version in title_parts(index.cat.cards[i].title)[1]]
    audience="business" if wanted & {"pro","enterprise","business"} else "home" if "home" in wanted else None
    query=" ".join(filter(None,[brand,version,*levels]))
    anchor=index.cat.cards[hits[0]]
    root=anchor.offers[0].category_path[:1]
    section=index.card_sections[anchor.id]
    others=[i for i in candidates if index.cat.cards[i].vendor==anchor.vendor and
            index.cat.cards[i].offers[0].category_path[:1]==root and title_parts(index.cat.cards[i].title)[0] and
            ("server" in title_parts(index.cat.cards[i].title)[0])==("server" in wanted)]
    others.sort(key=lambda i:(index.card_sections[i]==section,rank(i)),reverse=True)
    return EditionMatch(query,tuple(hits),tuple(others),audience,note)
