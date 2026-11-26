"""Идентичность модели и подтверждённые характеристики оборудования."""
import re

VARIANT = re.compile(
    r"\s*(?:[,;]\s*|\s+[—–-]\s+|\s*\()(?:арт(?:икул)?\.?\s*[:№]?|sku\b|цвет\b|"
    r"комплектация\b|конфигурация\b|вариант\b|исполнение\b|модификация\b|"
    r"(?:ram|озу|ssd|hdd)\s*[:=]?\s*\d|\d+\s*(?:гб|тб|gb|tb)\b|"
    r"черн(?:ый|ая)|бел(?:ый|ая)|сер(?:ый|ая)).*$", re.I)


def model_title(offer):
    title=offer.family_name or offer.name
    title=VARIANT.sub("",title).strip() or title
    title=re.sub(r",\s*\d{5,}\s*$","",title).strip() or title
    if offer.sku:
        title=re.sub(r"[,;]\s*"+re.escape(offer.sku)+r"$","",title,flags=re.I).strip() or title
    return title


def suitability(offer, categories, multifunction):
    attrs=offer.attrs
    reasons=[]
    if multifunction:
        if "мфу" in str(attrs.get("Тип устройства","")).lower() or "скан" in str(attrs.get("Состав МФУ","")).lower():
            reasons.append("Печать и работа со сканами")
    if categories & {"vector_illustration","raster_photo","cad_2d","mcad_plm"}:
        gpu=str(attrs.get("Видеопроцессор",""))
        if re.search("geforce|quadro|radeon rx|rtx",gpu,re.I):
            reasons.append("Дискретная графика "+gpu)
    if "accounting" in categories:
        if "офис" in str(attrs.get("Быстрый выбор","")).lower() or "офис" in str(attrs.get("Назначение ПК","")).lower():
            reasons.append("Офисная конфигурация по данным каталога")
        if "ssd" in str(attrs.get("Тип носителя","")).lower() or re.match(r"[1-9]",str(attrs.get("Объем установленного SSD",""))):
            reasons.append("Накопитель SSD")
    return reasons


def hardware_kind(value):
    """Класс в словаре поставщика и слова названий разделов для этого класса."""
    groups={
        "desktop":("пк","комп","компьютер","десктоп"), "laptop":("ноутбук","ноут"),
        "switch":("коммутатор","свитч"), "router":("роутер","маршрутизатор"),
        "printer_mfp":("mfp","мфу","принтер"), "monitor":("монитор",),
        "ups":("ибп","бесперебойник","бесперебойный"), "ssd":("ssd","твердотельный"),
        "ram":("memory","память","озу"), "gpu":("graphics_card","video_card","видеокарта"),
    }
    key=str(value).casefold().strip()
    for kind,labels in groups.items():
        if key in (kind,*labels):
            return kind,labels
    return key,(key,)
