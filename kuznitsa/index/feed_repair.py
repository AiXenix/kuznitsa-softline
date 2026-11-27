"""Восстановление написания с подтверждением всех частей запроса по снимку."""
from collections import defaultdict
from functools import lru_cache
import re

from kuznitsa.text import lemma, morphology, normalize, tokens
from kuznitsa.understand.repair import LAYOUT, repair, typo_matcher
from kuznitsa.understand.spell_index import roman
from rapidfuzz.fuzz import ratio


def compact(text):
    return "".join(re.findall(r"[а-яa-z0-9]+", normalize(text)))


def roman_keys(text):
    for ending in ("й", "y"):
        yield roman(text.replace("й", ending))


# Обозначения редакций, которые встречаются в русских и английских названиях.
EDITIONS = {"специальный": "special", "стандартный": "standard", "профессиональный": "professional",
            "pro": "professional", "профессиональная": "professional"}
QUALIFIERS = frozenset("pro professional plus premium standard business home mac macos windows server suite studio edition neo".split())

# Профессиональные аббревиатуры и классы задач, которые нельзя портить опечатками и фонетикой.
PROTECTED_ACRONYMS = frozenset({
    "кии", "скзи", "сзи", "dlp", "siem", "субд", "эдо", "вкс", "2fa", "mfa",
    "ngfw", "waf", "mdm", "vdi", "bi", "ocr", "crm", "erp", "edr", "xdr",
    "soar", "iam", "pam", "soc", "ids", "ips", "vpn", "pki", "cad", "bim",
    "plm", "cam", "cae", "cms", "dms", "ecm", "сэд", "асу", "сапр", "иб",
    "ит", "по", "ос", "пк", "ибп", "мфу", "ssd", "hdd", "ram", "cpu", "gpu",
    "nas", "san", "ups",
})

# Известные внешние/игровые/массовые бренды вне каталога, которые нельзя превращать в созвучные слова.
ABSENT_BRANDS = frozenset({
    "steam", "zoom", "figma", "jira", "notion", "tableau", "veeam", "jetbrains",
    "slack", "trello", "miro", "github", "gitlab", "docker", "kubernetes",
    "oracle", "sap", "cisco", "eset", "nod32", "discord", "telegram", "whatsapp",
    "spotify", "netflix", "youtube", "minecraft", "roblox", "fortnite", "iphone",
    "android", "ubuntu", "debian", "centos", "anydesk", "teamviewer",
})

EMOJI_OR_JUNK = re.compile(r"[^\w\s+\-.,/:;?!&\"'«»()₽$€%#№@*\n]+")
_DUP_WORDS = re.compile(r"\b([^\W\d_][\w-]*)(?:\s+\1)+\b", re.I)


def identity_terms(text):
    """Для имени с версией, платформой или редакцией выделяем марку из исходного запроса."""
    from .feed import STOP
    raw = [w for w in re.findall(r"[\w]+", normalize(text)) if w not in STOP]
    morph = morphology()
    parts = []
    for w in raw:
        # Неизвестное кириллическое слово в ошибочной раскладке («цштвщцы») не лемматизируем,
        # иначе «цштвщцы» → «цштвщца» → «windowf» ломает перевод раскладки.
        if re.fullmatch(r"[а-я]{3,}", w) and not morph.word_is_known(w):
            trans = w.translate(LAYOUT)
            if re.fullmatch(r"[a-z]{3,}", trans):
                parts.append(w)
                continue
        parts.append(lemma(w))
    parts = tuple(parts)
    qualifiers = {w for w in parts if w in QUALIFIERS or (re.fullmatch(r"v?\d+", w) and w != "365")}
    if not qualifiers:
        return ()
    terms = [w for w in parts if w not in qualifiers and w not in {"for", "and", "on", "под", "audio", "software"}]
    # У кириллического имени проверяем короткую именную часть перед английской
    # редакцией. Длинные русские описания остаются в разборе классов и задач.
    if any(re.search("[а-я]", w) for w in terms):
        if len(terms) > 2 or parts[-1] not in qualifiers:
            return ()
        if set(terms) & {"нужный", "хотеть", "как", "какой", "чем", "что", "программа", "лицензия", "софт"}:
            return ()
    return tuple(terms)


class FeedRecovery:
    def __init__(self, index, kb):
        self.index = index
        self._known_class = frozenset().union(*index.class_terms.values()) if index.class_terms else frozenset()
        self.spell = typo_matcher(w for w in index.vocab if len(w) >= 4)
        self.absent_words = set(ABSENT_BRANDS)
        for row in kb.rows.get("feed_analogs", {}).values():
            if not row.get("in_catalog"):
                for name in row.get("names", ()):
                    parts = tokens(normalize(name))
                    if len(parts) == 1 and len(parts[0]) >= 3:
                        self.absent_words.add(parts[0])
        self.names = defaultdict(set)
        self.titles = defaultdict(list)
        for card in index.cat.cards.values():
            for form in set(roman_keys(compact(card.title))):
                self.titles[form].append(card.id)
            for name in (card.title, card.offers[0].vendor or ""):
                parts = tokens(name.removeprefix("Программа "))[:8]
                for end in range(1, len(parts) + 1):
                    phrase = " ".join(parts[:end])
                    key = compact(phrase)
                    if len(key) < 3:
                        continue
                    for form in set(roman_keys(key)):
                        self.names[form].add(phrase)
        self.aliases = {}
        for phrase, (field, ids) in index.slang.items():
            if field in {"families", "vendors"}:
                for form in roman_keys(compact(phrase)):
                    self.aliases.setdefault(form, phrase)
        # У класса может быть разговорное название, а у линейки — только описание назначения.
        self.capabilities = defaultdict(set)
        self.descriptions = []
        self.russian_terms = {}
        for fid, row in kb.rows["families"].items():
            ids = index.tags["families"].get(fid)
            if not ids:
                continue
            for phrase in [row.get("summary", ""), *row.get("use_cases", [])]:
                description = len(self.descriptions)
                terms = set()
                for w in tokens(phrase or ""):
                    if len(w) < 3 or not re.fullmatch("[а-я]+", w):
                        continue
                    word = self.feature(w)
                    terms.add(word)
                    self.capabilities[word].add(description)
                    for form in roman_keys(w):
                        self.russian_terms[form] = w
                self.descriptions.append((len(terms), ids))
        self.confirmed = lru_cache(512)(self.confirmed)
        self.full_name = lru_cache(512)(self.full_name)
        self.identity_cards = lru_cache(512)(self.identity_cards)

    def is_hard_protected(self, word):
        """Аббревиатуры и отсутствующие бренды: нельзя подменять ни опечаткой, ни фонетикой."""
        w = word.lower()
        return w in PROTECTED_ACRONYMS or w in self.absent_words

    def is_protected(self, word):
        """Слово нельзя искажать опечаткой: аббревиатура, чужой бренд или обычное русское слово."""
        w = word.lower()
        if self.is_hard_protected(w):
            return True
        index = self.index
        if re.fullmatch(r"[а-я]+", w):
            lw = lemma(w)
            in_catalog = (
                w in index.postings or lw in index.postings
                or w in index.aliases or lw in index.aliases
                or w in index.slang or lw in index.slang
                or w in index.vendor_names or lw in index.vendor_names
            )
            if not in_catalog and morphology().word_is_known(w):
                return True
        return False

    def clean_query(self, norm):
        """Убирает эмодзи/шум, склеивает повторы слов и чинит удвоенную последнюю согласную («антивирусс»)."""
        cleaned = EMOJI_OR_JUNK.sub(" ", norm)
        cleaned = " ".join(cleaned.split())
        if not cleaned:
            return norm
        # Схлопываем подряд идущие одинаковые слова («антивирус антивирус антивирус» → «антивирус»).
        cleaned = _DUP_WORDS.sub(r"\1", cleaned)
        # Если неизвестное кириллическое слово кончается удвоенной буквой («антивирусс»), а без неё — известное слово каталога/класса.
        index = self.index
        morph = morphology()
        words_out = []
        changed = False
        known_class = self._known_class
        for tok in cleaned.split():
            if (len(tok) >= 5 and re.fullmatch(r"[а-я]+", tok)
                    and tok[-1] == tok[-2]
                    and tok not in index.postings and lemma(tok) not in index.postings
                    and tok not in index.aliases and tok not in index.slang
                    and not morph.word_is_known(tok)):
                short = tok[:-1]
                lshort = lemma(short)
                if (short in index.postings or lshort in index.postings
                        or short in known_class or lshort in known_class
                        or short in index.aliases or short in index.slang):
                    words_out.append(short)
                    changed = True
                    continue
            words_out.append(tok)
        return " ".join(words_out) if changed else cleaned

    def identity_cards(self, terms):
        """Артикул и слова редакции не подтверждают название чужой линейки."""
        index = self.index
        result = set()
        for word in terms:
            mapped = word.translate(LAYOUT)
            variants = {word, mapped, lemma(mapped), *index.sounds.lookup(word)}
            if mapped != word:
                variants.update(index.sounds.lookup(mapped))
            if len(word) >= 5 and word not in index.postings and not self.is_protected(word):
                variants.update(w for w, _, _ in self.spell(word, 6, 2) if ratio(word, w) >= 84)
            for form in variants:
                result.update(index.postings.get(form, ()))
                if form in index.aliases:
                    result.update(index.products(index.aliases[form], fuzzy=False))
                result.update(index.slang.get(form, (None, ()))[1])
            result.update(index.language.acronyms.get(word, ()))
            vendor = index.vendor_names.get(word) or index.vendor_names.get(mapped)
            if vendor:
                result.update(index.language.vendor_cards[vendor])
        return result

    @staticmethod
    def feature(word):
        root = lemma(word)
        if root in {"сетевой", "сеть"}:
            return "сеть"
        if root in {"сканер", "сканирование", "сканировать"}:
            return "сканер"
        return root

    def full_name(self, raw):
        for text, kind in [(raw, "translit"), (raw.translate(LAYOUT), "layout")]:
            for key in roman_keys(compact(text)):
                ids = self.titles.get(key)
                if ids:
                    order = sorted(ids, key=lambda i: (normalize(self.index.cat.cards[i].title) == normalize(text),
                                                       self.index.quality[i], i), reverse=True)
                    return order, self.index.cat.cards[order[0]].title, kind
        return (), raw, None

    def _safe_spell(self, term):
        """Безопасная правка опечаток: не ломает защищённые слова и короткие бренды («steam» ↛ «team»)."""
        if self.is_protected(term):
            return ()
        index = self.index
        if len(term) <= 5:
            candidates = []
            for w, _, _ in self.spell(term, 6, 1):
                if len(w) < 4:
                    continue
                # На коротких словах требуем совпадения первой буквы (или перестановки первых двух)
                # и достаточную частотность в каталоге.
                same_head = (term[0] == w[0]) or (len(term) >= 2 and len(w) >= 2 and term[:2] == w[:2][::-1])
                if same_head and len(index.postings.get(w, ())) >= 5:
                    candidates.append(w)
            return tuple(candidates)
        distance = 1 if len(term) < 8 else 2
        return tuple(w for w, _, _ in self.spell(term, 6, distance))

    def confirmed(self, phrase):
        index = self.index
        raw_terms = tokens(normalize(phrase))
        from .feed import STOP
        terms = [lemma(w) for w in raw_terms if w not in STOP]
        raw_filtered = [w for w in raw_terms if w not in STOP]
        if not terms:
            return (), phrase
        pools = []
        for raw_w, term in zip(raw_filtered, terms):
            variants = {term}
            if term in EDITIONS:
                variants.add(EDITIONS[term])
            if not any(v in index.postings for v in variants) and len(term) >= 4 and term.isalpha():
                if not self.is_protected(raw_w) and not self.is_protected(term):
                    variants.update(self._safe_spell(term))
            pool = set().union(*(index.postings.get(v, ()) for v in variants))
            if not pool:
                return (), phrase
            pools.append((variants, pool))
        hits = set.intersection(*(p for _, p in pools))
        if not hits:
            return (), phrase

        def rank(cid):
            title = tokens(index.cat.cards[cid].title)
            title_terms = {lemma(w) for w in title}
            return (sum(bool(opts & title_terms) for opts, _ in pools),
                    sum(w in title_terms for w in terms), index.line_popularity.get(cid, ()),
                    -len(title), index.quality[cid], cid)

        ordered = tuple(sorted(hits, key=rank, reverse=True))
        available = index.terms[ordered[0]]
        spelling = " ".join(term if term in available else min(variants & available)
                            for term, (variants, _) in zip(terms, pools))
        return ordered, spelling

    def lookup(self, engine, base):
        index = self.index
        if len(base) > 150 or len(base.split()) > 10:
            return (), base, None
        # Известное полное имя снятой линейки нельзя заменять соседним по опечатке.
        if base in index.unsold_sections or base in index.replacements:
            return (), base, None
        base_tokens = tokens(base)
        if len(base_tokens) == 1 and self.is_protected(base_tokens[0]):
            return (), base, None
        forms = [(base, "typo"), (base.translate(LAYOUT), "layout")]
        if any(ch.isalpha() for ch in base):
            fixed, changes = repair(base, engine.lex)
            if changes:
                # Отбрасываем разрушительную починку защищённых слов.
                if not any(self.is_protected(c.get("from", "")) for c in changes):
                    kinds = {c["kind"] for c in changes}
                    forms.append((" ".join(fixed), changes[0]["kind"] if len(kinds) == 1 else "catalog"))
        for phrase, kind in forms:
            key = compact(phrase)
            if len(key) < 3:
                continue
            for form in roman_keys(key):
                alias = self.aliases.get(form)
                if alias:
                    canonical = index.aliases.get(alias, alias)
                    return index.slang[alias][1], canonical, "translit" if kind == "typo" else kind
                for name in sorted(self.names.get(form, ()), key=lambda s: (s != phrase, len(s), s)):
                    hits = index.products(name)
                    if hits:
                        return hits, name, "translit" if kind == "typo" and name != phrase else kind
            mapped, _ = engine._phrases.apply(phrase)
            mapped = index.correct(mapped)
            if mapped != base:
                if mapped in index.slang and index.slang[mapped][0] in {"families", "vendors"}:
                    return index.slang[mapped][1], mapped, kind
                direct = index.products(mapped, fuzzy=False)
                if direct:
                    return direct, mapped, kind
            hits, spelling = self.confirmed(mapped)
            if hits:
                return hits, spelling, kind
            if kind == "layout":
                sounds, corrected = index.sound_products(mapped)
                if sounds:
                    return sounds, corrected, "layout"
        for phrase, kind in forms:
            decoded = [self.russian_terms.get(w) or engine.lex.roman.get(w, w) for w in tokens(phrase)]
            terms = {self.feature(w) for w in decoded}
            if len(terms) < 2 or not all(w in self.capabilities for w in terms):
                continue
            descriptions = set.intersection(*(self.capabilities[w] for w in terms))
            supported = {}
            for i in descriptions:
                length, ids = self.descriptions[i]
                for cid in ids:
                    supported[cid] = min(length, supported.get(cid, length))
            if supported:
                ids = sorted(supported, key=lambda cid: (-supported[cid], index.quality[cid], cid), reverse=True)
                return tuple(ids), " ".join(decoded), "translit" if decoded != tokens(phrase) else kind
        return (), base, None
