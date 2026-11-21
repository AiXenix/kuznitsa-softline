"""Причины одинаковы для событий витрины и исторической выборки."""
import re
REASONS = set("""not_in_catalog_known not_in_catalog_unknown vendor_left vocabulary_gap typo_unfixed
filters_too_strict price_on_request_only content_gap ranking_issue ambiguous sku_not_found hardware piracy off_topic gibberish""".split())
NOISE = {"hardware","piracy","off_topic","gibberish"}


def classify(response, count, reason):
    understood = response["understood"]
    if "zero_reason" in understood:
        return understood["zero_reason"]
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
    if response.get("relax_hints"):
        return "filters_too_strict"
    if understood.get("intent")=="off_topic":
        # До M2b движок относил любое нераспознанное слово к подтипу other.
        query=response["query"].get("corrected") or response["query"].get("raw","")
        return "off_topic" if re.search(r"\b(погод|рецепт|пицц|борщ)",query.lower()) else "unknown_term"
    if understood.get("qty") and reason=="qty_out_of_range":
        return reason
    if reason in ("not_in_catalog","vendor_left","no_available_offer","unknown_term"):
        return reason
    if understood.get("filters") and any(understood["filters"].get(k) for k in ("delivery","term_months","price_max","registry","platforms")):
        return "filters_too_strict"
    if response["query"].get("corrections"):
        return "typo_unfixed"
    if understood.get("intent") == "out_of_catalog":
        return "not_in_catalog_unknown"
    return "unknown_term"

LABELS = dict(not_in_catalog_known="Известный продукт отсутствует",not_in_catalog_unknown="Неизвестный продукт",
              vendor_left="Вендор прекратил поставки",vocabulary_gap="Не хватает синонима",typo_unfixed="Ошибка ввода",
              filters_too_strict="Слишком строгие условия",price_on_request_only="Только цена по запросу",
              content_gap="Не хватает характеристик",ranking_issue="Подходящая позиция слишком низко",
              ambiguous="Нужно уточнение",sku_not_found="Артикул отсутствует",hardware="Ищут оборудование",
              piracy="Нелицензионное ПО",off_topic="Другая тематика",gibberish="Неразборчивый запрос")

CANONICAL = {"not_in_catalog_known":"not_in_catalog","not_in_catalog_unknown":"unknown_term","vocabulary_gap":"unknown_term",
             "typo_unfixed":"unknown_term","sku_not_found":"unknown_term","price_on_request_only":"no_available_offer",
             "hardware":"off_topic","piracy":"off_topic","gibberish":"off_topic","ambiguous":"unknown_term"}
LABELS.update(ambiguous="Уход или уточнение без установленной причины",unknown_term="Термин не распознан",not_in_catalog="Нет в ассортименте",qty_out_of_range="Количество вне диапазона",
              no_available_offer="Нет доступной лицензии")
