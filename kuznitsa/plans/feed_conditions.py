"""Разбор и применение условий покупки в поиске по фиду (цена, сортировка, исключения, происхождение, платформа, поддержка)."""
from dataclasses import dataclass
import re

from kuznitsa.index.feed import words
from kuznitsa.index.feed_language import publisher_keys
from kuznitsa.rank.variants import select
from kuznitsa.text import normalize
from kuznitsa.understand.spell_index import roman

# Единицы измерения, указывающие на количество, срок или тех. параметры (НЕ цену).
NON_PRICE_UNIT = re.compile(
    r"^\s*(?:пк|pk|пользовател\w*|сотрудник\w*|мест\w*|лиценз\w*|устройств\w*|узл\w*|узел|"
    r"сервер\w*|ядр\w*|ядер|процессор\w*|год\w*|лет|мес\w*|дюйм\w*|гб|тб|gb|tb|мб|mb|"
    r"ггц|ghz|мгц|mhz|вт|ва|va|порт\w*|шт\w*|штук\w*|чел\w*)\b",
    re.I,
)

UPGRADE_RE = re.compile(
    r"\b(?:апгрейд|обновлен\w*|обновить|переход|миграц\w*)\s+(.+?)\s+(?:с\s+)?(\d+(?:\.\d+)?)\s+(?:до|на)\s+(\d+(?:\.\d+)?)\b"
)

PRICE_RANGE_RE = re.compile(
    r"\bот\s+(?P<n1>\d+(?:\s+\d{3})*(?:[.,]\d{1,2})?)\s*(?P<s1>млн|миллион\w*|тыс\w*|[кk])?\s*(?P<c1>руб\w*\.?|₽|р\.?)?"
    r"\s+до\s+(?P<n2>\d+(?:\s+\d{3})*(?:[.,]\d{1,2})?)\s*(?P<s2>млн|миллион\w*|тыс\w*|[кk])?\s*(?P<c2>руб\w*\.?|₽|р\.?)?(?=\s|$|,)"
)

PRICE_DASH_RE = re.compile(
    r"(?<!\w)(?P<n1>\d+(?:\s+\d{3})*(?:[.,]\d{1,2})?)\s*(?P<s1>млн|миллион\w*|тыс\w*|[кk])?"
    r"\s*[-–—]\s*"
    r"(?P<n2>\d+(?:\s+\d{3})*(?:[.,]\d{1,2})?)\s*(?P<s2>млн|миллион\w*|тыс\w*|[кk])?\s*(?P<c2>руб\w*\.?|₽|р\.?)?(?=\s|$|,)"
)

PRICE_MAX_RE = re.compile(
    r"\b(?P<kw>не\s+дороже|дешевле|в\s+пределах|бюджет(?:\s+до)?|цена\s+до|до)"
    r"\s+(?P<n>\d+(?:\s+\d{3})*(?:[.,]\d{1,2})?)\s*(?P<s>млн|миллион\w*|тыс\w*|[кk])?\s*(?P<c>руб\w*\.?|₽|р\.?)?(?=\s|$|,)"
)

PRICE_MIN_RE = re.compile(
    r"\b(?P<kw>не\s+дешевле|дороже|свыше|цена\s+от|от)"
    r"\s+(?P<n>\d+(?:\s+\d{3})*(?:[.,]\d{1,2})?)\s*(?P<s>млн|миллион\w*|тыс\w*|[кk])?\s*(?P<c>руб\w*\.?|₽|р\.?)?(?=\s|$|,)"
)

VERSION_PREFIX_RE = re.compile(r"(?:\b\d+(?:\.\d+)?|\b(?:апгрейд|обновлен\w*|переход|верси\w*))\s+$")

FREE_RE = re.compile(r"\b(?:бесплатн\w*|даром)\b")

SORT_ASC_RE = re.compile(
    r"\b(?:сам\w*\s+дешев\w*|подешевле|недорог\w*|"
    r"дешев(?:ый|ая|ое|ые|ого|ому|ым|ых|ую)|"
    r"бюджетн\w*(?!\s+(?:учрежд|организ|сфер|сектор))|"
    r"по\s+возрастанию\s+цены|сначала\s+дешев\w*|минимальн\w*\s+цен\w*)\b"
)

SORT_DESC_RE = re.compile(
    r"\b(?:сам\w*\s+дорог\w*|подороже|топов\w*|флагманск\w*|премиальн\w*|"
    r"по\s+убыванию\s+цены|сначала\s+дорог\w*|максимальн\w*\s+цен\w*)\b"
)

MINUS_EXCLUDE_RE = re.compile(r"(?:^|\s)-(?P<target>[а-яёa-z][а-яёa-z0-9.]*)(?=$|\s|,)")

EXCLUDE_RE = re.compile(
    r"\b(?P<mk>только\s+не|но\s+не|кроме|без|не)\s+"
    r"(?P<target>[\w.+ -]+?(?:(?:\s*,\s*|\s+(?:и|или)\s+(?:(?:только\s+)?не\s+|без\s+|кроме\s+)?)"
    r"(?!(?:до|от|дешевле|дороже|для|на|под|в|с|по)\b)[\w.+ -]+?)*)"
    r"(?=$|\s+(?:до|от|дешевле|дороже|для|на|под|в|с|по)\b)"
)
EXCLUDE_SPLIT_RE = re.compile(r"\s*,\s*|\s+(?:и|или)\s+(?:(?:только\s+)?не\s+|без\s+|кроме\s+)?")

NON_EXCLUDE_NE = re.compile(
    r"^(?:дороже|дешевле|менее|более|меньше|больше|выше|ниже|нуж\w*|работа\w*|указан\w*|только|могу|знаю|подход\w*|старше|младше)\b"
)
NON_EXCLUDE_BEZ = re.compile(
    r"^(?:ндс|срок\w*|сертификат\w*|привязк\w*|огранич\w*|подписк\w*|установк\w*|доставк\w*|провод\w*|шум\w*|подсветк\w*|ключ\w*|диск\w*|коробк\w*|учета|учёта|ос|операционн\w*|предустановленн\w*|привод\w*|дисковод\w*|dvd|cd|рамк\w*|рамок|аккумулятор\w*|батаре\w*|подставк\w*)\b"
)
FOREIGN_WORD = re.compile(r"^(?:зарубежн\w*|иностранн\w*|импортн\w*)\b")

REGISTRY_RE = re.compile(
    r"\b(?:"
    r"(?:из|в)\s+(?:единого\s+|едином\s+)?реестр[ае]\s+(?:(?:российск\w*|отечественн\w*|минцифр\w*|рф)\s+)*(?:по|программ\w*)?"
    r"|(?:из|в)\s+(?:единого\s+|едином\s+)?реестр[ае]"
    r"|реестров\w*"
    r"|реестр\s+(?:(?:российск\w*|отечественн\w*|минцифр\w*)\s+)*(?:по|программ\w*)"
    r")\b"
)
ORIGIN_RU_RE = re.compile(r"\b(?:российск\w*|отечественн\w*|импортозамещ\w*)\b")

GENERIC_ORIGIN_SUBJECTS = frozenset({
    "по", "софт", "программа", "программы", "программное обеспечение",
    "решение", "решения", "система", "системы", "аналог", "аналоги", "инструменты",
})

PLATFORM_RE = re.compile(
    r"\b(?:для|под|на|for)\s+(mac(?:\s*os(?:\s*x)?)?|мак(?:ос)?|macintosh|android|андроид\w*|linux|линукс\w*|ios|айос|iphone|ipad|айфон\w*|windows|виндовс\w*)\b"
)

SUPPORT_PREFIX_RE = re.compile(
    r"^(?P<kind>сертификат(?:\s+на)?\s+(?:тех(?:ническ\w*)?\s*)?поддержк\w*|"
    r"тех(?:ническ\w*)?\s+поддержк\w*|техподдержк\w*|поддержк\w*|сопровожден\w*|внедрен\w*)"
    r"\s+(?:(?:по|программ\w*|ос|продукта?)\s+)?(?P<rest>.+)$"
)
SUPPORT_SUFFIX_RE = re.compile(
    r"^(?P<rest>.+?)\s+(?:с\s+)?(?P<kind>сертификат\w*\s+(?:на\s+)?(?:тех)?поддержк\w*|"
    r"тех(?:ническ\w*)?\s+поддержк\w*|техподдержк\w*|внедрен\w*)$"
)
GENERIC_SUPPORT_REST = frozenset({
    "по", "программ", "программы", "программного", "обеспечения", "пользователей",
    "клиентов", "сайта", "сети", "ит", "инфраструктуры", "оборудования", "рабочих", "мест",
})

# Быстрые пре-триггеры для extract() — чтобы на обычных запросах не прогонять лишние регулярки.
_SORT_OR_FREE_CUE = re.compile(r"бесплат|даром|дешев|дорог|дорож|бюджет|топов|флагман|премиал|возрастани|убывани|минимальн|максимальн")
_EXCLUDE_CUE = re.compile(r"(?:^|\s)-|\b(?:кроме|без|не)\b")
_ORIGIN_CUE = re.compile(r"реестр|российск|отечествен|импортозамещ")
_SUPPORT_CUE = re.compile(r"поддержк|сопровожден|внедрен")
_PLATFORM_CUE = re.compile(r"\b(?:для|под|на|for)\b")
_WORD_RE = re.compile(r"[\w]+")

# Курируемый список российских вендоров, сверенный с real-cards.tsv (дополнение к kb/vendors*.yaml).
RUSSIAN_VENDORS = frozenset({
    "лаборатория касперского", "kaspersky", "доктор веб", "dr web", "pro32",
    "ао р7", "р7", "мойофис", "myoffice", "группа астра", "астра", "astra",
    "яндекс", "yandex", "vk tech", "алми партнер", "алми партнёр",
    "ред софт", "базальт спо", "нанософт", "нанософт разработка", "аскон",
    "криптопро", "код безопасности", "инфотекс", "актив", "аладдин р д",
    "киберпротект", "usergate", "positive technologies", "смарт софт", "смарт cофт",
    "инфовотч", "infowatch", "с терра", "с терра сиэспи", "нпо эшелон",
    "панорама кб", "csoft development", "кредо диалог", "индорсофт",
    "scad soft", "арос", "лисси софт", "digt", "инсайдер", "стахановец",
    "1с", "1c", "битрикс", "контур", "скб контур", "постгрес профессиональный",
    "postgres professional", "контент ии", "content ai", "ams software", "амс софт",
    "rudesktop", "рудесктоп", "ассистент", "мойсклад", "kaiten", "weeek",
    "мегаплан", "directum", "директум", "elma", "элма", "тензор", "сбис",
    "катюша", "никотех", "амберит снг", "wss consulting", "нтп трубопровод",
    "appius", "интеллектуальные платформы и решения", "центр безопасности информации цби",
    "труконф", "trueconf", "вкурсе", "ivcs", "iva technologies", "салют", "сберджаз",
    "анлимитед продакшен", "новая облачная технология", "новые облачные технологии",
    "роса", "нтц ит роса", "базис", "ориони", "orion soft",
})

OFFICE_SUITE_QUERY = re.compile(r"\b(?:офис|офисн\w*\s+пакет\w*|офисн\w*\s+по|office)\b")
OFFICE_SUITE_TITLE = re.compile(r"р7-?офис|мойофис|настольный офис|офис|office|libreoffice|onlyoffice|alteroffice", re.I)
OFFICE_NON_SUITE = re.compile(r"\b(?:visio|project)\b", re.I)

PLATFORM_PATTERNS = {
    "macos": re.compile(r"\b(?:mac(?:\s*os|\s*osx|intosh)?|os\s*x|мак)\b", re.I),
    "android": re.compile(r"\b(?:android|андроид\w*|mobile|мобильн\w*|смартфон\w*)\b", re.I),
    "ios": re.compile(r"\b(?:ios|iphone|ipad|mobile|мобильн\w*|смартфон\w*)\b", re.I),
    "linux": re.compile(r"\b(?:linux|линукс|ubuntu|debian|centos|rhel|astra|ред\s*ос|альт)\b", re.I),
    "windows": re.compile(r"\b(?:windows|win32|win64)\b", re.I),
}

PLATFORM_LABELS = {
    "macos": "macOS",
    "android": "Android",
    "ios": "iOS",
    "linux": "Linux",
    "windows": "Windows",
}

EXCLUDE_ALIASES = {
    "касперский": ("kaspersky", "лаборатория касперского"),
    "каспер": ("kaspersky", "лаборатория касперского"),
    "kaspersky": ("kaspersky", "лаборатория касперского"),
    "майкрософт": ("microsoft", "майкрософт"),
    "microsoft": ("microsoft", "майкрософт"),
    "ms": ("microsoft", "майкрософт"),
    "доктор веб": ("dr web", "dr.web", "доктор веб"),
    "др веб": ("dr web", "dr.web", "доктор веб"),
    "dr web": ("dr web", "dr.web", "доктор веб"),
    "dr.web": ("dr web", "dr.web", "доктор веб"),
    "eset": ("eset", "нод32"),
    "pro32": ("pro32",),
    "р7": ("р7", "r7"),
    "мойофис": ("мойофис", "myoffice"),
    "adobe": ("adobe", "адоб"),
    "адоб": ("adobe", "адоб"),
    "autodesk": ("autodesk", "автодеск"),
    "леново": ("lenovo",),
    "lenovo": ("lenovo",),
    "самсунг": ("samsung",),
    "samsung": ("samsung",),
    "асус": ("asus",),
    "asus": ("asus",),
    "асер": ("acer",),
    "эйсер": ("acer",),
    "acer": ("acer",),
    "хп": ("hp", "hewlett packard"),
    "hp": ("hp", "hewlett packard"),
    "делл": ("dell",),
    "dell": ("dell",),
    "эппл": ("apple",),
    "apple": ("apple",),
    "лг": ("lg",),
    "lg": ("lg",),
    "мси": ("msi",),
    "msi": ("msi",),
    "аок": ("aoc",),
    "aoc": ("aoc",),
    "хуавей": ("huawei",),
    "huawei": ("huawei",),
}


@dataclass
class Conditions:
    subject: str
    raw_for_analogs: str
    price_min: float | None = None
    price_max: float | None = None
    sort: str | None = None
    exclude_vendors: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()
    exclude_labels: tuple[str, ...] = ()
    origin: str | None = None
    registry: bool = False
    platform: str | None = None
    service: str | None = None
    upgrade: bool = False
    active: bool = False
    free_requested: bool = False


def _fmt_rub(value):
    n = int(value) if float(value).is_integer() else value
    return f"{n:,}".replace(",", " ") + " ₽"


def _scale_amount(num_str, scale):
    amount = float(num_str.replace(" ", "").replace(",", "."))
    if not scale:
        return amount
    low = scale.lower()
    if low.startswith(("млн", "миллион")):
        return amount * 1_000_000
    if low.startswith("тыс") or low in ("к", "k"):
        return amount * 1_000
    return amount


def _clean_spaces(text):
    return " ".join(text.strip(" ,;:-").split())


def _canonical_platform(raw):
    low = raw.lower().strip()
    if low.startswith(("mac", "мак")):
        return "macos"
    if low.startswith(("android", "андроид")):
        return "android"
    if low.startswith(("linux", "линукс")):
        return "linux"
    if low.startswith(("ios", "айос", "iphone", "ipad", "айфон")):
        return "ios"
    if low.startswith(("windows", "виндовс")):
        return "windows"
    return None


def _vendor_origin_map(engine):
    cache = getattr(engine.kb, "_n4_vendor_origins", None)
    if cache is not None:
        return cache
    origins = {}
    for vid, row in engine.kb.rows.get("vendors", {}).items():
        origin = row.get("origin")
        if not origin:
            continue
        origins[vid] = origin
        for name in (row.get("name"), row.get("name_ru"), *(row.get("aliases") or [])):
            if not name:
                continue
            norm_name = " ".join(_WORD_RE.findall(normalize(str(name))))
            if norm_name:
                origins[norm_name] = origin
                compact = norm_name.replace(" ", "")
                if compact:
                    origins.setdefault(compact, origin)
    engine.kb._n4_vendor_origins = origins
    return origins


def _vendor_is_domestic(origins, v_id, v_name, cache):
    key = (v_id, v_name)
    hit = cache.get(key)
    if hit is not None:
        return hit
    res = False
    if v_id and v_id in origins:
        res = origins[v_id] == "russian"
    else:
        norm_v = " ".join(_WORD_RE.findall(normalize(v_name)))
        if norm_v in origins:
            res = origins[norm_v] == "russian"
        elif norm_v in RUSSIAN_VENDORS:
            res = True
        else:
            compact = norm_v.replace(" ", "")
            if compact in origins:
                res = origins[compact] == "russian"
            elif compact in RUSSIAN_VENDORS:
                res = True
            else:
                res = any(len(rv) >= 4 and rv in norm_v for rv in RUSSIAN_VENDORS)
    cache[key] = res
    return res


def _compute_domestic_card(index, origins, cid, vendor_cache):
    card = index.cat.cards[cid]
    for o in card.offers:
        if o.domestic or o.registry:
            return True
        country = (o.attrs.get("country") or "").casefold()
        if country in {"россия", "рф", "ru", "russia"}:
            return True
        if country:
            return False
    if cid in index.analogs.domestic:
        return True
    return _vendor_is_domestic(origins, card.vendor, card.offers[0].vendor or "", vendor_cache)


def prepare(index, engine):
    """Предподготовить словари и множества на индексе один раз (убирает O(N) сканы на запросе)."""
    if getattr(index, "_n4_prepared", False):
        return
    origins = _vendor_origin_map(engine)
    vendor_cache = {}
    domestic = set()
    registered = set()
    reg_set = index.analogs.registered
    for cid, card in index.cat.cards.items():
        if _compute_domestic_card(index, origins, cid, vendor_cache):
            domestic.add(cid)
        if cid in reg_set or any(o.registry for o in card.offers):
            registered.add(cid)
    index._n4_domestic_cids = frozenset(domestic)
    index._n4_registered_cids = frozenset(registered)

    # Индекс токенов названий вендоров -> множество vendor_id (без pymorphy3 на тысячах строк)
    vendor_tokens = {}
    for vname, vid in index.vendor_names.items():
        for w in _WORD_RE.findall(vname):
            vendor_tokens.setdefault(w, set()).add(vid)
    index._n4_vendor_tokens = vendor_tokens

    # Смежные разделы, сгруппированные по (domain, root)
    by_root = {}
    for sec, members in index.groups.items():
        if not members:
            continue
        o0 = index.cat.cards[members[0]].offers[0]
        by_root.setdefault((o0.domain, tuple(o0.category_path[:1])), []).append(sec)
    index._n4_by_root = by_root
    index._n4_siblings = {}

    # Слова программных классов (для точной проверки known_cand в PLATFORM_RE)
    soft_words = set()
    for sec in index.software_sections:
        for w in index.class_terms.get(sec, ()):
            if w not in _GENERIC_CLASS_WORDS:
                soft_words.add(w)
    index._n4_soft_class_words = frozenset(soft_words)
    index._n4_software_set = frozenset(index.software_sections)
    index._n4_prepared = True


def is_domestic_card(index, kb, engine, cid):
    prepare(index, engine)
    return cid in index._n4_domestic_cids


_GENERIC_CLASS_WORDS = frozenset({
    "для", "по", "программа", "программы", "приложение", "приложения", "система", "системы",
    "средство", "средства", "российский", "российские", "импортозамещение", "дом", "дома",
    "организация", "организаций", "бизнес", "бизнеса", "другой", "другие", "решение", "решения",
    "пакет", "пакеты", "инструмент", "инструменты", "сервис", "сервисы",
})


def _kb_vendor_lookup(engine):
    cache = getattr(engine.kb, "_n4_vendor_lookup", None)
    if cache is not None:
        return cache
    lookup = {}
    for _vid_key, row in engine.kb.rows.get("vendors", {}).items():
        names = [row.get("name"), row.get("name_ru"), *(row.get("aliases") or [])]
        norm_names = set()
        for n in names:
            if not n:
                continue
            nn = normalize(str(n))
            if nn:
                norm_names.add(nn)
                clean = " ".join(_WORD_RE.findall(nn))
                if clean:
                    norm_names.add(clean)
        extra = tuple(normalize(str(x)) for x in (row.get("name"), row.get("name_ru")) if x)
        entry = (tuple(norm_names), extra)
        for n in norm_names:
            if n:
                lookup.setdefault(n, []).append(entry)
    engine.kb._n4_vendor_lookup = lookup
    return lookup


def _resolve_exclude(index, engine, target):
    raw = target.strip(" ,;:-\"«»")
    if not raw:
        return (), (), ""
    prepare(index, engine)
    norm_t = normalize(raw)
    lem = " ".join(words(norm_t))
    vids = set()
    terms = set()

    # Формы-кандидаты: оригинал, лемма, варианты издателя, латинская транслитерация кириллицы
    cands = [norm_t, lem, *publisher_keys(norm_t)]
    if re.search("[а-я]", norm_t):
        r1 = roman(norm_t)
        r2 = roman(lem) if lem else ""
        if r1:
            cands.append(r1)
        if r2 and r2 != r1:
            cands.append(r2)
    cands = list(dict.fromkeys(c for c in cands if c))

    # Проверка по словарю вендоров фида и алиасам
    for cand in cands:
        vid = index.vendor_names.get(cand)
        if vid:
            vids.add(vid)
            terms.add(cand)
        if cand in EXCLUDE_ALIASES:
            for alias in EXCLUDE_ALIASES[cand]:
                terms.add(alias)
                v2 = index.vendor_names.get(alias) or index.vendor_names.get(" ".join(words(alias)))
                if v2:
                    vids.add(v2)

    # Проверка по slang / KB vendors
    for key in (norm_t, lem):
        if key in index.slang:
            field, members = index.slang[key]
            if field == "vendors":
                for cid in members:
                    if index.card_vendors.get(cid):
                        vids.add(index.card_vendors[cid])
                terms.add(key)

    kb_lookup = _kb_vendor_lookup(engine)
    for key in cands:
        for norm_names, extra in kb_lookup.get(key, ()):
            for n in norm_names:
                v = index.vendor_names.get(n)
                if v:
                    vids.add(v)
            terms.update(extra)
            terms.add(norm_t)

    # Быстрый поиск по предвычисленному индексу токенов вендоров (O(1) вместо скана vendor_names)
    if not vids and len(lem) >= 3:
        vendor_tokens = index._n4_vendor_tokens
        for cand in cands:
            toks = _WORD_RE.findall(cand) or words(cand)
            if not toks:
                continue
            sets = [vendor_tokens.get(w) or vendor_tokens.get(words(w)[0] if words(w) else w) for w in toks]
            if all(sets):
                matched = set.intersection(*sets)
                if matched:
                    vids.update(matched)
                    terms.add(cand)
                    break

    # Если это известный продукт/токен в каталоге
    if not vids and not terms:
        if any(w in index.postings for w in words(norm_t)):
            terms.add(norm_t)
            if lem:
                terms.add(lem)

    if vids or terms:
        terms.add(norm_t)
        if lem:
            terms.add(lem)
    return tuple(sorted(vids)), tuple(sorted(t for t in terms if t)), raw


def _is_software_subject(index, engine, cand):
    """Проверить, что предмет перед «для Mac/Android/Linux/iOS/Windows» — реальный программный предмет каталога."""
    prepare(index, engine)
    cwords = words(cand)
    if not cwords:
        return False
    # Железо и аксессуары («чехол для айфона», «мышь для mac») не получают программный фильтр платформы.
    if cand in index.hardware or any(w in index.hardware for w in cwords):
        return False
    soft_sections = index._n4_software_set
    sec = index.class_match(cand)
    if sec:
        return sec in soft_sections
    if index.products(cand, domain="software", fuzzy=False):
        return True
    if index.edition(cand):
        return True
    if cand in index.slang:
        _field, members = index.slang[cand]
        if members and index.cat.cards[members[0]].offers[0].domain in {"software", "cloud", "service"}:
            return True
    if cand in index.vendor_names:
        vid = index.vendor_names[cand]
        vcards = index.language.vendor_cards.get(vid, ())
        if vcards and any(index.cat.cards[c].offers[0].domain in {"software", "cloud", "service"} for c in vcards[:5]):
            return True
    if index.solutions.match(cand):
        return True
    if all(w in index._n4_soft_class_words for w in cwords):
        return True
    cand_norm = index.correct(cand)
    if cand_norm != cand:
        sec2 = index.class_match(cand_norm)
        if sec2:
            return sec2 in soft_sections
        if index.products(cand_norm, domain="software", fuzzy=False):
            return True
    return False


def extract(engine, norm, req):
    """Извлечь условия покупки из запроса до опознания предмета."""
    from . import feed_analogs

    index = engine.catalog.feed
    ignore = set(req.ignore)
    text = norm
    raw_for_analogs = norm
    price_min = None
    price_max = None
    sort = None
    exclude_vendors = []
    exclude_terms = []
    exclude_labels = []
    origin = None
    registry = False
    platform = None
    service = None
    upgrade = False
    active = False
    free_requested = False

    _is_analog_cache = None
    def is_analog():
        nonlocal _is_analog_cache
        if _is_analog_cache is None:
            _is_analog_cache = bool(feed_analogs.requested(norm))
        return _is_analog_cache

    if not req.verbatim:
        has_digit = any(ch.isdigit() for ch in text)

        # 1. Апгрейд / переход версии («апгрейд windows 10 до 11») — ДО разбора цены!
        if has_digit:
            m_upg = UPGRADE_RE.search(text)
            if m_upg:
                prod, _v1, v2 = m_upg.group(1).strip(), m_upg.group(2), m_upg.group(3)
                if prod and not re.search(r"руб|₽|тыс", m_upg.group(0)):
                    replacement = f"{prod} {v2}"
                    text = _clean_spaces(text[:m_upg.start()] + " " + replacement + " " + text[m_upg.end():])
                    raw_for_analogs = text
                    upgrade = True
                    active = True
                    has_digit = any(ch.isdigit() for ch in text)

        # 2. Границы цены (только если в тексте есть цифры)
        if has_digit:
            # 2a. Диапазон «от N до M»
            m = PRICE_RANGE_RE.search(text)
            if m and not NON_PRICE_UNIT.match(text[m.end():]):
                s1, s2 = m.group("s1"), m.group("s2")
                c1, c2 = m.group("c1"), m.group("c2")
                v1_raw = float(m.group("n1").replace(" ", "").replace(",", "."))
                v2_raw = float(m.group("n2").replace(" ", "").replace(",", "."))
                eff_s1 = s1 or (s2 if s2 and v1_raw < v2_raw and v1_raw < 1000 else None)
                v1 = _scale_amount(m.group("n1"), eff_s1)
                v2 = _scale_amount(m.group("n2"), s2)
                has_unit = bool(s1 or s2 or c1 or c2)
                if v1 <= v2 and (has_unit or v2 >= 100):
                    if "price_min" not in ignore:
                        price_min = v1
                    if "price_max" not in ignore:
                        price_max = v2
                    text = _clean_spaces(text[:m.start()] + " " + text[m.end():])
                    raw_for_analogs = text
                    active = True

            # 2b. Диапазон через тире «N–M» (с единицами или крупными числами, не годами)
            if price_min is None and price_max is None and ("-" in text or "–" in text or "—" in text):
                m = PRICE_DASH_RE.search(text)
                if m and not NON_PRICE_UNIT.match(text[m.end():]):
                    s1, s2, c2 = m.group("s1"), m.group("s2"), m.group("c2")
                    v1_raw = float(m.group("n1").replace(" ", "").replace(",", "."))
                    v2_raw = float(m.group("n2").replace(" ", "").replace(",", "."))
                    eff_s1 = s1 or (s2 if s2 and v1_raw < v2_raw and v1_raw < 1000 else None)
                    v1 = _scale_amount(m.group("n1"), eff_s1)
                    v2 = _scale_amount(m.group("n2"), s2)
                    has_unit = bool(s1 or s2 or c2)
                    is_years = (1990 <= v1 <= 2035 and 1990 <= v2 <= 2035 and not has_unit)
                    if v1 < v2 and not is_years and (has_unit or v1 >= 1000):
                        if "price_min" not in ignore:
                            price_min = v1
                        if "price_max" not in ignore:
                            price_max = v2
                        text = _clean_spaces(text[:m.start()] + " " + text[m.end():])
                        raw_for_analogs = text
                        active = True

            # 2c. Верхняя граница («до N», «дешевле N», «не дороже N», «в пределах N»)
            if price_max is None:
                m = PRICE_MAX_RE.search(text)
                if m and not NON_PRICE_UNIT.match(text[m.end():]):
                    kw = m.group("kw")
                    has_unit = bool(m.group("s") or m.group("c"))
                    prefix = text[:m.start()]
                    looks_like_version = (
                        kw == "до"
                        and not has_unit
                        and bool(VERSION_PREFIX_RE.search(prefix))
                    )
                    if not looks_like_version:
                        val = _scale_amount(m.group("n"), m.group("s"))
                        if "price_max" not in ignore:
                            price_max = val
                        text = _clean_spaces(text[:m.start()] + " " + text[m.end():])
                        raw_for_analogs = text
                        active = True

            # 2d. Нижняя граница («от N», «дороже N», «не дешевле N», «свыше N»)
            if price_min is None:
                m = PRICE_MIN_RE.search(text)
                if m and not NON_PRICE_UNIT.match(text[m.end():]):
                    kw = m.group("kw")
                    has_unit = bool(m.group("s") or m.group("c"))
                    val = _scale_amount(m.group("n"), m.group("s"))
                    if has_unit or kw != "от" or val >= 100:
                        if "price_min" not in ignore:
                            price_min = val
                        text = _clean_spaces(text[:m.start()] + " " + text[m.end():])
                        raw_for_analogs = text
                        active = True

        # 3. Запрос бесплатных версий и сортировка по цене
        if "sort" not in ignore and _SORT_OR_FREE_CUE.search(text):
            if not is_analog():
                m_free = FREE_RE.search(text)
                if m_free:
                    cand = _clean_spaces(text[:m_free.start()] + " " + text[m_free.end():])
                    if cand and cand not in GENERIC_ORIGIN_SUBJECTS:
                        free_requested = True
                        sort = "price_asc"
                        text = cand
                        raw_for_analogs = text
                        active = True
            if sort is None:
                m_asc = SORT_ASC_RE.search(text)
                if m_asc:
                    cand = _clean_spaces(text[:m_asc.start()] + " " + text[m_asc.end():])
                    if cand:
                        sort = "price_asc"
                        text = cand
                        raw_for_analogs = text
                        active = True
                else:
                    m_desc = SORT_DESC_RE.search(text)
                    if m_desc:
                        cand = _clean_spaces(text[:m_desc.start()] + " " + text[m_desc.end():])
                        if cand:
                            sort = "price_desc"
                            text = cand
                            raw_for_analogs = text
                            active = True

        # 4. Исключения («-X», «кроме X и Y», «только не X», «не X», «без X»)
        if "exclude" not in ignore and _EXCLUDE_CUE.search(text):
            # 4a. Минус-слова («антивирус -касперский», «ноутбук -lenovo -asus»)
            while True:
                m_min = MINUS_EXCLUDE_RE.search(text)
                if not m_min:
                    break
                target = m_min.group("target").strip()
                cand = _clean_spaces(text[:m_min.start()] + " " + text[m_min.end():])
                if not cand:
                    break
                vids, terms, label = _resolve_exclude(index, engine, target)
                if vids or terms or len(target) >= 3:
                    exclude_vendors.extend(vids)
                    exclude_terms.extend(terms or (normalize(target),))
                    exclude_labels.append(label)
                    text = cand
                    raw_for_analogs = text
                    active = True
                    continue
                break

            # 4b. Словесные исключения (в т.ч. цепочки «кроме asus и acer», «кроме lg, samsung»)
            while True:
                m_ex = EXCLUDE_RE.search(text)
                if not m_ex:
                    break
                mk = m_ex.group("mk").strip()
                target = m_ex.group("target").strip()
                if mk == "не" and NON_EXCLUDE_NE.match(target):
                    break
                if mk == "без" and NON_EXCLUDE_BEZ.match(target):
                    break
                if FOREIGN_WORD.match(target):
                    cand = _clean_spaces(text[:m_ex.start()] + " " + text[m_ex.end():])
                    if cand:
                        if "origin" not in ignore:
                            origin = "russian"
                        text = cand
                        raw_for_analogs = text
                        active = True
                        continue
                    break
                parts = [p.strip(" ,;:-") for p in EXCLUDE_SPLIT_RE.split(target) if p.strip(" ,;:-")]
                if not parts:
                    break
                explicit_mk = mk in ("кроме", "только не", "но не")
                resolved_all = []
                any_known = False
                for part in parts:
                    vids, terms, label = _resolve_exclude(index, engine, part)
                    if vids or terms:
                        any_known = True
                    elif not explicit_mk:
                        resolved_all = []
                        break
                    resolved_all.append((vids, terms or (normalize(part),), label or part))
                if resolved_all and (any_known or explicit_mk):
                    cand = _clean_spaces(text[:m_ex.start()] + " " + text[m_ex.end():])
                    if cand:
                        for vids, terms, label in resolved_all:
                            exclude_vendors.extend(vids)
                            exclude_terms.extend(terms)
                            exclude_labels.append(label)
                        text = cand
                        raw_for_analogs = text
                        active = True
                        continue
                break

        # 5. Происхождение и реестр («российский», «отечественный», «из реестра ...»)
        # Не трогаем запросы на аналоги («российский аналог Windows») — их обрабатывает feed_analogs.
        if not is_analog() and _ORIGIN_CUE.search(text):
            m_reg = REGISTRY_RE.search(text)
            if m_reg:
                cand = _clean_spaces(text[:m_reg.start()] + " " + text[m_reg.end():])
                if cand and cand not in GENERIC_ORIGIN_SUBJECTS:
                    if "registry" not in ignore:
                        registry = True
                    if "origin" not in ignore:
                        origin = "russian"
                    text = cand
                    active = True
            m_ru = ORIGIN_RU_RE.search(text)
            if m_ru:
                cand = _clean_spaces(text[:m_ru.start()] + " " + text[m_ru.end():])
                if cand and cand not in GENERIC_ORIGIN_SUBJECTS:
                    if "origin" not in ignore:
                        origin = "russian"
                    text = cand
                    active = True

        # 6. Техподдержка / внедрение конкретного продукта («техподдержка astra linux», «внедрение X»)
        if not is_analog() and "action" not in ignore and _SUPPORT_CUE.search(text):
            m_sup = SUPPORT_PREFIX_RE.match(text) or SUPPORT_SUFFIX_RE.match(text)
            if m_sup:
                rest = _clean_spaces(m_sup.group("rest"))
                kind = m_sup.group("kind")
                rest_words = set(words(rest))
                if rest and rest_words and not (rest_words <= GENERIC_SUPPORT_REST):
                    has_product = bool(
                        index.products(rest, fuzzy=False)
                        or index.products(index.correct(rest), fuzzy=False)
                        or index.edition(rest)
                        or rest in index.vendor_names
                        or " ".join(words(rest)) in index.vendor_names
                        or rest in index.slang
                        or index.sound_products(rest)[0]
                    )
                    if has_product:
                        service = "implementation" if kind.startswith("внедрен") else "support"
                        text = rest
                        raw_for_analogs = rest
                        active = True

        # 7. Платформа («для mac», «для android», «для linux», «для ios»)
        # Выносим платформу только если предмет — известное ПО каталога (отсекает «FableMuse для Mac», «игра для mac», «чехол для айфона»).
        if not is_analog() and "platform" not in ignore and _PLATFORM_CUE.search(text):
            m_plat = PLATFORM_RE.search(text)
            if m_plat:
                plat = _canonical_platform(m_plat.group(1))
                cand = _clean_spaces(text[:m_plat.start()] + " " + text[m_plat.end():])
                if plat and cand and _is_software_subject(index, engine, cand):
                    platform = plat
                    text = cand
                    active = True

        # Если после снятия условия (исключение/происхождение/сортировка) осталось голое «офис»,
        # раскрываем в «офисный пакет» — быстрее (без dense.encode) и точнее попадает в офисные пакеты.
        if active and text == "офис" and (exclude_vendors or exclude_terms or origin == "russian" or registry or sort):
            text = "офисный пакет"

    # Слияние с явными параметрами Request
    if req.filters.get("price_max") is not None and "price_max" not in ignore:
        pmax = float(req.filters["price_max"])
        price_max = min(price_max, pmax) if price_max is not None else pmax
    if req.filters.get("price_min") is not None and "price_min" not in ignore:
        pmin = float(req.filters["price_min"])
        price_min = max(price_min, pmin) if price_min is not None else pmin
    if req.sort in ("price_asc", "price_desc") and "sort" not in ignore:
        sort = req.sort
        active = True
    if req.filters.get("origin") == "russian" and "origin" not in ignore:
        origin = "russian"
        active = True
    if req.filters.get("registry") is True and "registry" not in ignore:
        registry = True
        origin = origin or "russian"
        active = True
    if req.exclude.get("vendor") and "exclude" not in ignore:
        raw_ex = req.exclude["vendor"]
        raw_ex = [raw_ex] if isinstance(raw_ex, str) else list(raw_ex)
        for v in raw_ex:
            exclude_vendors.append(v)
            exclude_terms.append(normalize(v))
            exclude_labels.append(v)
        active = True

    return Conditions(
        subject=text or norm,
        raw_for_analogs=raw_for_analogs or norm,
        price_min=price_min,
        price_max=price_max,
        sort=sort,
        exclude_vendors=tuple(dict.fromkeys(exclude_vendors)),
        exclude_terms=tuple(dict.fromkeys(exclude_terms)),
        exclude_labels=tuple(dict.fromkeys(exclude_labels)),
        origin=origin,
        registry=registry,
        platform=platform,
        service=service,
        upgrade=upgrade,
        active=active,
        free_requested=free_requested,
    )


def excluded_cids(index, cond):
    """Множество card_id, подпадающих под исключение (для основного списка, всех страниц и допродаж)."""
    if not cond or not (cond.exclude_vendors or cond.exclude_terms):
        return frozenset()
    blocked = set()
    for vid in cond.exclude_vendors:
        blocked.update(index.language.vendor_cards.get(vid, ()))
        blocked.update(index.cat.by.get("vendor", {}).get(vid, ()))
    for term in cond.exclude_terms:
        if not term:
            continue
        raw_toks = _WORD_RE.findall(term)
        if not raw_toks:
            continue
        # Пересечение по raw_terms (точное слово) и postings (лемма) — O(размер постинга) вместо O(всех карточек)
        raw_sets = [index.raw_terms.get(t) for t in raw_toks]
        if all(raw_sets):
            blocked.update(set.intersection(*raw_sets))
        lem_toks = words(term)
        if lem_toks:
            lem_sets = [index.postings.get(w) for w in lem_toks]
            if all(lem_sets):
                blocked.update(set.intersection(*lem_sets))
    return frozenset(blocked)


def _is_excluded(index, cond, cid, blocked=None):
    if blocked is not None and cid in blocked:
        return True
    if cond.exclude_vendors and index.card_vendors.get(cid) in cond.exclude_vendors:
        return True
    if blocked is not None or not cond.exclude_terms:
        return False
    card = index.cat.cards[cid]
    title_norm = normalize(card.title)
    vendor_norm = normalize(card.offers[0].vendor or "")
    combined_tokens = set(_WORD_RE.findall(title_norm)) | set(_WORD_RE.findall(vendor_norm))
    for term in cond.exclude_terms:
        t_tokens = set(_WORD_RE.findall(term))
        if t_tokens and t_tokens <= combined_tokens:
            return True
    return False


def _sibling_sections(index, engine, section, prefer_domestic=False):
    if not section or section not in index.groups or not index.groups[section]:
        return ()
    prepare(index, engine)
    cache_key = (section, prefer_domestic)
    cached = index._n4_siblings.get(cache_key)
    if cached is not None:
        return cached
    anchor = index.cat.cards[index.groups[section][0]].offers[0]
    same_root = index._n4_by_root.get((anchor.domain, tuple(anchor.category_path[:1])), ())
    siblings = [k for k in same_root if k != section]
    if prefer_domestic:
        siblings.sort(key=lambda k: (k in index.analogs.domestic_sections, len(index.groups[k])), reverse=True)
    else:
        siblings.sort(key=lambda k: len(index.groups[k]), reverse=True)
    result = tuple(siblings)
    index._n4_siblings[cache_key] = result
    return result


def _match_platform_offer(index, cid, platform):
    if platform in index.platform_offers and cid in index.platform_offers[platform]:
        return index.platform_offers[platform][cid]
    pattern = PLATFORM_PATTERNS.get(platform)
    if not pattern:
        return None
    card = index.cat.cards[cid]
    if pattern.search(card.title):
        return card.offers[0]
    for o in card.offers[:40]:
        if o.platforms and any(pattern.search(p) for p in o.platforms):
            return o
        ap = o.attrs.get("platform")
        if ap and pattern.search(str(ap)):
            return o
        if pattern.search(o.name):
            return o
    if card.offers and card.offers[0].description and pattern.search(card.offers[0].description):
        return card.offers[0]
    return None


def _match_support_offer(card, service):
    is_impl = service == "implementation"
    best = None
    best_key = None
    for o in card.offers:
        op = str(o.attrs.get("operation") or "").lower()
        name_l = o.name.lower()
        desc_l = (o.description or "").lower()
        if is_impl:
            hit = "внедрен" in name_l or "внедрен" in op or "внедрен" in desc_l or o.kind == "service"
        else:
            hit = (
                o.lic.action == "support"
                or "поддержк" in op
                or "поддержк" in name_l
                or "support" in name_l
                or "техподдержк" in desc_l
            )
        if not hit:
            continue
        key = (o.available, o.price is not None and not o.price_on_request, o.lic.audience in (None, "business"), -(o.price or 0))
        if best_key is None or key > best_key:
            best_key = key
            best = o
    return best


def _card_display_price(index, cid, preferred, selections):
    if cid in selections:
        o = selections[cid][0]
        if o.price is not None and not o.price_on_request and o.price > 0:
            return float(o.price)
    if cid in preferred:
        o = preferred[cid]
        if o.price is not None and not o.price_on_request and o.price > 0:
            return float(o.price)
    card = index.cat.cards[cid]
    if card.price_from is not None and card.price_from > 0:
        return float(card.price_from)
    prices = [float(o.price) for o in card.offers if o.price is not None and not o.price_on_request and o.price > 0]
    return min(prices) if prices else None


def _pick_offer_in_range(card, profile, price_min, price_max, qty, renewal, sort=None):
    filters = {}
    if price_min is not None:
        filters["price_min"] = price_min
    if price_max is not None:
        filters["price_max"] = price_max
    if qty and qty.get("metric"):
        filters["metric"] = qty["metric"]
    if renewal:
        filters["action"] = "renewal"
    sel = select(card, profile, filters, {}, qty, prefer_lowest=(sort == "price_asc"))
    if sel:
        return sel
    if qty or renewal:
        return None
    candidates = [
        o for o in card.offers
        if o.price is not None and not o.price_on_request and o.price > 0
        and (price_min is None or o.price >= price_min)
        and (price_max is None or o.price <= price_max)
    ]
    if not candidates:
        return None
    if sort == "price_desc":
        o = max(candidates, key=lambda x: (x.available, x.price))
    else:
        o = min(candidates, key=lambda x: (not x.available, x.price))
    return (o, None, None)


def apply_conditions(engine, req, profile, cond, ids, section, preferred, selections, qty, renewal, note):
    """Применить извлечённые условия к списку кандидатов. Возвращает (ids, section, note, price_relaxed)."""
    index = engine.catalog.feed
    prepare(index, engine)
    ids = list(ids)
    price_relaxed = False
    blocked = excluded_cids(index, cond)

    # 1. Исключение вендоров / продуктов
    if blocked or cond.exclude_vendors or cond.exclude_terms:
        filtered = [cid for cid in ids if not _is_excluded(index, cond, cid, blocked)]
        if section and len(filtered) < 4:
            seen = set(filtered)
            for sib in _sibling_sections(index, engine, section, prefer_domestic=True):
                for cid in index.groups[sib]:
                    if cid not in seen and not _is_excluded(index, cond, cid, blocked):
                        filtered.append(cid)
                        seen.add(cid)
        if filtered:
            if not any(index.card_sections[cid] == section for cid in filtered[:4]):
                section = index.card_sections[filtered[0]]
            ids = filtered
        else:
            ids = []

    # 2. Российское ПО / реестр
    if cond.origin == "russian" or cond.registry:
        domestic_cids = index._n4_domestic_cids
        registered_cids = index._n4_registered_cids

        dom_filtered = [cid for cid in ids if cid in domestic_cids]
        # Добираем из родственных отечественных разделов ТОЛЬКО если в текущем разделе не хватает российских товаров (< 4)
        # (например, «Офисные пакеты» -> «Российские офисные приложения»), не загрязняя уже заполненный раздел («Антивирусы»).
        if section and len(dom_filtered) < 4:
            seen = set(dom_filtered)
            extra = []
            for sib in _sibling_sections(index, engine, section, prefer_domestic=True):
                for cid in index.groups[sib]:
                    if cid not in seen and cid not in blocked and cid in domestic_cids:
                        extra.append(cid)
                        seen.add(cid)
            if extra:
                dom_filtered = dom_filtered + extra if dom_filtered else extra

        in_domestic_sec = bool(section and section in index.analogs.domestic_sections)
        if cond.registry and dom_filtered and not in_domestic_sec:
            reg_hits = [cid for cid in dom_filtered if cid in registered_cids]
            if len(reg_hits) >= 4:
                filtered = reg_hits
            elif reg_hits:
                reg_set = set(reg_hits)
                filtered = reg_hits + [cid for cid in dom_filtered if cid not in reg_set]
            else:
                # В фиде у части отечественных карточек флаг registry не заполнен — всё равно отсекаем зарубежных вендоров
                filtered = dom_filtered
        else:
            filtered = dom_filtered

        if filtered:
            if section and not any(index.card_sections[cid] == section for cid in filtered[:4]):
                section = index.card_sections[filtered[0]]
            ids = filtered
            if (
                not cond.sort
                and section
                and section in index._n4_software_set
                and section not in index.analogs.domestic_sections
                and not index.solutions.match(cond.subject)
            ):
                f_rank = index.flagships.rank
                ids = sorted(
                    ids,
                    key=lambda cid: (f_rank.get(cid, 0) > 0, f_rank.get(cid, 0)),
                    reverse=True,
                )

    # 2b. Уточнение для «офисный пакет» / «офис»: настоящие офисные пакеты выше Visio/Project и почтовых сервисов
    if ids and (cond.origin == "russian" or cond.registry or cond.exclude_vendors or cond.exclude_terms or cond.sort) and OFFICE_SUITE_QUERY.search(cond.subject):
        office_hits = [
            cid for cid in ids
            if OFFICE_SUITE_TITLE.search(index.cat.cards[cid].title)
            and not OFFICE_NON_SUITE.search(index.cat.cards[cid].title)
        ]
        if section and len(office_hits) < 4:
            seen = set(office_hits)
            for sib in _sibling_sections(index, engine, section, prefer_domestic=bool(cond.origin or cond.registry)):
                for cid in index.groups[sib]:
                    if cid in seen or cid in blocked:
                        continue
                    if (cond.origin == "russian" or cond.registry) and cid not in index._n4_domestic_cids:
                        continue
                    title = index.cat.cards[cid].title
                    if OFFICE_SUITE_TITLE.search(title) and not OFFICE_NON_SUITE.search(title):
                        office_hits.append(cid)
                        seen.add(cid)
        if office_hits:
            if cond.sort:
                ids = office_hits
            else:
                hit_set = set(office_hits)
                ids = office_hits + [cid for cid in ids if cid not in hit_set]

    # 3. Техподдержка / внедрение — карточки с вариантом поддержки первыми
    if cond.service and ids:
        with_sup = []
        without_sup = []
        for cid in ids:
            offer = _match_support_offer(index.cat.cards[cid], cond.service)
            if offer is not None:
                preferred[cid] = offer
                with_sup.append(cid)
            else:
                without_sup.append(cid)
        ids = with_sup + without_sup

    # 4. Платформа — карточки с указанной платформой первыми (+ добор из родственных разделов того же департамента)
    if cond.platform and ids:
        matched = []
        others = []
        seen = set(ids)
        for cid in ids:
            offer = _match_platform_offer(index, cid, cond.platform)
            if offer is not None:
                preferred.setdefault(cid, offer)
                matched.append(cid)
            else:
                others.append(cid)
        if section and len(matched) < 4:
            sec_words = set(index.class_terms.get(section, ())) - _GENERIC_CLASS_WORDS
            for sib in _sibling_sections(index, engine, section):
                sib_words = set(index.class_terms.get(sib, ())) - _GENERIC_CLASS_WORDS
                if sec_words and not (sec_words & sib_words):
                    continue
                for cid in index.groups[sib]:
                    if cid in seen or cid in blocked:
                        continue
                    if cond.origin == "russian" and cid not in index._n4_domestic_cids:
                        continue
                    offer = _match_platform_offer(index, cid, cond.platform)
                    if offer is not None:
                        preferred.setdefault(cid, offer)
                        matched.append(cid)
                        seen.add(cid)
        ids = matched + others

    # 5. Границы цены (price_min / price_max) — единый механизм фильтрации и честного фоллбэка
    if ids and (cond.price_min is not None or cond.price_max is not None):
        before = list(ids)
        in_range = []
        new_selections = {}
        for cid in ids:
            card = index.cat.cards[cid]
            pf = card.price_from
            if cond.price_max is not None and not qty and (pf is None or pf > cond.price_max):
                continue
            if cond.price_min is not None and pf is not None and pf < cond.price_min:
                continue
            sel = _pick_offer_in_range(card, profile, cond.price_min, cond.price_max, qty, renewal, cond.sort)
            if not sel:
                continue
            in_range.append(cid)
            new_selections[cid] = sel
        if not in_range and cond.price_min is not None:
            for cid in ids:
                sel = _pick_offer_in_range(index.cat.cards[cid], profile, cond.price_min, cond.price_max, qty, renewal, cond.sort)
                if sel:
                    in_range.append(cid)
                    new_selections[cid] = sel
        if in_range:
            selections.update(new_selections)
            ids = in_range
        elif req.filters.get("price_max") is not None or req.filters.get("price_min") is not None:
            # Явный параметр фильтра API: строго пустой список при отсутствии совпадений
            ids = []
            note = "В указанном диапазоне цен предложений нет."
        else:
            # Текстовая граница цены невыполнима — не обнуляем ответ, показываем ближайшие по цене карточки того же предмета
            price_relaxed = True
            if cond.price_max is not None and cond.price_min is None:
                def key_max(cid):
                    p = _card_display_price(index, cid, preferred, selections)
                    return (p is None, p if p is not None else float("inf"))
                ids = sorted(before, key=key_max)
                note = f"Дешевле {_fmt_rub(cond.price_max)} подходящих предложений нет, самые доступные — ниже."
            elif cond.price_min is not None and cond.price_max is None:
                def key_min(cid):
                    p = _card_display_price(index, cid, preferred, selections)
                    return (p is None, -(p if p is not None else 0.0))
                ids = sorted(before, key=key_min)
                note = f"Дороже {_fmt_rub(cond.price_min)} подходящих предложений нет, ближайшие по цене — ниже."
            else:
                def key_band(cid):
                    p = _card_display_price(index, cid, preferred, selections)
                    if p is None:
                        return (True, float("inf"))
                    dist = min(abs(p - cond.price_min), abs(p - cond.price_max))
                    return (False, dist)
                ids = sorted(before, key=key_band)
                note = f"В диапазоне от {_fmt_rub(cond.price_min)} до {_fmt_rub(cond.price_max)} предложений нет, ближайшие по цене — ниже."

    # 6. Сортировка по цене («самый дешёвый», «недорогой», «бесплатный», «самый дорогой»)
    if cond.sort in ("price_asc", "price_desc") and ids:
        reverse = cond.sort == "price_desc"
        for cid in ids:
            card = index.cat.cards[cid]
            priced = [o for o in card.offers if o.price is not None and not o.price_on_request and o.price > 0]
            if priced and cid not in selections:
                preferred[cid] = max(priced, key=lambda o: o.price) if reverse else min(priced, key=lambda o: o.price)

        def sort_key(cid):
            card = index.cat.cards[cid]
            p = card.price_from if (card.price_from is not None and card.price_from > 0) else _card_display_price(index, cid, preferred, selections)
            if p is None:
                return (1, 0.0)
            return (0, -float(p) if reverse else float(p))

        ids = sorted(ids, key=sort_key)

    # 7. Честное пояснение для запросов бесплатных версий (без срабатывания ABSENT_NOTE)
    if cond.free_requested and ids and not price_relaxed:
        note = "Бесплатных версий нет — ниже показаны самые доступные лицензии."

    return ids, section, note, price_relaxed


def populate_result(cond, result, chips):
    """Отразить распознанные условия в understood.filters, understood.exclude и chips."""
    filters = result["understood"]["filters"]
    exclude = result["understood"]["exclude"]

    if cond.price_min is not None:
        filters["price_min"] = cond.price_min
        chips.append(dict(key="price_min", label=f"От {_fmt_rub(cond.price_min)}", removable=True))
    if cond.price_max is not None and "price_max" not in filters:
        filters["price_max"] = cond.price_max
        chips.append(dict(key="price_max", label=f"До {_fmt_rub(cond.price_max)}", removable=True))
    if cond.sort:
        filters["sort"] = cond.sort
        label = "Сначала дешёвые" if cond.sort == "price_asc" else "Сначала дорогие"
        chips.append(dict(key="sort", label=label, removable=True))
    if cond.exclude_vendors or cond.exclude_terms:
        exclude["vendor"] = list(cond.exclude_vendors or cond.exclude_terms)
        shown = ", ".join(cond.exclude_labels or cond.exclude_terms)
        chips.append(dict(key="exclude", label=f"Кроме {shown}", removable=True))
    if cond.origin == "russian":
        filters["origin"] = "russian"
        chips.append(dict(key="origin", label="Российское ПО", removable=True))
    if cond.registry:
        filters["registry"] = True
        chips.append(dict(key="registry", label="Из реестра ПО", removable=True))
    if cond.platform:
        filters["platform"] = [cond.platform]
        chips.append(dict(key="platform", label=f"Для {PLATFORM_LABELS.get(cond.platform, cond.platform)}", removable=True))
    if cond.service:
        filters["action"] = "support" if cond.service == "support" else "service"
        label = "Техподдержка" if cond.service == "support" else "Внедрение"
        chips.append(dict(key="action", label=label, removable=True))
    if cond.upgrade:
        filters["action"] = "upgrade"
        chips.append(dict(key="action", label="Апгрейд", removable=True))
