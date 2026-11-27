"""Названия классов, издателей и редакций, подтверждённые снимком магазина."""
from collections import Counter, defaultdict
from functools import lru_cache
import re

from kuznitsa.text import lemma, morphology, normalize
from kuznitsa.understand.spell_index import cyrillic, roman
from kuznitsa.understand.quantities import NUMBERS
from .feed import STOP, words, class_words
from .feed_repair import PROTECTED_ACRONYMS, QUALIFIERS


ORDINALS = dict(zip("первый второй третий четвертый пятый шестой седьмой восьмой девятый десятый".split(), range(1, 11)))
VERSION_WORD = r"(?:верси[яию]|версией|version)"
VERSION_NUMBER = r"(?:\d+(?:\.\d+)*|[а-я]+)"
DESCRIPTORS = ("ос", "скзи", "криптопровайдер", "антивирус", "сканер уязвимостей", "дистрибутив", "вебинар", "видеоконференция",
               "подписка", "семейная подписка", "лицензия", "офисный пакет", "защита рабочих станций")
EDITION_WORDS = {"home and business": "для дома и бизнеса", " se": " special edition", " epp": " endpoint protection platform"}
LETTER_NAMES = dict(zip("эй би си ди и эф джи эйч ай джей кей эл эм эн оу пи кью ар эс ти ю ви икс уай зед".split(),
                        "abcdefghijklmnopqrstuvxyz"))
SPELLED = re.compile(r"\b(?:" + "|".join(LETTER_NAMES) + r")(?:[ -]+(?:" + "|".join(LETTER_NAMES) + r")){1,5}\b")

VENDOR_QUESTION_PATTERNS = (
    re.compile(r"^(?:что есть у|что прода[её]т(?:е|ся)? у|продукты|товары|решения|линейка|каталог|программы|софт)\s+(.+)$"),
    re.compile(r"^(?:вс[её]\s+от)\s+(.+)$"),
    re.compile(r"^(.+?)\s+(?:продукты|товары|линейка|каталог)$"),
)
SPEC_ONLY = re.compile(r"^[\d.,]+\s*(?:gb|tb|mb|kb|гб|тб|мб|кб|mhz|ghz|w|va|вт|ва|\"|дюйм\w*)?$", re.I)


def spoken_initials(index, text):
    def expand(match):
        short = "".join(LETTER_NAMES[w] for w in re.split("[ -]+", match[0]))
        return short if short in index.language.acronyms or short in index.postings else match[0]
    return SPELLED.sub(expand, text)


CORPORATE = {"inc", "ltd", "limited", "corporation", "corp", "llc", "gmbh", "software", "systems", "ооо", "ао", "зао"}


def publisher_keys(name):
    parts = [w for w in words(name) if w not in CORPORATE]
    if parts:
        short = " ".join(parts)
        yield short
        if re.search("[а-я]", short):
            yield roman(short)
        if re.fullmatch("[a-z ]+", short):
            yield " ".join(words(cyrillic(short)))


@lru_cache(2048)
def plural_with_object(head, tail):
    if not (re.fullmatch("[а-я]+", head) and re.fullmatch("[а-я]+", tail)):
        return False
    return (any("plur" in p.tag and p.tag.POS == "NOUN" for p in morphology().parse(head))
            and any("gent" in p.tag and p.tag.POS == "NOUN" for p in morphology().parse(tail)))


def sold_as(card, query):
    """Разрешаем издателя и родовое обозначение перед собственным именем."""
    title_norm = normalize(card.title)
    raw = re.findall(r"\w+", title_norm)
    title = tuple(lemma(w) for w in raw)
    name = words(query)
    vendor = set(words(card.offers[0].vendor or ""))
    if not name:
        return False
    if tuple(words(card.offers[0].vendor or "")) == name:
        return True
    # Сторонние утилиты вида «EMS SQL Backup for SQL Server» не являются продажей самого продукта.
    m = re.search(r"\b(?:for|для)\s+(.+)$", title_norm)
    if m:
        tail_words = words(m.group(1))
        lead_words = words(title_norm[:m.start()])
        if set(name) <= set(tail_words) and lead_words and not (set(lead_words[:2]) & set(name)) and not (set(name) & vendor):
            return False
    if words(card.title)[:len(name)] == name:
        return True
    prefixes = vendor | {"программа", "программный", "обеспечение", "операционный", "система",
                         "платформа", "пакет", "архиватор", "облачный", "субд", "пак", "комплекс", "сервис"}
    for pos, word in enumerate(title):
        if title[pos:pos + len(name)] == name:
            return True
        if word not in prefixes:
            break
    return False


def version_forms(text):
    def number(match):
        raw = match["number"]
        if raw[0].isdigit():
            return raw
        value = ORDINALS.get(lemma(raw), NUMBERS.get(lemma(raw)))
        return str(value) if value is not None else match[0]
    if " " not in text:
        return text
    text = re.sub(rf"\b{VERSION_WORD}\s+(?P<number>{VERSION_NUMBER})\b", number, text)
    text = re.sub(rf"\b(?P<number>{VERSION_NUMBER})\s+{VERSION_WORD}\b", number, text)
    text = re.sub(r"\bv\.?\s*(?=\d)", "", text)
    text = re.sub(r"\b(?:выпуск(?:а)?|релиз(?:а)?)\s+((?:19|20)\d\d)\b", r"\1", text)
    text = re.sub(r"\b((?:19|20)\d\d)\s+(?:года?\b|г\.)", r"\1", text)
    return text


def edition_form(index, text):
    literal = text
    text = re.sub(r"\bhome\s*&\s*business\b", "home and business", text)
    text = re.sub(r"^ms (?=\w)", "microsoft ", text)
    for source, dest in EDITION_WORDS.items():
        text = re.sub(re.escape(source) + r"\b", dest, text)
    if literal != text and index.products(literal, fuzzy=False):
        return literal
    return text


class FeedLanguage:
    def __init__(self, index, kb):
        self.descriptors = {words(x) for x in DESCRIPTORS}
        self.descriptors.update(words(label) for label in index.classes.values())
        # Одно и то же имя может обозначать несколько разделов. Не фиксируем
        # за таким именем случайный раздел из порядка обхода YAML.
        targets = defaultdict(set)
        for ident, row in kb.rows["categories"].items():
            labels = [row.get("title", ""), row.get("title_short", "")]
            labels.extend(re.split(r"\s+и\s+|\s*\(", row.get("title_short", ""))[:1])
            self.descriptors.update(words(str(s)) for s in [*row.get("synonyms", []), *row.get("slang", [])] if s)
            sections = Counter(index.card_sections[cid] for cid in index.tags["classes"].get(ident, ()))
            target = max(sections, key=lambda k: (sections[k], k)) if sections else None
            for label in filter(None, labels):
                self.descriptors.add(words(label))
                if target:
                    signature = class_words(label)
                    if signature:
                        targets[signature].add(target)
        self.category_alias = {k: next(iter(v)) for k, v in targets.items() if len(v) == 1}
        topics = defaultdict(set)
        for phrase, section in index.section_phrases.items():
            if len(phrase) != 2:
                continue
            subject = phrase - {"editor", "art", "graphics", "design", "редактор", "графика"}
            if len(subject) == 1:
                word = next(iter(subject))
                if re.fullmatch(r"[a-z]{4,}|\d+d", word):
                    topics[word].add(section)
        self.name_topics = {word: next(iter(keys)) for word, keys in topics.items() if len(keys) == 1}
        by_short = defaultdict(set)
        self.vendor_cards = defaultdict(list)
        for cid, vid in index.card_vendors.items():
            if vid:
                self.vendor_cards[vid].append(cid)
        for name, vid in index.vendor_names.items():
            for short in publisher_keys(name):
                by_short[short].add(vid)
        for short, vids in by_short.items():
            if len(vids) == 1:
                index.vendor_names.setdefault(short, next(iter(vids)))
        # Русское и международное имя связываются через реально найденного издателя.
        for row in kb.rows["vendors"].values():
            names = [name for name in (row.get("name"), row.get("name_ru"), *row.get("aliases", [])) if name]
            keys = {key for name in names for key in publisher_keys(name)}
            owners = {index.vendor_names[k] for k in keys if k in index.vendor_names}
            if len(owners) == 1:
                for key in keys:
                    index.vendor_names.setdefault(key, next(iter(owners)))

        self.acronyms = defaultdict(set)
        known = {
            term for term, row in kb.rows["slang"].items()
            if row.get("type") == "abbr"
            and row.get("maps_to", {}).get("attr") != "hardware_class"
            and normalize(term) not in index.hardware
            and normalize(term) not in PROTECTED_ACRONYMS
        }
        for fid, row in kb.rows["families"].items():
            members = index.tags["families"].get(fid)
            if not members:
                continue
            names = row["name"].split()
            latin = [w for w in names if re.fullmatch("[A-Z][a-z]+", w)]
            initials = "".join(w[0] for w in latin)
            abbreviations = [a for a in row.get("aliases", []) if a in known or a.lower() == initials.lower()]
            abbreviations.extend(w for w in names if w.isupper())
            abbreviations.append(initials)
            for alias in abbreviations:
                if re.fullmatch("[A-Za-z]{3,5}", alias):
                    self.acronyms[alias.lower()].update(members)
        for cid, card in index.cat.cards.items():
            if card.offers[0].domain != "software":
                continue
            parts = card.title.split()
            if 3 <= len(parts) <= 5 and all(re.fullmatch("[A-Z][a-z]+", w) for w in parts):
                short = "".join(w[0].lower() for w in parts)
                if short not in index.hardware and short not in PROTECTED_ACRONYMS and (short in known or (short not in index.postings and parts[0].lower() in words(card.offers[0].vendor or ""))):
                    self.acronyms[short].add(cid)
            for start in range(len(parts) - 2):
                name = parts[start:start + 3]
                if all(re.fullmatch("[A-Z][a-z]+", w) for w in name):
                    short = "".join(w[0].lower() for w in name)
                    if short in known:
                        self.acronyms[short].add(cid)
        # Некоторые словарные статьи отмечены как вендор и дают точную
        # расшифровку сокращения в примечании «Название продукта (ABC)».
        self.absent_acronyms = {}
        for row in kb.rows["slang"].values():
            vid = row["maps_to"].get("vendor")
            if not vid:
                continue
            definition = re.fullmatch(r"([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){2,4}) \(([A-Z]{3,5})\)", row.get("note") or "")
            if not definition:
                continue
            title, short = definition.groups()
            if "".join(w[0] for w in title.split()) != short:
                continue
            members = index.tags["vendors"].get(vid, ())
            owners = {index.card_vendors[cid] for cid in members}
            if len(owners) != 1:
                continue
            sold = [cid for cid in index.products(title, fuzzy=False)
                    if cid in members and sold_as(index.cat.cards[cid], title)]
            if sold:
                self.acronyms[short.lower()].update(sold)
            elif short.lower() not in self.acronyms:
                self.absent_acronyms[short.lower()] = (title, owners.pop())

    def vendor_question(self, index, text):
        """Распознаёт вопросы об ассортименте вендора: «что есть у Positive Technologies», «продукты Аскон», «всё от adobe»."""
        norm = normalize(text).strip(" ?!.")
        for pattern in VENDOR_QUESTION_PATTERNS:
            m = pattern.fullmatch(norm)
            if not m:
                continue
            candidate = m.group(1).strip(" ?!.")
            if not candidate:
                continue
            vid = (
                index.vendor_names.get(candidate)
                or index.vendor_names.get(" ".join(words(candidate)))
            )
            if not vid and candidate in index.aliases:
                aliased = normalize(index.aliases[candidate])
                vid = index.vendor_names.get(aliased) or index.vendor_names.get(" ".join(words(aliased)))
            if not vid and candidate in index.slang and index.slang[candidate][0] == "vendors":
                members = index.slang[candidate][1]
                if members:
                    return index.card_vendors.get(members[0]), tuple(members)
            if not vid and candidate in index.tags["vendors"]:
                members = index.tags["vendors"][candidate]
                if members:
                    ordered = tuple(sorted(members, key=index.quality.get, reverse=True))
                    return index.card_vendors.get(ordered[0]), ordered
            if vid and self.vendor_cards.get(vid):
                ordered = tuple(sorted(self.vendor_cards[vid], key=index.quality.get, reverse=True))
                return vid, ordered
        return None, ()

    def class_prefixes(self, index, text):
        parts = text.split()
        for end in range(min(7, len(parts) - 1), 0, -1):
            label = " ".join(parts[:end])
            rest = " ".join(parts[end:])
            if parts[end - 1] in STOP:
                continue
            # Не отрезаем класс оборудования (ssd/hdd/ram/ноутбук) и не оставляем голую характеристику («1tb»).
            if label in index.hardware or SPEC_ONLY.fullmatch(rest):
                continue
            if words(label) in self.descriptors or index.class_match(label):
                yield rest

    def section(self, index, label):
        return index.class_match(label) or self.category_alias.get(class_words(label))

    def possible_section(self, text):
        """Слово из отраслевого названия ('audio editor', '3D графика') подсказывает класс замены."""
        matches = {section for word in words(text) for cue, section in self.name_topics.items()
                   if word.startswith(cue) or word.endswith(cue)}
        return next(iter(matches)) if len(matches) == 1 else None

    def qualified_class(self, index, label):
        # «Архиваторы чертежей» сохраняют раздел, «архиваторы RARSoft» — издателя.
        head, sep, last = label.rpartition(" ")
        if not sep or last in index.slang or lemma(last) in index.vendor_names:
            return None
        section = index.class_match(head)
        if section and (lemma(last) in {"предприятие", "организация", "компания", "файл", "документ"}
                        or plural_with_object(head.split()[0], last)):
            return section

    def acronym_cards(self, index, text):
        parts = words(text)
        groups = [self.acronyms[w] for w in parts if w not in QUALIFIERS and w in self.acronyms]
        if not groups:
            return ()
        matches = set.intersection(*groups)
        brands = {index.vendor_names[w] for w in parts if w in index.vendor_names}
        if brands:
            matches = {cid for cid in matches if index.card_vendors[cid] in brands}
        evidence = set(words(text))
        return sorted(matches, key=lambda cid: (len(evidence & index.terms[cid]), index.line_popularity.get(cid, ()), index.quality[cid], cid), reverse=True)
