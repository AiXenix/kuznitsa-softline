import re
from kuznitsa.text import sku_key,tokens


def lookup_skus(catalog,raw,quantity=None):
    found={}
    from .repair import LAYOUT
    from kuznitsa.index.source import source_key
    code=re.sub(r"^артикул\s+", "", raw.strip().casefold())
    shared=catalog.shared_sources.get(code)
    if shared:
        matches=[o for o in shared if quantity is None or
                 (o.lic.qty_min or 1)<=quantity<=(o.lic.qty_max or float("inf"))]
        if matches and len({o.family_id or o.offer_id for o in matches})==1:
            matches=matches[:1]
        for offer in matches:
            found.setdefault(offer.card_id,offer)
        return found
    direct=catalog.source_codes.get(code) or catalog.source_variants.get(source_key(code))
    if not direct and any(char.isdigit() for char in code):
        direct=catalog.source_codes.get(code.translate(LAYOUT))
    if direct:return {direct.card_id:direct}
    parts=(raw,*tokens(raw))
    for candidate in (*parts,*(s.translate(LAYOUT) for s in parts if re.search(r"[а-я]",s,re.I) and re.search(r"\d",s))):
        key=sku_key(candidate)
        o=catalog.skus.get(key) or catalog.regional.get(key)
        if o:
            found[o.card_id]=o
    return found


def resembles_sku(word):
    return len(word)>=6 and re.fullmatch(r"(?=[a-z0-9-]*\d)(?=[a-z0-9-]*[a-z])[a-z0-9]+(?:-[a-z0-9]+)*",word) is not None
