"""Привязка демонстрационных артикулов к соответствующим условиям mock-SKU."""
import json
from collections import defaultdict


def apply_sample_codes(directory, offers, families):
    by_card = defaultdict(list)
    for offer in offers:
        by_card[offer.card_id].append(offer)
    for path in directory.glob("fam_*.json"):
        card = path.stem.removeprefix("fam_").replace("-", ":")
        for sample in json.loads(path.read_text()).get("state", {}).get("familyFilteredProducts", []):
            code = sample.get("sku")
            description = sample.get("shortConfiguration", "").lower()
            if not code or "12 мес" not in description:
                continue
            action = "renewal" if "продлен" in description else "new"
            match = next((o for o in by_card[card] if o.lic.action == action and o.lic.term_months == 12
                          and o.lic.audience == "business" and o.lic.qty_min == sample.get("minQuantity")
                          and o.lic.qty_max == sample.get("maxQuantity")), None)
            if match:
                match.sku = code
    for path in directory.glob("sku_*.json"):
        product = json.loads(path.read_text()).get("product", {})
        code = product.get("sku_shown")
        if not code:
            continue
        family = next((f for f in families.values() if code.lower() in
                       {str(a).lower() for a in f.get("aliases", [])}), None)
        if family:
            title = product.get("h1", "").lower().split()
            for ed in family.get("editions", []):
                if ed["id"].lower() in title:
                    pool = by_card[family["id"] + ":" + ed["id"]]
                    match = next((o for o in pool if o.lic.action == "new" and o.delivery == "esd"
                                  and o.lic.audience == "business" and (o.lic.qty_min or 1) == 1), None)
                    if match:
                        match.sku = code
                        break
