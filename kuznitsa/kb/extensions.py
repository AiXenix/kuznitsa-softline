"""Схема строк источников и удаление недействительных ссылок после объединения KB."""

FIELDS={
    "families":"id for_whom name title vendor aliases category extra_categories summary editions versions platforms compat_ru_os deployment license delivery registry certs use_cases roles industries formats analogs replaces price_rub popularity catalog sku_name_examples confidence max_seats upgrade_to",
    "vendors":"id name name_ru country origin market_status aliases categories notes",
    "categories":"id parent title title_short softline_path synonyms slang description typical_queries",
    "okved":"code title industry",
    "feed_analogs":"id names kind in_catalog sections analogs note",
    "feed_tasks":"id sections phrases aliases",
    "hardware_hints":"id hardware_class hardware_feed_classes trigger_words prompt software_classes software_query_hint sw_examples",
    "roles":"id parent title aliases slots",
    "industries":"id parent title aliases slots compliance",
    "use_cases":"id title phrases categories families features products",
    "faq":"id questions answer related_categories related_families related_products tags",
    "analogs":"family product aliases russian_analogs",
    "compliance":"id title aliases effect explain",
    "slang":"term type maps_to note",
    "crosssell":"id when suggest note",
}
FIELDS={g:set(fields.split()) for g,fields in FIELDS.items()}


NESTED={k:set(fields.split()) for k,fields in {
    "editions":"id name title aliases", "license":"models audiences terms_months metrics packs actions bands",
    "price_rub":"unit low typical high", "slots":"category families products must note",
    "maps_to":"attr value platform category vendor family text class_id line_id", "effect":"filter boost",
    "russian_analogs":"family note", "when":"categories families", "suggest":"category families reason",
}.items()}


def unknown_fields(group,row):
    unknown=[str(k) for k in row.keys()-FIELDS[group]]
    for key in row.keys() & NESTED.keys():
        parts=row[key] if isinstance(row[key],list) else [row[key]]
        for part in parts:
            if isinstance(part,dict):
                unknown.extend(f"{key}.{k}" for k in part.keys()-NESTED[key])
    return sorted(unknown)


def prune_families(kb,origins):
    families=kb.rows["families"]
    def exists(fid,where):
        if isinstance(fid,str) and fid in families:
            return True
        notice=f"{where} → {fid}"
        if notice not in kb.dangling:
            kb.dangling.append(notice)
        return False

    def clean_list(row,key,where):
        if key in row:
            values=row[key] if isinstance(row[key],list) else [row[key]] if row[key] is not None else []
            row[key]=[v for v in values if exists(v,where+"."+key)]

    for group,rows in kb.rows.items():
        for ident,row in list(rows.items()):
            remove=False
            if group=="feed_analogs":
                continue  # Здесь analogs ссылается на названия карточек фида.
            for key in ("families","related_families","replaces","analogs"):
                clean_list(row,key,ident)
            if row.get("upgrade_to") and not exists(row["upgrade_to"],ident+".upgrade_to"):
                row.pop("upgrade_to")
            if group=="analogs":
                remove=not exists(ident,ident+".family")
                row["russian_analogs"]=[r for r in row.get("russian_analogs",[]) if exists(r.get("family"),ident+".russian_analogs")]
            if group=="slang" and "family" in row["maps_to"] and not exists(row["maps_to"]["family"],ident+".family"):
                row["maps_to"].pop("family")
                remove=not row["maps_to"]
            for slot in [*row.get("slots",[]),*row.get("suggest",[]),row.get("when",{})]:
                clean_list(slot,"families",ident)
            if remove:
                del rows[ident]
                source=origins[group].pop(ident)
                kb.sources[group][source]-=1
