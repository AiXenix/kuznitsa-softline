"""Public manufacturer identifiers used by exact SKU search in the demo."""
import csv
from pathlib import Path


def apply_sample_codes(offers):
    with Path(__file__).with_name("sample_codes.tsv").open() as stream:
        records=list(csv.DictReader(stream,delimiter="\t"))
    remaining={(r["family_id"],r["edition"],r["action"],r["audience"],r["delivery"],
                r["metric"],r["model"],r["term_months"],r["qty_min"],r["qty_max"],r["pack"]):r["sku"] for r in records}
    for offer in offers:
        lic=offer.lic
        key=(offer.family_id,offer.edition,lic.action,lic.audience,offer.delivery,lic.metric,lic.model,
             *(str(v) if v is not None else "" for v in (lic.term_months,lic.qty_min,lic.qty_max,lic.pack)))
        if key in remaining:
            offer.sku=remaining.pop(key)
