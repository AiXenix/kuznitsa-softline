"""Проверка полноты на mock: эталоны читает только проверяющая сторона."""
import json

from kuznitsa.analytics.insights import listing
from kuznitsa.analytics.store import Journal
from kuznitsa.config import ROOT,Config
import yaml


def audit(j):
    stories=yaml.safe_load((ROOT/"mock/spec/querylog.yaml").read_text())["seeded_anomalies"]
    proposals=listing(j)
    result={}
    for story in stories:
        found=[]
        for it in proposals:
            if it["type"]!=story["type"]:
                continue
            evidence=it["evidence"]
            payload=it["action"]["payload_json"]
            samples=set(evidence["sample_queries"])
            overlap=samples.intersection(story.get("queries",[]))
            kind=it["type"]
            if kind=="hot_lead":
                ok=payload.get("client_id")==story["client_id"] and bool(overlap)
            elif kind=="renewal_campaign":
                ok=any(c["licenses"] for c in payload["clients"])
            elif kind=="weights_advice":
                ok=evidence["band_inversions"]==0 and evidence["moved"]>0
            elif kind=="add_synonym":
                ok=payload["phrase"] in story["queries"] and payload["to"] in story["reformulate_to"]
            elif kind=="fix_card":
                ok=bool(overlap and payload["card_ids"]) and payload["field"] in story["missing_attribute"].replace("qty_brackets","qty_range")
            elif kind=="merch_rule":
                ok=bool(overlap) and it["action"]["kind"] in ("boost","pin")
            elif kind=="rising_demand":
                ok=bool(overlap) and evidence["previous_searches"]>0 and evidence["growth_pct"]>0
            else:
                ok=bool(overlap)
            if ok:
                found.append(it["id"])
        result[story["id"]]=found
    return result


if __name__=="__main__":
    print(json.dumps(audit(Journal(Config().data/"kuznitsa.sqlite")),indent=2))
