"""Последняя проверка товарных блоков после фильтров и правил магазина."""

COLLECTION = {
    "products":"items", "analogs":"items", "promo":"items", "services":"items", "crosssell":"items",
    "compare":"columns", "my_licenses":"items", "spec":"lines", "kit":"slots",
}


def guard(engine, req, result):
    blocks = result["blocks"]
    visible = set()
    had_catalog_block = False
    for block in blocks[:]:
        kind = block["type"]
        field = COLLECTION.get(kind)
        if field is None:
            continue
        rows = block.get(field)
        if not rows:
            blocks.remove(block)
        if kind in ("products","analogs","promo","services"):
            had_catalog_block = True
            for row in rows or ():
                card = row.get("card",row)
                if card.get("kind")!="upsell":
                    visible.add(card.get("card_ref") or card.get("card_id"))
    visible.discard(None)
    feed = getattr(engine.catalog,"feed",None)
    if req.page!=1:
        if not blocks:
            blocks.append(dict(type="answer",title="Конец выдачи",text="На этой странице больше нет предложений.",
                               source="catalog",links=[]))
        return
    if not feed:
        if not blocks:
            options=[dict(label=row["title"],apply=dict(q=row["title"],category=k))
                     for k,row in engine.kb.rows["categories"].items() if k in engine.catalog.by["category"]][:3]
            blocks.append(dict(type="clarify",title="Уточните запрос",
                question="Подходящих предложений нет. Какой раздел вас интересует?",options=options))
        return
    if len(visible)>=min(req.page_size,4):
        return
    if not had_catalog_block and blocks and result["understood"]["intent"] not in ("analog","out_of_catalog"):
        return
    if any(b["type"]=="clarify" and b.get("options") for b in blocks):
        return
    understood = result["understood"]
    sections = list(understood.get("filters",{}).get("category") or ())
    sections.extend(feed.card_sections[c] for c in visible if c in feed.card_sections)
    hint = next((feed.classes[k] for k in sections if k in feed.classes),"")
    sections.extend(feed.sections(hint or req.q))
    options = [dict(label=feed.classes[k],apply=dict(q=feed.classes[k],category=k))
               for k in dict.fromkeys(sections) if k in feed.groups][:3]
    message = ("Подходящих карточек меньше четырёх. В каком разделе продолжить поиск?" if visible
               else "С заданными условиями подходящих товаров нет. Какой раздел открыть?")
    existing = next((b for b in blocks if b["type"]=="clarify"),None)
    if existing is None:
        blocks.append(dict(type="clarify",title="Уточните раздел",question=message,options=options))
    else:
        existing.update(question=message,options=options)
