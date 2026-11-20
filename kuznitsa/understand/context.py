from .intent import base_plan


def fallback_plan(intent,initial,filters,words,profile,category,entities,kb):
    if intent=="renewal" and not any(filters.get(k) for k in ("family","category","vendor")):
        owned=[p for p in profile.owned if p.get("family_id")]
        if owned:
            filters["family"]=[p["family_id"] for p in sorted(owned,key=lambda p:p.get("expires_in_days") or 9999)]
            return "product"
    mapping={"task":("use_cases","use_case"),"role_kit":("roles","role"),"industry":("industries","industry"),"question":("faq","faq")}
    if intent in mapping and initial=="off_topic":
        group,kind=mapping[intent]
        for e in entities:
            if e["type"]==kind:
                row=kb.rows[group][e["id"]]
                cats=row.get("categories",[])+row.get("related_categories",[])+[s["category"] for s in row.get("slots",[]) if s.get("category")]
                if cats:
                    filters["category"]=cats
                    return "category"
    return initial
