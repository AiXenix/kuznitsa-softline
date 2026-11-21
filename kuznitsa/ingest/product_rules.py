"""Literal supplier signals, restricted to non-regulatory fields."""
import re
from functools import lru_cache

PATTERNS={
    "platforms":{"linux":"linux|линукс","windows":"windows|виндовс","macos":r"mac\s?os","android":"android","ios":"ios","web":"веб-приложение"},
    "deployment":{"onprem":r"on.?prem(?:ise)?|локально\w* разв[её]ртывани\w*","cloud":r"cloud|saas|облачн\w*","hybrid":r"hybrid|гибридн\w* разв[её]ртывани\w*"},
    "delivery":{"esd":r"esd|электронн\w* поставк\w*","box":r"box|коробочн\w*","paper":r"paper|бумажн\w* поставк\w*",
                "media":r"media|dvd|физическ\w* носител\w*","service":r"service|оказание услуг"}
}
COMPILED={field:[(value,re.compile(r"(?<!\w)(?:"+expr+r")(?!\w)",re.I)) for value,expr in rules.items()]
          for field,rules in PATTERNS.items()}


@lru_cache(4096)
def literal(text):
    return {field:tuple(val for val,regex in rules if regex.search(text)) for field,rules in COMPILED.items()}


def apply(offer):
    text=" ".join([offer.name,offer.description,*offer.attrs.values()])
    hits=literal(text)
    if not offer.platforms:
        offer.platforms=list(hits["platforms"])
    if not offer.delivery and len(hits["delivery"])==1:
        offer.delivery=hits["delivery"][0]
    return [*(("platforms",p) for p in offer.platforms),*(("deployment",d) for d in hits["deployment"]),
            *([("delivery",offer.delivery)] if offer.delivery else [])]
