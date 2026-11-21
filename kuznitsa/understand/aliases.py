from rapidfuzz.distance import DamerauLevenshtein
from kuznitsa.text import normalize,tokens


def typo_aliases(kb):
    corrections={}
    for term,r in kb.rows["slang"].items():
        if r.get("type")!="typo":
            continue
        for field,group in [("vendor","vendors"),("family","families"),("category","categories")]:
            row=kb.rows[group].get(r["maps_to"].get(field))
            if not row:
                continue
            candidates=[normalize(v) for v in [row.get("name"),row.get("title"),*row.get("aliases",[])] if v and normalize(v)!=normalize(term)]
            if candidates:
                best=min(candidates,key=lambda v:(DamerauLevenshtein.distance(term.replace(" ",""),v.replace(" ","")),len(v)))
                if DamerauLevenshtein.distance(term.replace(" ",""),best.replace(" ",""))<=2:
                    corrections[normalize(term)]=best
    return corrections
