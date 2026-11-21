import json
import yaml
from collections import Counter,defaultdict
from itertools import pairwise

from kuznitsa.config import Config
from kuznitsa.kb.loader import load
from kuznitsa.mock.catalog_gen import build
from kuznitsa.mock.naming import quantity_word
from kuznitsa.mock.pricing import edition_ranks
from kuznitsa.schema import Offer


def test_quantity_words_and_tiers():
    assert [quantity_word("user",n) for n in (1,2,5,11,21,24)]==[
        "пользователь","пользователя","пользователей","пользователей","пользователь","пользователя"]
    assert quantity_word("server",1)=="сервер"
    assert edition_ranks([{"name":"Pro"},{"name":"Кластер"},{"aliases":["Home"]}])==[2,1,0]


def test_full_catalog_invariants(tmp_path):
    cfg=Config(data=tmp_path)
    kb=load(cfg.kb)
    build(cfg,kb)
    families=kb.rows["families"]
    cards=defaultdict(list)
    compared=defaultdict(dict)
    tiers=defaultdict(list)
    ranks=defaultdict(list)
    with (cfg.data/"catalog.jsonl").open() as f:
        for line in f:
            o=Offer.model_validate_json(line)
            cards[o.card_id].append(o)
            lic=o.lic
            if o.family_id=="drweb_enterprise_security_suite" and o.edition=="desktop":
                assert lic.metric=="device"
            if not o.price:
                continue
            base=(o.family_id,o.version,lic.model,lic.term_months,lic.metric,o.delivery)
            size=(lic.qty_min,lic.qty_max,lic.pack)
            compared[base+(o.edition,size)][lic.action,lic.audience]=o.price
            if lic.qty_min or lic.pack:
                tiers[base+(o.edition,lic.action,lic.audience,bool(lic.pack))].append(
                    (lic.qty_min or lic.pack,o.price/(lic.pack or 1)))
            ranks[base+(size,lic.action,lic.audience)].append((o.edition,o.price))
    sold_families={rows[0].family_id for rows in cards.values()}
    retired_home={"kaspersky_standard_home","drweb_security_space","pro32_total_security"}
    assert not sold_families.intersection(retired_home)
    assert all(families[fid].get("catalog") is False for fid in retired_home)
    # В исходном снимке было 660 карточек и 352 линейки. Снято шесть редакций.
    assert len(cards)>=654 and len(sold_families)>=349
    assert 0<sum(not o.available for rows in cards.values() for o in rows)/sum(map(len,cards.values()))<.02
    labels=Counter(r["insight"] for r in map(json.loads,(cfg.data/"mock_defects.jsonl").read_text().splitlines()))
    assert labels=={"INS-07":14,"INS-08":9,"INS-09":11}
    for values in compared.values():
        for (action,aud),amount in values.items():
            if action=="renewal" and ("new",aud) in values:
                assert amount<values["new",aud]
            if aud in ("gov","edu") and (action,"business") in values:
                assert amount<values[action,"business"]
    for values in tiers.values():
        assert all(a>=b for (_,a),(_,b) in pairwise(sorted(values)))
    for key,values in ranks.items():
        editions=families[key[0]].get("editions",[])
        rank={e["id"]:n for e,n in zip(editions,edition_ranks(editions))}
        ordered=sorted(values,key=lambda v:rank.get(v[0],0))
        assert all(a<=b for (_,a),(_,b) in pairwise(ordered)),key
    for rows in cards.values():
        f=families[rows[0].family_id]
        lic=f.get("license",{})
        required={int(b.split("-")[0].rstrip("+")) for b in lic.get("bands",[])}
        audience=(lic.get("audiences") or ["business"])[0]
        if not any(o.lic.audience==audience for o in rows):
            audience=rows[0].lic.audience
        term=12 if 12 in lic.get("terms_months",[]) else (lic.get("terms_months") or [None])[0]
        for action in set(lic.get("actions",[])) & {"new","renewal"}:
            primary=[o for o in rows if (o.lic.term_months,o.lic.action,o.lic.audience)==(term,action,audience)
                     and o.delivery==(f.get("delivery") or ["esd"])[0]]
            assert required<={o.lic.qty_min for o in primary}
            if f.get("popularity",0)>=4:
                assert all(o.price and o.available for o in primary)
    clients=list(map(json.loads,(cfg.data/"clients.jsonl").read_text().splitlines()))
    by_client={c["client_id"]:c for c in clients}
    by_offer={o.offer_id:o for rows in cards.values() for o in rows}
    profiles=yaml.safe_load((cfg.kb.parent/"mock/spec/profiles.yaml").read_text())["profiles"]
    for profile in profiles:
        client=by_client[profile["id"]]
        for spec,owned in zip(profile.get("owned",[]),client["owned"],strict=True):
            if spec["family"] in retired_home:
                assert owned["offer_id"] is None and owned["card_id"] is None
                assert owned["family_id"]==spec["family"]
                for key in ("product","edition","qty","metric","expires_in_days"):
                    assert owned.get(key)==spec.get(key)
                continue
            assert by_offer[owned["offer_id"]].family_id==spec["family"]
            lic=by_offer[owned["offer_id"]].lic
            assert owned["metric"]==lic.metric and owned["qty"]%(lic.pack or 1)==0
            assert (owned.get("requested_qty",owned["qty"]),owned.get("expires_in_days"))==(spec["qty"],spec.get("expires_in_days"))
        historical={spec["product"] for spec in profile.get("owned",[]) if spec["family"] in retired_home}
        for order in client["orders"]:
            for item in order["items"]:
                if item["product"] in historical:
                    assert item["offer_id"] is None and item["card_id"] is None
                    assert any(source=={k:item[k] for k in source}
                               for old_order in profile["orders"] for source in old_order["items"])
                else:
                    assert item["offer_id"] in by_offer
    own=by_client["smb_trade"]["owned"][0]
    assert by_offer[own["offer_id"]].lic.pack==15
    assert (own["family_id"],own["qty"],own["expires_in_days"])==("kaspersky_ksos",15,21)

    for sku,family in [("KL4867RAQFR","kaspersky_kesb"),("FQC-10572","windows_11"),("4601546092816","onec_accounting")]:
        matches=[o for o in by_offer.values() if o.sku==sku]
        assert len(matches)==1 and matches[0].family_id==family
        if sku.isdigit():
            assert matches[0].delivery=="box"
