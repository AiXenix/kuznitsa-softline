"""Причины одинаковы для событий витрины и исторической выборки."""
REASONS = set("""not_in_catalog_known not_in_catalog_unknown vendor_left vocabulary_gap typo_unfixed
filters_too_strict price_on_request_only content_gap ranking_issue ambiguous sku_not_found hardware piracy off_topic gibberish""".split())
NOISE = {"hardware","piracy","off_topic","gibberish"}


def classify(response, count, reason):
    understood = response["understood"]
    for block in response["blocks"]:
        if block["type"] == "not_in_catalog":
            return "vendor_left" if block.get("reason") == "vendor_left" else "not_in_catalog_known"
    for value in (understood.get("subtype"), reason):
        if value in REASONS and value != "filters_too_strict":
            return value
    cards = [c for b in response["blocks"] if b["type"]=="products" for c in b["items"]]
    if cards and all(c.get("offer",{}).get("price_on_request") for c in cards):
        return "price_on_request_only"
    relaxed=any("снято условие" in note for note in response.get("notes",[]))
    if relaxed and cards:
        filters=understood.get("filters",{})
        if any(key in filters and all(c.get("offer",{}).get(key) is None for c in cards)
               for key in ("term_months","vat","delivery")):
            return "content_gap"
        return "filters_too_strict"
    if count:
        return None
    if understood.get("filters"):
        return "filters_too_strict"
    if response["query"].get("corrections"):
        return "typo_unfixed"
    if understood.get("intent") == "out_of_catalog":
        return "not_in_catalog_unknown"
    return "vocabulary_gap"

LABELS = dict(not_in_catalog_known="Известный продукт отсутствует",not_in_catalog_unknown="Неизвестный продукт",
              vendor_left="Вендор прекратил поставки",vocabulary_gap="Не хватает синонима",typo_unfixed="Ошибка ввода",
              filters_too_strict="Слишком строгие условия",price_on_request_only="Только цена по запросу",
              content_gap="Не хватает характеристик",ranking_issue="Подходящая позиция слишком низко",
              ambiguous="Нужно уточнение",sku_not_found="Артикул отсутствует",hardware="Ищут оборудование",
              piracy="Нелицензионное ПО",off_topic="Другая тематика",gibberish="Неразборчивый запрос")
