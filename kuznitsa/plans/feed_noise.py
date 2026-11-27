"""Очистка покупательского шума, извлечение условий и проверка мусорных запросов на фиде."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
import yaml

from kuznitsa.index.feed import STOP, words
from kuznitsa.text import normalize, tokens
from kuznitsa.understand.normalize import lookup_skus
from kuznitsa.understand.spell_index import cyrillic, roman
from .feed_query import PRICE_LIMIT, license_request

GARBAGE_NOTE = (
    "Не нашли такого в каталоге программ и оборудования. "
    "Попробуйте название программы, производителя или задачу."
)

# Запросы, которые действительно требуют старого конвейера (спецификации, сравнения, «мои лицензии», реестр).
FEED_COMPLEX = re.compile(
    r"\n|;|\b(?:сравни\w*|комплект\w*|мои\s+лицензи\w*|мои\s+заказ\w*|истор\w*\s+заказ\w*|статус\s+заказ\w*|заказ(?:а|ов|ы|е|у|ом)?|куплен\w*|реестр\w*)\b"
)

HTML_TAG = re.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9]*\b[^>]*>")
SQL_INJECTION = re.compile(
    r"(?:^|[\s'\"])(?:or|and)\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+"
    r"|['\"].*--"
    r"|\bunion\s+select\b"
    r"|\bdrop\s+table\b"
    r"|;\s*(?:delete|drop|insert|update|select)\b",
    re.I,
)
KEYBOARD_MASH_TOKENS = (
    "qwerty", "asdf", "zxcv", "qazw", "wsx", "edc", "rfv", "tgb", "yhn", "ujm",
    "йцук", "фыва", "ячсм",
)

UPGRADE_TO = re.compile(
    r"^(?:апгрейд|upgrade|обновлен\w*|обновить|переход)\s+(?:с\s+)?(.+?)\s+(\d+(?:\.\d+)?)\s+(?:до|на)\s+(\d+(?:\.\d+)?)\b(.*)$"
)
UPGRADE_MID = re.compile(
    r"^(.+?)\s+(\d+(?:\.\d+)?)\s+(?:апгрейд|upgrade|обновлен\w*|обновить|переход)\s+(?:до|на)\s+(\d+(?:\.\d+)?)\b(.*)$"
)
CHEAPER_LIMIT = re.compile(
    r"\bдешевле\s+(\d+(?: \d{3})*(?:[.,]\d{1,2})?)\s*(тыс\w*|млн|[кk])?\s*(?:руб(?:лей|ля|ль)?\.?|₽|р\.)?\b"
)

ANALOG_MODIFIERS = re.compile(
    r"\b(?:"
    r"дешевле|подешевле|недорог\w*|бюджетн\w*|деш[её]в\w*|"
    r"бесплатн\w*|свободн\w*|open\s*source|opensource|free|cheaper|"
    r"лучш\w*|получше|хорош\w*|современн\w*|популярн\w*|полн\w*|ближайш\w*|"
    r"российск\w*|отечественн\w*|русск\w*|импортозамещ\w*|"
    r"в\s+россии|в\s+рф|для\s+россии|из\s+реестра"
    r")\b",
    re.I,
)

IMPORT_SUB_ANALOG = re.compile(
    r"^(?:импортозамещен\w*|замещен\w*)\s+(?:по\s+|программ\w*\s+|сервер\w*\s+)?(.+)$",
    re.I,
)
GENERIC_IMPORT_SUB_TARGETS = frozenset({
    "по", "софт", "софта", "программ", "программы", "программа",
    "офис", "офиса", "ит", "it", "инфраструктуры", "инфраструктура",
})

VENDOR_CATALOG_PATTERNS = (
    re.compile(r"^(?:все|всё)\s+(?:от|у|продукты|программы|решения|товары)\s+(?:компании\s+|вендора\s+|производителя\s+)?(.+)$"),
    re.compile(r"^(?:продукты|программы|решения|товары|линейка|линейки|по|софт|каталог|ассортимент)\s+(?:от\s+|компании\s+|вендора\s+|производителя\s+)?(.+)$"),
    re.compile(r"^(?:что\s+есть|что\s+продается|что\s+выпускает|что\s+предлагает)\s+(?:у|от)\s+(?:компании\s+|вендора\s+|производителя\s+)?(.+)$"),
    re.compile(r"^(.+?)\s+(?:каталог|все\s+продукты|все\s+программы|все\s+товары)$"),
)

# Покупательский шум, англоязычные обёртки и закупочные префиксы.
LEAD_ACTION = re.compile(
    r"^(?:(?:хочу\s+)?(?:купить|приобрести|заказать|скачать|загрузить|установить|поставить|найти|подобрать|получить|оформить)"
    r"|цена|цены|стоимость|прайс(?:-лист)?|сколько\s+стоит|поч[её]м"
    r"|ключ(?:и)?(?:\s+активации)?|код\s+активации|серийный\s+номер|активация"
    r"|право\s+на\s+использование(?:\s+(?:программ\w*|операционн\w*\s+систем\w*|по))?"
    r"|расширени\w*\s+лицензи\w*(?:\s+на)?"
    r"|докупить\s+лицензи\w*(?:\s+на)?"
    r"|buy|download|price(?:\s+of)?|license(?:\s+for)?|licence(?:\s+for)?|key(?:\s+for)?"
    r")\s+(?:(?:на|для|от)\s+)?"
)
TRAIL_ACTION = re.compile(
    r"\s+(?:купить|скачать|цена|цены|стоимость|прайс|price|buy|download|license|licence|key)$"
)
UPGRADE_ACTION = re.compile(r"^(?:обновлен\w*|обновить|апгрейд|upgrade)\s+(?:(?:на|до)\s+)?")

TERM_NUM = re.compile(r"\b(?:на\s+)?(\d{1,2})\s*(год\w*|лет|мес\w*)\b")
TERM_ONE_YEAR = re.compile(r"\b(?:на\s+год|годов\w*(?:\s+подписк\w*)?)\b")
TERM_ONE_MONTH = re.compile(r"\b(?:на\s+месяц|месячн\w*(?:\s+подписк\w*)?)\b")
PERPETUAL = re.compile(r"\b(?:без\s+подписк\w*|бессрочн\w*(?:\s+лицензи\w*)?|навсегда|вечн\w*|постоянн\w*\s+лицензи\w*)\b")
SUBSCRIPTION = re.compile(r"\bподписк\w*\b")

DELIVERY_ESD = re.compile(r"\b(?:электронн\w*\s+(?:лицензи\w*|верси\w*|ключ\w*|поставк\w*)|esd)\b")
DELIVERY_BOX = re.compile(r"\b(?:коробочн\w*\s+(?:верси\w*|лицензи\w*|поставк\w*)|коробка|fpp)\b")
LICENSE_OEM = re.compile(r"\b(?:oem|оем)\b")

AUDIENCE_EDU = re.compile(r"\b(?:академическ\w*(?:\s+лицензи\w*)?|для\s+вузов)\b")
AUDIENCE_BIZ = re.compile(r"\b(?:для\s+юр\.?\s*лиц|для\s+юридическ\w*\s+лиц|юр\.?\s*лицам|для\s+команд|for\s+teams)\b")
AUDIENCE_HOME = re.compile(r"\b(?:для\s+физ\.?\s*лиц|для\s+физическ\w*\s+лиц|физ\.?\s*лицам)\b")

ARCH_TECH = re.compile(
    r"\b(?:x64|x86(?:[-_]64)?|amd64|arm64|64[- ]?bit|32[- ]?bit|64[- ]?бит\w*|32[- ]?бит\w*|64[- ]?разряд\w*|32[- ]?разряд\w*)\b"
)
CORE_QTY = re.compile(r"\b(\d{1,3})\s*(?:core|cores|ядер|ядра|ядро)\b")
WRAPPER_LICENSE = re.compile(r"\b(?:лицензи(?:я|ю|и|й|ей)(?:\s+на)?|верси(?:я|ю|и|ей))\b")

# Разговорная транслитерация брендов в начале/внутри составного запроса.
SPOKEN_BRAND_TOKENS = (
    (re.compile(r"\bвиндоу[сз]\b"), "windows"),
    (re.compile(r"\bвиндов[сз]\b"), "windows"),
    (re.compile(r"\bвинда\b"), "windows"),
    (re.compile(r"\boffice\s*365\b"), "office 365"),
    (re.compile(r"^(?:мс|ms)\s+(?=(?:sql|office|windows|visio|project|exchange|visual|365|word|excel|outlook|powerpoint)\b)"), "microsoft "),
    (re.compile(r"\b(автокад|autocad)\s+лт\b"), r"\1 lt"),
)

# Слова-редакции/квалификаторы, которые сами по себе не образуют название продукта.
EDITION_ONLY_WORDS = frozenset({
    "pro", "про", "проф", "home", "хоум", "standard", "стандарт", "enterprise",
    "ultimate", "professional", "профессиональный", "business", "бизнес",
    "basic", "starter", "lite", "lt", "dc", "cc", "e1", "e3", "e5", "f1", "f3",
    "oem", "esd", "box", "fpp", "x64", "x86", "core", "cores", "plus", "premium",
    "плюс", "премиум", "лайт", "базовый", "базовая", "расширенный", "расширенная",
    "корпоративный", "корпоративная", "оптимальный", "домашний", "персональный",
    "персональная", "учебный", "учебная",
    "edu", "academic", "team", "teams", "suite", "cloud", "online", "desktop",
    "юрлиц", "юрлицам", "физлиц", "физлицам", "для", "на", "от", "под",
})

COLLOQUIAL_KB_PATH = Path(__file__).resolve().parents[2] / "kb" / "feed_colloquial_n1.yaml"


@lru_cache(1)
def load_colloquial_kb() -> tuple[dict[str, str], dict[str, str]]:
    """Загружает словарь разговорных продуктов и английских классов ПО из kb/feed_colloquial_n1.yaml."""
    if not COLLOQUIAL_KB_PATH.is_file():
        return {}, {}
    data = yaml.load(COLLOQUIAL_KB_PATH.read_text(encoding="utf-8"), Loader=yaml.CSafeLoader) or {}
    spoken = {
        _clean_spaces(normalize(str(k))): str(v).strip()
        for k, v in (data.get("spoken_products") or {}).items()
        if k and v
    }
    english = {
        _clean_spaces(normalize(str(k))): _clean_spaces(normalize(str(v)))
        for k, v in (data.get("english_classes") or {}).items()
        if k and v
    }
    return spoken, english


@dataclass
class CleanQuery:
    subject: str
    filters: dict
    qty: dict | None
    chips: list
    changed: bool


def _clean_spaces(text: str) -> str:
    return " ".join(text.strip(" ,;:-").split())


def pre_normalize(raw_q: str, norm_q: str) -> str:
    """Раннее раскрытие типовых сленговых маркеров с пунктуацией (m$ office -> microsoft office)."""
    out = norm_q
    if re.search(r"\b(?:m|м)\$\s+", raw_q or "", re.I):
        out = re.sub(r"\b(?:m|м)\$?\s+", "microsoft ", out, count=1)
    elif re.search(r"\b(?:m|м)\$\s+", out, re.I):
        out = re.sub(r"\b(?:m|м)\$\s+", "microsoft ", out, count=1)
    return _clean_spaces(out)


def translate_english_class(text: str) -> str | None:
    """Переводит английское название класса/задачи ПО в эквивалентный русский запрос по словарю KB."""
    s = _clean_spaces(normalize(text))
    if not s or not re.search(r"[a-z]", s):
        return None
    _, english = load_colloquial_kb()
    if s in english:
        return english[s]
    # Снятие английского хвоста "software" / "system" / "tool" / "tools" при совпадении ядра в словаре.
    stripped = re.sub(r"\s+(?:software|system|systems|tool|tools|app|apps|program|programs|solution|solutions)$", "", s)
    if stripped != s and stripped in english:
        return english[stripped]
    return None


def extract_import_sub_analog(index, text: str) -> str | None:
    """Распознаёт «импортозамещение <продукт>» (не общее «импортозамещение ПО»)."""
    from .feed_guard import lookup_analog

    s = _clean_spaces(normalize(text))
    m = IMPORT_SUB_ANALOG.match(s)
    if not m:
        return None
    tail = clean_analog_subject(m.group(1))
    if not tail or tail in GENERIC_IMPORT_SUB_TARGETS:
        return None
    if lookup_analog(index, tail, fuzzy=True):
        return tail
    return None


def is_edition_only(text: str) -> bool:
    """True, если строка состоит только из слов-редакций/квалификаторов и чисел (без имени продукта)."""
    terms = words(text)
    if not terms:
        return True
    return all(w in EDITION_ONLY_WORDS or w.isdecimal() for w in terms)


def is_garbage_syntax(raw_q: str, norm_q: str, index, catalog) -> str | None:
    """Быстрая синтаксическая проверка на HTML, SQL-инъекции, пустой/знаковый ввод, одну букву, mash и пустые числа."""
    raw = (raw_q or "").strip()
    if not raw:
        return "symbols"
    if HTML_TAG.search(raw) or SQL_INJECTION.search(raw):
        return "html_sql"
    if not re.search(r"[а-яёa-z0-9]", norm_q, re.I):
        return "symbols"
    alnum = re.findall(r"[а-яёa-z0-9]+", norm_q, re.I)
    if len(alnum) == 1 and len(alnum[0]) == 1 and alnum[0].isalpha():
        return "single_char"
    if len(alnum) == 1 and len(alnum[0]) >= 6 and alnum[0].isalpha():
        tok = alnum[0].lower()
        if any(m in tok for m in KEYBOARD_MASH_TOKENS):
            return "keyboard_mash"
    if re.fullmatch(r"\d+", norm_q):
        if not (
            norm_q in catalog.source_codes
            or norm_q in index.aliases
            or norm_q in index.slang
            or norm_q in index.postings
            or norm_q in index.raw_terms
            or lookup_skus(catalog, norm_q)
        ):
            return "unknown_number"
    return None


def parse_upgrade_query(text: str) -> tuple[str, bool]:
    """Разбирает запросы вида «апгрейд windows 10 до 11», чтобы «до 11» не стало ценой."""
    for rx in (UPGRADE_TO, UPGRADE_MID):
        m = rx.match(text)
        if m:
            product, _v_from, v_to, tail = m.groups()
            cleaned = _clean_spaces(f"{product} {v_to} {tail}")
            if cleaned:
                return cleaned, True
    return text, False


def extract_budget(text: str) -> tuple[str, float | None, bool]:
    """Извлекает ценовой потолок с защитой от «апгрейд X 10 до 11» и поддержкой «дешевле N»."""
    upgraded, is_upgrade = parse_upgrade_query(text)
    if is_upgrade:
        return upgraded, None, False
    match = PRICE_LIMIT.search(text)
    if match:
        scale = match[2]
        amount = float(match[1].replace(" ", "").replace(",", "."))
        budget = amount * (1_000_000 if scale == "млн" else 1000 if scale else 1)
        return text[:match.start()].strip(" ,"), budget, False
    cheaper = CHEAPER_LIMIT.search(text)
    if cheaper:
        scale = cheaper[2]
        amount = float(cheaper[1].replace(" ", "").replace(",", "."))
        budget = amount * (1_000_000 if scale == "млн" else 1000 if scale else 1)
        cleaned = _clean_spaces(text[:cheaper.start()] + " " + text[cheaper.end():])
        if cleaned:
            return cleaned, budget, True
    return text, None, False


def clean_analog_subject(subject: str) -> str:
    """Убирает модификаторы («дешевле», «бесплатный», «российский») из предмета запроса аналогов."""
    cleaned = _clean_spaces(ANALOG_MODIFIERS.sub(" ", subject))
    return cleaned or subject


def resolve_vendor(index, engine, text: str) -> tuple[str, str] | None:
    """Находит реального вендора фида по имени, транслиту, алиасу или КБ."""
    norm = _clean_spaces(normalize(text))
    if not norm:
        return None
    candidates = [norm, " ".join(words(norm))]
    if re.search("[а-я]", norm):
        candidates.append(roman(norm))
    if re.fullmatch("[a-z0-9 ]+", norm):
        candidates.append(" ".join(words(cyrillic(norm))))
    vid = None
    for key in candidates:
        if key and key in index.vendor_names:
            vid = index.vendor_names[key]
            break
    if not vid:
        for key in candidates:
            kw = words(key) if key else ()
            if not kw:
                continue
            pref_vids = {
                v
                for name, v in index.vendor_names.items()
                if words(name)[:len(kw)] == kw
            }
            if len(pref_vids) == 1:
                vid = next(iter(pref_vids))
                break
    if not vid and norm in index.slang:
        field, members = index.slang[norm]
        if field == "vendors" and members:
            vid = index.card_vendors.get(members[0])
    if not vid:
        toks = tokens(norm)
        if toks:
            for start, end, matches in engine.lex.match(toks):
                if start != 0 or end != len(toks):
                    continue
                for kind, key, _ in matches:
                    if kind == "vendor":
                        members = index.tags["vendors"].get(key.casefold())
                        if members:
                            vid = index.card_vendors.get(next(iter(members)))
                            break
                        row = engine.kb.rows["vendors"].get(key, {})
                        for alias in (row.get("name"), row.get("name_ru"), *(row.get("aliases") or ())):
                            if not alias:
                                continue
                            k = " ".join(words(str(alias)))
                            if k in index.vendor_names:
                                vid = index.vendor_names[k]
                                break
                    if vid:
                        break
                if vid:
                    break
    if not vid:
        hits = index.products(norm, fuzzy=False)[:10]
        if hits:
            vids = [index.card_vendors.get(cid) for cid in hits if index.card_vendors.get(cid)]
            if vids:
                top_vid = max(set(vids), key=vids.count)
                v_label = normalize(index.cat.cards[hits[0]].offers[0].vendor or "")
                if vids.count(top_vid) >= max(1, len(vids) // 2) and any(
                    k and k in v_label for k in candidates
                ):
                    vid = top_vid
    if not vid:
        return None
    cards = index.language.vendor_cards.get(vid) or list(index.tags["vendors"].get(vid, ()))
    if not cards:
        return None
    display = index.cat.cards[cards[0]].offers[0].vendor or norm
    return vid, display


def detect_vendor_catalog(index, engine, text: str) -> tuple[str, str] | None:
    """Распознаёт запросы вида «всё от adobe», «продукты Аскон», «что есть у X», «каталог X»."""
    norm = _clean_spaces(normalize(text))
    for rx in VENDOR_CATALOG_PATTERNS:
        m = rx.match(norm)
        if not m:
            continue
        tail = _clean_spaces(m[1])
        if not tail or tail.startswith(("для ", "от ", "по ", "на ", "в ")):
            continue
        found = resolve_vendor(index, engine, tail)
        if found:
            return found
    return None


def normalize_spoken_brands(text: str) -> str:
    out = text
    for rx, repl in SPOKEN_BRAND_TOKENS:
        out = rx.sub(repl, out)
    return _clean_spaces(out)


def extract_conditions_and_noise(engine, index, text: str, existing_qty=None) -> CleanQuery:
    """Извлекает условия (срок, тип лицензии, поставка, аудитория, ядра) и снимает покупательский шум."""
    s = _clean_spaces(text)
    filters: dict = {}
    chips: list = []
    qty = existing_qty
    changed = False

    # Если исходная строка уже точно совпадает с классом, редакцией, прямым запросом лицензии или вендором — не ломаем её.
    if (
        not s
        or index.class_match(s)
        or index.edition(s)
        or license_request(engine, s)
        or resolve_vendor(index, engine, s)
    ):
        return CleanQuery(s, filters, qty, chips, False)

    def strip_rx(rx, current):
        candidate = _clean_spaces(rx.sub(" ", current))
        return candidate if candidate and re.search(r"[а-яёa-z0-9]", candidate) else current

    # 1. Ведущие/хвостовые глаголы действия и обёртки («скачать», «купить», «цена», «ключ активации», «license»).
    for _ in range(2):
        nxt = strip_rx(LEAD_ACTION, s)
        if nxt != s:
            s, changed = nxt, True
        else:
            break
    for _ in range(2):
        nxt = strip_rx(TRAIL_ACTION, s)
        if nxt != s:
            s, changed = nxt, True
        else:
            break

    # 2. Обновление / апгрейд (без «до N», которое обработал parse_upgrade_query).
    if UPGRADE_ACTION.search(s):
        nxt = strip_rx(UPGRADE_ACTION, s)
        if nxt != s:
            s, changed = nxt, True
            filters["action"] = "upgrade"
            chips.append(dict(key="action", label="Обновление", removable=True))

    # 3. Бессрочная / без подписки / навсегда (до «подписка»!).
    if PERPETUAL.search(s):
        nxt = strip_rx(PERPETUAL, s)
        if nxt != s:
            s, changed = nxt, True
            filters["model"] = "perpetual"
            chips.append(dict(key="model", label="Бессрочная лицензия", removable=True))

    # 4. Срок действия («1 год», «3 года», «на год», «годовая подписка»).
    m = TERM_NUM.search(s)
    if m and int(m[1]) > 0:
        nxt = _clean_spaces(s[:m.start()] + " " + s[m.end():])
        if nxt and re.search(r"[а-яёa-z0-9]", nxt):
            months = int(m[1]) * (1 if m[2].startswith("мес") else 12)
            filters["term_months"] = months
            label = f"{m[1]} мес." if m[2].startswith("мес") else f"{m[1]} г."
            chips.append(dict(key="term_months", label=f"Срок · {label}", removable=True))
            s, changed = nxt, True
    elif TERM_ONE_YEAR.search(s):
        had_sub = "подписк" in TERM_ONE_YEAR.search(s)[0]
        nxt = strip_rx(TERM_ONE_YEAR, s)
        if nxt != s:
            filters["term_months"] = 12
            chips.append(dict(key="term_months", label="Срок · 1 год", removable=True))
            if had_sub and "model" not in filters:
                filters["model"] = "subscription"
                chips.append(dict(key="model", label="Подписка", removable=True))
            s, changed = nxt, True
    elif TERM_ONE_MONTH.search(s):
        nxt = strip_rx(TERM_ONE_MONTH, s)
        if nxt != s:
            filters["term_months"] = 1
            chips.append(dict(key="term_months", label="Срок · 1 мес.", removable=True))
            s, changed = nxt, True

    # 5. Подписка (не ломаем составные дескрипторы вроде «семейная подписка»).
    if SUBSCRIPTION.search(s) and "model" not in filters and not re.search(r"\bсемейн\w*\s+подписк", s):
        nxt = strip_rx(SUBSCRIPTION, s)
        if nxt != s:
            filters["model"] = "subscription"
            chips.append(dict(key="model", label="Подписка", removable=True))
            s, changed = nxt, True

    # 6. Способ поставки и тип лицензии (электронная лицензия, коробочная версия, OEM).
    if DELIVERY_ESD.search(s):
        nxt = strip_rx(DELIVERY_ESD, s)
        if nxt != s:
            filters["delivery"] = "esd"
            chips.append(dict(key="delivery", label="Электронная лицензия", removable=True))
            s, changed = nxt, True
    if DELIVERY_BOX.search(s):
        nxt = strip_rx(DELIVERY_BOX, s)
        if nxt != s:
            filters["delivery"] = "box"
            chips.append(dict(key="delivery", label="Коробочная версия", removable=True))
            s, changed = nxt, True
    if LICENSE_OEM.search(s):
        nxt = strip_rx(LICENSE_OEM, s)
        if nxt != s:
            filters["license_type"] = "oem"
            chips.append(dict(key="license_type", label="OEM", removable=True))
            s, changed = nxt, True

    # 7. Аудитория / канал (академическая, для юрлиц, для команд, для физлиц).
    if AUDIENCE_EDU.search(s):
        nxt = strip_rx(AUDIENCE_EDU, s)
        if nxt != s:
            filters["audience"] = "edu"
            chips.append(dict(key="audience", label="Для образования", removable=True))
            s, changed = nxt, True
    elif AUDIENCE_BIZ.search(s):
        nxt = strip_rx(AUDIENCE_BIZ, s)
        if nxt != s:
            filters["audience"] = "business"
            chips.append(dict(key="audience", label="Для бизнеса", removable=True))
            s, changed = nxt, True
    elif AUDIENCE_HOME.search(s):
        nxt = strip_rx(AUDIENCE_HOME, s)
        if nxt != s:
            filters["audience"] = "home"
            chips.append(dict(key="audience", label="Для дома", removable=True))
            s, changed = nxt, True

    # 8. Разрядность (x64, x86, 64-bit) и количество ядер (16 core).
    if ARCH_TECH.search(s):
        nxt = strip_rx(ARCH_TECH, s)
        if nxt != s:
            s, changed = nxt, True
    core_m = CORE_QTY.search(s)
    if core_m and int(core_m[1]) > 0:
        nxt = _clean_spaces(s[:core_m.start()] + " " + s[core_m.end():])
        if nxt and re.search(r"[а-яёa-z0-9]", nxt):
            if qty is None:
                qty = dict(value=int(core_m[1]), metric="core")
            s, changed = nxt, True

    # 9. Слово-обёртка «версия» (standalone «лицензия» снимает purchase_subject после edition).
    ver_only = re.compile(r"\bверси(?:я|ю|и|ей)\b")
    if ver_only.search(s):
        nxt = strip_rx(ver_only, s)
        if nxt != s and not nxt.startswith(("на ", "для ", "от ")):
            s, changed = nxt, True

    # 10. Повторное снятие ведущих действий, если они остались после удаления «лицензия на».
    nxt = strip_rx(LEAD_ACTION, s)
    if nxt != s:
        s, changed = nxt, True

    # 11. Разговорные написания брендов («виндоус», «мс sql», «ms windows», «office365», «автокад лт»).
    spoken = normalize_spoken_brands(s)
    if spoken != s:
        s, changed = spoken, True

    return CleanQuery(s, filters, qty, chips, changed)
