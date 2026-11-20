import re
from kuznitsa.text import sku_key,tokens


def lookup_skus(catalog,raw):
    found={}
    for candidate in (raw,*tokens(raw)):
        key=sku_key(candidate)
        o=catalog.skus.get(key) or catalog.regional.get(key)
        if o:
            found[o.card_id]=o
    return found


def resembles_sku(word):
    return len(word)>=6 and re.fullmatch(r"(?=[a-z0-9-]*\d)(?=[a-z0-9-]*[a-z])[a-z0-9]+(?:-[a-z0-9]+)*",word) is not None
