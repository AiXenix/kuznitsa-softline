"""Идентичность модели и подтверждённые характеристики оборудования."""
import re

VARIANT = re.compile(
    r"\s*(?:[,;]\s*|\s+[—–-]\s+|\s*\()(?:арт(?:икул)?\.?\s*[:№]?|sku\b|цвет\b|"
    r"комплектация\b|конфигурация\b|вариант\b|исполнение\b|модификация\b|"
    r"(?:ram|озу|ssd|hdd)\s*[:=]?\s*\d|\d+\s*(?:гб|тб|gb|tb)\b|"
    r"черн(?:ый|ая)|бел(?:ый|ая)|сер(?:ый|ая)).*$", re.I)

_COMBO_RE = re.compile(r"\b(?:комплект\w*|набор\w*|combo)\b", re.I)
_ACCESSORY_RE = re.compile(
    r"\b(?:кронштейн\w*|подставк\w*|креплен\w*|кабел\w*|сумк\w*|рюкзак\w*|чех[ое]л\w*|зарядн\w*|блок\w*\s+питан\w*|аккумулятор\w*|пленк\w*|плёнк\w*|обложк\w*)\b",
    re.I,
)

# Правила разделения составных разделов оборудования и периферии:
# (паттерн в запросе, паттерн точного типа в названии, паттерн близкого типа, паттерн комбо/чужого типа)
_SUBTYPE_RULES = (
    (
        re.compile(r"\bклавиатур\w*\b"),
        re.compile(r"\bклавиатур\w*\b|\bkeyboard\b", re.I),
        None,
        re.compile(r"\bмыш\w*\b|\bmouse\b|\bкомплект\w*\b|\bнабор\w*\b|\bcombo\b", re.I),
    ),
    (
        re.compile(r"\bмыш\w*\b"),
        re.compile(r"\bмыш\w*\b|\bmouse\b", re.I),
        None,
        re.compile(r"\bклавиатур\w*\b|\bkeyboard\b|\bкомплект\w*\b|\bнабор\w*\b|\bcombo\b", re.I),
    ),
    (
        re.compile(r"\bнаушник\w*\s+с\s+микрофон\w*\b"),
        re.compile(r"\bгарнитур\w*\b|\bheadset\b", re.I),
        re.compile(r"\bнаушник\w*\b|\bheadphone\w*\b", re.I),
        re.compile(r"^\s*микрофон\w*\b", re.I),
    ),
    (
        re.compile(r"\bнаушник\w*\b"),
        re.compile(r"\bнаушник\w*\b|\bheadphone\w*\b", re.I),
        re.compile(r"\bгарнитур\w*\b|\bheadset\b", re.I),
        re.compile(r"^\s*микрофон\w*\b", re.I),
    ),
    (
        re.compile(r"\bгарнитур\w*\b"),
        re.compile(r"\bгарнитур\w*\b|\bheadset\b", re.I),
        re.compile(r"\bнаушник\w*\b|\bheadphone\w*\b", re.I),
        re.compile(r"^\s*микрофон\w*\b", re.I),
    ),
    (
        re.compile(r"\bмикрофон\w*\b"),
        re.compile(r"\bмикрофон\w*\b|\bmicrophone\b", re.I),
        None,
        re.compile(r"\bгарнитур\w*\b|\bнаушник\w*\b|\bheadset\b|\bheadphone\w*\b", re.I),
    ),
    (
        re.compile(r"\bтонер\w*\b"),
        re.compile(r"\bтонер\w*\b|\btoner\b", re.I),
        re.compile(r"\bкартридж\w*\b|\bcartridge\b", re.I),
        re.compile(r"\bфотобарабан\w*\b|\bдрам\b|\bпл[её]нк\w*\b|\bобложк\w*\b|\bбумаг\w*\b|\bпружин\w*\b", re.I),
    ),
    (
        re.compile(r"\bкартридж\w*\b"),
        re.compile(r"\b(?:тонер-?)?картридж\w*\b|\bcartridge\b", re.I),
        re.compile(r"\bтонер\w*\b|\bчернил\w*\b", re.I),
        re.compile(r"\bфотобарабан\w*\b|\bдрам\b|\bпл[её]нк\w*\b|\bобложк\w*\b|\bбумаг\w*\b|\bпружин\w*\b", re.I),
    ),
    (
        re.compile(r"\b(?:ж[её]стк\w*\s+диск\w*|hdd)\b"),
        re.compile(r"\bж[её]стк\w*\s+диск\w*\b|\bhdd\b", re.I),
        re.compile(r"\bнакопител\w*\b|\bдиск\w*\b", re.I),
        re.compile(r"\bкабел\w*\b|\bадаптер\w*\b|\bкорпус\w*\b|\bбокс\w*\b|\bтвердотельн\w*\b|\bssd\b", re.I),
    ),
    (
        re.compile(r"\bграфическ\w*\s+планшет\w*\b|\bдигитайзер\w*\b"),
        re.compile(r"\bграфическ\w*\s+планшет\w*\b|\bдигитайзер\w*\b|\bhuion\b|\bwacom\b", re.I),
        None,
        re.compile(r"\bакустич\w*\b|\bколонк\w*\b|\bмыш\w*\b|\bклавиатур\w*\b", re.I),
    ),
    (
        re.compile(r"\bпроектор\w*\b"),
        re.compile(r"\bпроектор\w*\b|\bprojector\b", re.I),
        None,
        re.compile(r"\bакустич\w*\b|\bколонк\w*\b|\bкронштейн\w*\b", re.I),
    ),
    (
        re.compile(r"\bвеб-?камер\w*\b|\bвебкамер\w*\b"),
        re.compile(r"\bвеб-?камер\w*\b|\bwebcam\b|\bweb-?cam\b", re.I),
        re.compile(r"\bкамер\w*\b", re.I),
        None,
    ),
    (
        re.compile(r"\bколонк\w*\b|\bакустик\w*\b"),
        re.compile(r"\bколонк\w*\b|\bакусти\w*\b|\bspeaker\w*\b", re.I),
        None,
        None,
    ),
    (
        re.compile(r"\bфлеш\w*\b|\bфлэш\w*\b"),
        re.compile(r"\bфлеш\w*\b|\bфлэш\w*\b|\bflash\b|\busb-?накопител\w*\b", re.I),
        re.compile(r"\bнакопител\w*\b", re.I),
        None,
    ),
    (
        re.compile(r"\bпринтер\w*\b"),
        re.compile(r"\bпринтер\w*\b|\bprinter\b", re.I),
        re.compile(r"\bмфу\b|\bmfp\b", re.I),
        re.compile(r"\bкартридж\w*\b|\bтонер\w*\b|\bбумаг\w*\b|\bкабел\w*\b", re.I),
    ),
    (
        re.compile(r"\bмфу\b"),
        re.compile(r"\bмфу\b|\bmfp\b", re.I),
        re.compile(r"\bпринтер\w*\b", re.I),
        re.compile(r"\bкартридж\w*\b|\bтонер\w*\b|\bdesignjet\b|\bплоттер\w*\b", re.I),
    ),
    (
        re.compile(r"\bсканер\w*\b"),
        re.compile(r"\bсканер\w*\b|\bscanner\b", re.I),
        re.compile(r"\bмфу\b", re.I),
        None,
    ),
    (
        re.compile(r"\bмонитор\w*\b"),
        re.compile(r"\bмонитор\w*\b|\bmonitor\b", re.I),
        None,
        _ACCESSORY_RE,
    ),
    (
        re.compile(r"\bноутбук\w*\b|\bноут\b"),
        re.compile(r"\bноутбук\w*\b|\blaptop\b|\bnotebook\b", re.I),
        None,
        _ACCESSORY_RE,
    ),
    (
        re.compile(r"\b(?:роутер\w*|маршрутизатор\w*)\b"),
        re.compile(r"\b(?:роутер\w*|маршрутизатор\w*|router)\b", re.I),
        None,
        None,
    ),
    (
        re.compile(r"\b(?:коммутатор\w*|свитч\w*)\b"),
        re.compile(r"\b(?:коммутатор\w*|switch)\b", re.I),
        None,
        None,
    ),
)

# Ошибочно классифицированные товары в маленьких разделах («акустическая система» в «Графические планшеты»).
_HARD_DROP_MISCLASSIFIED = re.compile(r"\b(?:акустич\w*|колонк\w*)\b", re.I)

_TRADE_QUALIFIER_RE = re.compile(r"\b(?:этикет\w*|чек\w*|штрих-?код\w*|касс\w*|торгов\w*|термо\w*)\b", re.I)


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


def hardware_head(index, text):
    """Отделить определение устройства от назначения и от запроса о программе."""
    from kuznitsa.text import morphology
    if text in index.hardware:return text
    head=re.split(r"\s+(?:для|в|под)\s+",text,maxsplit=1)[0]
    if head in index.hardware:
        return head
    terms=head.split()
    if len(terms)>8:return None
    for start in range(len(terms)):
        for end in range(len(terms),start,-1):
            name=" ".join(terms[start:end])
            if name not in index.hardware:continue
            modifiers=terms[:start]+terms[end:]
            if all(any(p.tag.POS in ("ADJF","PRTF") for p in morphology().parse(t)) for t in modifiers):
                return name
    return None


def resolve_hardware_section(index, q, section, vendor):
    """Подобрать точный раздел оборудования, когда vendor_class попал в смежный раздел без этого вендора
    (например, «принтер hp»: 91774 «Торговое оборудование / Принтеры» → 93995 «Офисная техника / Принтеры и МФУ»)."""
    if not section or not vendor or section not in index.groups:
        return section
    members = index.groups[section]
    if not members or index.cat.cards[members[0]].offers[0].domain != "hardware":
        return section
    if any(index.card_vendors[cid] == vendor for cid in members):
        return section
    if _TRADE_QUALIFIER_RE.search(q):
        return section

    from kuznitsa.index.feed import words
    q_words = words(q)
    q_set = set(q_words)
    sec_terms = set(index.class_terms.get(section, ()))

    # 1. Подсказки hardware_hints (например, «принтер» → 93995 «Принтеры и МФУ»)
    hint_candidates = []
    for i in range(len(q_words)):
        for j in range(len(q_words), i, -1):
            phrase = " ".join(q_words[i:j])
            dev = index.hardware.get(phrase)
            if dev:
                for k in dev.get("hardware_feed_classes", ()):
                    ks = str(k)
                    if ks in index.groups and ks != section:
                        hint_candidates.append(ks)
    for cand in dict.fromkeys(hint_candidates):
        if any(index.card_vendors[cid] == vendor for cid in index.groups[cand]):
            return cand

    # 2. Другие разделы оборудования, где есть этот вендор и совпадает слово типа устройства
    vendor_cards = index.language.vendor_cards.get(vendor, ())
    if not vendor_cards:
        return section
    by_sec = {}
    for cid in vendor_cards:
        c = index.cat.cards[cid]
        if c.offers[0].domain != "hardware":
            continue
        sec_id = index.card_sections.get(cid)
        if not sec_id or sec_id == section:
            continue
        title_words = set(words(c.title))
        sec_words = set(index.class_terms.get(sec_id, ()))
        name_hit = bool((q_set & sec_words) or (sec_terms & sec_words))
        v_words = set(words(vendor))
        title_hit = bool((q_set - v_words) & title_words) or bool(sec_terms & title_words)
        if name_hit or title_hit:
            prev = by_sec.get(sec_id, [0, 0])
            prev[0] += 1 if name_hit else 0
            prev[1] += 1 if title_hit else 0
            by_sec[sec_id] = prev
    if by_sec:
        best = max(by_sec, key=lambda s: (by_sec[s][0] > 0, by_sec[s][1], by_sec[s][0], len(index.groups[s])))
        return best
    return section


def rank_hardware_section(index, section, query, members):
    """В составных разделах оборудования («Клавиатуры, мыши, комплекты», «Наушники и микрофоны»,
    «Расходные материалы», «Жесткие диски» и др.) поднимаем наверх точный тип устройства из запроса,
    сохраняя исходный порядок качества внутри каждого уровня."""
    if not section or not members or len(members) <= 1:
        return members
    if index.cat.cards[members[0]].offers[0].domain != "hardware":
        return members
    q_norm = (query or "").casefold()
    if not q_norm:
        return members

    # Если пользователь явно просит комплект/набор — не понижаем комплекты
    wants_combo = bool(_COMBO_RE.search(q_norm))

    matched_rule = None
    for q_rx, exact_rx, close_rx, exclude_rx in _SUBTYPE_RULES:
        if q_rx.search(q_norm):
            matched_rule = (exact_rx, close_rx, exclude_rx)
            break

    if matched_rule is not None:
        exact_rx, close_rx, exclude_rx = matched_rule

        def tier(cid):
            title = index.cat.cards[cid].title
            has_exact = bool(exact_rx.search(title))
            has_excl = bool(exclude_rx and exclude_rx.search(title)) and not wants_combo
            if has_exact and not has_excl:
                return 3
            if has_exact:
                return 2
            if close_rx and close_rx.search(title) and not has_excl:
                return 2
            if has_excl and _HARD_DROP_MISCLASSIFIED.search(title):
                return 0
            return 1

        tiers = {cid: tier(cid) for cid in members}
        # Убираем явно ошибочно попавшие чужие товары (например акустика внутри «Графические планшеты»),
        # если в разделе есть подтверждённые товары точного типа.
        if max(tiers.values()) >= 3 and 0 in tiers.values():
            members = [cid for cid in members if tiers[cid] > 0]
        if len(set(tiers.values())) > 1:
            return sorted(members, key=tiers.get, reverse=True)
        return members

    # Общий фоллбэк для остальных составных разделов оборудования: совпадение слов типа в названии карточки
    from kuznitsa.index.feed import words
    q_terms = [w for w in words(q_norm) if len(w) >= 3 and w not in index.vendor_names]
    if not q_terms:
        return members
    q_set = set(q_terms)

    def generic_tier(cid):
        title = index.cat.cards[cid].title
        overlap = len(q_set & set(words(title)))
        if overlap:
            return 2 if not _ACCESSORY_RE.search(title) else 1
        return 0

    tiers = {generic_tier(cid) for cid in members}
    if len(tiers) > 1 and max(tiers) >= 2:
        return sorted(members, key=generic_tier, reverse=True)
    return members
