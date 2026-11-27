"""Курируемая таблица задач магазина программ и привязка к карточкам фида."""
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
import json
import logging
from pathlib import Path
import re
import yaml

from kuznitsa.text import normalize
from .feed import words

log = logging.getLogger(__name__)

AUX_PIN = re.compile(
    r"\b(?:обучен\w*|курс\w*|express course|поддержк\w*|техподдержк\w*|"
    r"support and maintenance|продлен\w*|миграц\w*|модул\w*|плагин\w*|"
    r"plug-?in|add-?ons?|опци\w*|сертификат на оказание|услуг\w*|кресл\w*|"
    r"книг\w*|учебник\w*|аудит и восстановление|сопровожден\w*)\b",
    re.I,
)
TARGET_OF = re.compile(r"\b(?:для|for|под|к)\s+$")


def key(text):
    return " ".join(re.findall(r"\w+", normalize(text)))


@dataclass(frozen=True)
class SolutionHit:
    id: str
    title: str
    note: str
    cards: tuple
    sections: tuple
    kit: bool
    exact: bool
    phrase_len: int
    brand: object = None


def load_rows(kb_dir):
    path = Path(kb_dir) / "feed_solutions.yaml"
    if not path.is_file():
        return [], []
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.CSafeLoader)
    except (yaml.YAMLError, UnicodeError) as exc:
        return [], [f"feed_solutions.yaml: {exc}"]
    if not isinstance(data, list):
        return [], ["feed_solutions.yaml: ожидается список задач"]
    rows, warnings = [], []
    seen = set()
    for i, item in enumerate(data, 1):
        if not isinstance(item, dict):
            warnings.append(f"feed_solutions.yaml [{i}]: строка не является словарём")
            continue
        ident = item.get("id")
        title = item.get("title")
        phrases = item.get("phrases")
        pins = item.get("pins", [])
        sections = item.get("sections", [])
        avoid = item.get("avoid", [])
        replaces = item.get("replaces", [])
        if not isinstance(ident, str) or not ident.strip():
            warnings.append(f"feed_solutions.yaml [{i}]: отсутствует id")
            continue
        if ident in seen:
            warnings.append(f"feed_solutions.yaml [{ident}]: повтор id")
            continue
        if not isinstance(title, str) or not title.strip():
            warnings.append(f"feed_solutions.yaml [{ident}]: отсутствует title")
            continue
        if not isinstance(phrases, list) or not phrases or not all(isinstance(p, str) and p.strip() for p in phrases):
            warnings.append(f"feed_solutions.yaml [{ident}]: некорректное поле phrases")
            continue
        if not isinstance(pins, list) or not all(isinstance(p, str) and p.strip() for p in pins):
            warnings.append(f"feed_solutions.yaml [{ident}]: некорректное поле pins")
            continue
        if not isinstance(sections, list) or not all(isinstance(s, str) and s.strip() for s in sections):
            warnings.append(f"feed_solutions.yaml [{ident}]: некорректное поле sections")
            continue
        if not isinstance(avoid, list) or not all(isinstance(a, str) and a.strip() for a in avoid):
            warnings.append(f"feed_solutions.yaml [{ident}]: некорректное поле avoid")
            continue
        if not isinstance(replaces, list) or not all(isinstance(r, str) and r.strip() for r in replaces):
            warnings.append(f"feed_solutions.yaml [{ident}]: некорректное поле replaces")
            continue
        seen.add(ident)
        rows.append(item)
    return rows, warnings


def _avoided(title_key, avoid_keys):
    return any(bad in title_key for bad in avoid_keys)


def _pin_candidates(pin, card_meta, avoid_keys, quality):
    pin_key = key(pin)
    if not pin_key:
        return []
    pin_rx = re.compile(r"(?:^|\s)" + re.escape(pin_key) + r"(?:\s|$)")
    pin_is_aux = bool(AUX_PIN.search(pin))
    pin_words = set(words(pin))
    hits = []
    for cid, title, title_key, vendor_key, domain, title_words in card_meta:
        if avoid_keys and _avoided(title_key, avoid_keys):
            continue
        m = pin_rx.search(title_key)
        if m:
            match_kind = 2
            pos = m.start()
        elif pin_key in title_key:
            match_kind = 1
            pos = title_key.find(pin_key)
        elif len(pin_words) >= 2 and pin_words <= title_words:
            match_kind = 0
            pos = 50
        else:
            continue
        prefix = title_key[:pos].strip()
        is_for_target = bool(TARGET_OF.search(title_key[:pos]))
        is_aux = (not pin_is_aux) and bool(AUX_PIN.search(title))
        starts = (title_key == pin_key) or title_key.startswith(pin_key + " ") or (
            bool(vendor_key) and title_key.startswith(vendor_key + " " + pin_key)
        )
        score = (
            not is_for_target,
            not is_aux,
            domain != "hardware",
            match_kind,
            starts,
            -pos,
            quality.get(cid, (False, False, 0, -len(title))),
            cid,
        )
        hits.append((score, cid))
    hits.sort(key=lambda pair: pair[0], reverse=True)
    return [cid for _, cid in hits]


def bind(rows, cards, classes, groups=None, quality=None, browse_quality=None):
    """Разрешить шаблоны карточек (pins) и разделы (sections) в конкретном снимке."""
    quality = quality or {}
    browse_quality = browse_quality or {}
    groups = groups or {}
    section_ids = defaultdict(list)
    for sec, label in classes.items():
        section_ids[key(label)].append(sec)

    card_meta = [
        (cid, title, key(title), key(vendor or ""), domain, set(words(title)))
        for cid, title, vendor, domain in cards
    ]
    title_key_by_id = {cid: tkey for cid, _, tkey, _, _, _ in card_meta}
    title_by_id = {cid: title for cid, title, _, _, _, _ in card_meta}

    bound = {}
    warnings = []
    for row in rows:
        ident = row["id"]
        avoid_keys = [key(a) for a in row.get("avoid", []) if key(a)]
        sec_ids = []
        for label in row.get("sections", []):
            matched = section_ids.get(key(label))
            if matched:
                sec_ids.extend(matched)
            else:
                warnings.append(f"feed_solutions [{ident}] · раздел «{label}» отсутствует в снимке")
        sec_ids = list(dict.fromkeys(sec_ids))

        pinned = []
        used = set()
        for pin in row.get("pins", []):
            candidates = _pin_candidates(pin, card_meta, avoid_keys, quality)
            if not candidates:
                warnings.append(f"feed_solutions [{ident}] · шаблон «{pin}» не найден в снимке")
                continue
            chosen = next((cid for cid in candidates if cid not in used), candidates[0])
            if chosen not in used:
                used.add(chosen)
                pinned.append(chosen)

        # Добор из указанных разделов после закреплённых карточек
        filled = list(pinned)
        sec_pool = []
        for sec in sec_ids:
            members = list(groups.get(sec, ()))
            if browse_quality:
                members.sort(key=lambda cid: browse_quality.get(cid, (True, 0, False, 0, False)), reverse=True)
            for cid in members:
                if cid in used:
                    continue
                tkey = title_key_by_id.get(cid, "")
                if avoid_keys and _avoided(tkey, avoid_keys):
                    continue
                if AUX_PIN.search(title_by_id.get(cid, "")):
                    continue
                used.add(cid)
                sec_pool.append(cid)
        filled.extend(sec_pool)
        # Если после фильтрации вспомогательных карточек меньше 6 — добираем остаток разделов без фильтра AUX_PIN
        if len(filled) < 6:
            for sec in sec_ids:
                for cid in groups.get(sec, ()):
                    if cid in used:
                        continue
                    tkey = title_key_by_id.get(cid, "")
                    if avoid_keys and _avoided(tkey, avoid_keys):
                        continue
                    used.add(cid)
                    filled.append(cid)
                    if len(filled) >= 12:
                        break

        bound[ident] = (tuple(filled), tuple(sec_ids), tuple(pinned))
    return bound, warnings


def check_snapshot(kb, kb_dir, data):
    """Проверка feed_solutions.yaml против снимка каталога (для kb-check и тестов)."""
    rows, load_warnings = load_rows(kb_dir)
    kb.warnings.extend(load_warnings)
    if not rows:
        return
    catalog = data / "catalog.jsonl"
    if not catalog.exists():
        return
    from .hardware import model_title
    from .source import read_offer

    tree_file = data / "feed_categories.json"
    tree = json.loads(tree_file.read_text()) if tree_file.exists() else {}
    cards, classes = {}, {}
    with catalog.open() as stream:
        for line in stream:
            offer = read_offer(line)
            if not offer.domain:
                continue
            if any(str(offer.attrs.get(k, "")).lower() in ("false", "нет", "no", "0") for k in ("active", "sold")):
                continue
            path = offer.category_path
            section = offer.class_id or (path[1] if len(path) > 1 else offer.category_id)
            classes[section] = path[min(1, len(path) - 1)] if path else str(section)
            if offer.card_id not in cards:
                title = (tree.get(offer.group_id) or [None])[0] or offer.family_name or (path or [offer.name])[-1]
                if offer.domain == "hardware" and not offer.group_id:
                    title = model_title(offer)
                cards[offer.card_id] = (offer.card_id, title, offer.vendor, offer.domain)
    if cards:
        _, warnings = bind(rows, cards.values(), classes)
        kb.warnings.extend(warnings)


class SolutionIndex:
    def __init__(self, index, kb_dir):
        self.index = index
        self.rows, self.warnings = load_rows(kb_dir)
        self.by_id = {row["id"]: row for row in self.rows}
        self.exact = {}
        self.cues = []
        self.abbreviations = set()
        self.replace_map = {}

        if not self.rows:
            self.bound = {}
            self.match = lru_cache(512)(self.match)
            self.match_replacement = lru_cache(256)(self.match_replacement)
            return

        cards = [
            (c.id, c.title, c.offers[0].vendor, c.offers[0].domain)
            for c in index.cat.cards.values()
        ]
        self.bound, bind_warnings = bind(
            self.rows,
            cards,
            index.classes,
            groups=index.groups,
            quality=index.quality,
            browse_quality=index.browse_quality,
        )
        self.warnings.extend(bind_warnings)
        for msg in bind_warnings:
            log.warning(msg)

        for row in self.rows:
            ident = row["id"]
            cards_for_row, sec_ids, _ = self.bound.get(ident, ((), (), ()))
            if not cards_for_row and not sec_ids:
                continue
            for phrase in row["phrases"]:
                pkey = key(phrase)
                if not pkey:
                    continue
                self.exact.setdefault(pkey, ident)
                raw_tokens = pkey.split()
                if len(raw_tokens) == 1:
                    self.abbreviations.add(pkey)
                lemmas = frozenset(words(phrase))
                if lemmas:
                    # Для коротких однословных терминов/аббревиатур (<=4 символов) требуем точный токен
                    need_raw = pkey if (len(raw_tokens) == 1 and len(pkey) <= 4) else None
                    self.cues.append((lemmas, len(lemmas), len(pkey), need_raw, ident))
            for target in row.get("replaces", []):
                tkey = key(target)
                if tkey:
                    self.replace_map.setdefault(tkey, ident)

        self.cues.sort(key=lambda item: (item[1], item[2]), reverse=True)
        self.match = lru_cache(512)(self.match)
        self.match_replacement = lru_cache(256)(self.match_replacement)

    def _hit(self, ident, exact=False, phrase_len=0):
        row = self.by_id[ident]
        cards, sections, _ = self.bound[ident]
        title = row["title"]
        note = row.get("note") or title
        return SolutionHit(
            id=ident,
            title=title,
            note=note,
            cards=cards,
            sections=sections,
            kit=bool(row.get("kit")),
            exact=exact,
            phrase_len=phrase_len,
        )

    def is_exact_phrase(self, text):
        return key(text) in self.exact

    def match(self, text):
        if not self.rows or not text:
            return None
        qkey = key(text)
        if not qkey:
            return None
        ident = self.exact.get(qkey)
        if ident and ident in self.bound:
            return self._hit(ident, exact=True, phrase_len=len(words(qkey)) or 1)
        q_lemmas = set(words(text))
        if not q_lemmas:
            return None
        q_raw = set(qkey.split())
        for cue_lemmas, cue_len, _, need_raw, ident in self.cues:
            if need_raw is not None:
                if need_raw in q_raw:
                    return self._hit(ident, exact=(qkey == need_raw), phrase_len=1)
                continue
            if cue_lemmas <= q_lemmas:
                return self._hit(ident, exact=False, phrase_len=cue_len)
        return None

    def match_replacement(self, subject):
        if not self.replace_map or not subject:
            return None
        skey = key(subject)
        ident = self.replace_map.get(skey)
        if not ident:
            for target_key, tid in self.replace_map.items():
                if target_key and re.search(r"(?:^|\s)" + re.escape(target_key) + r"(?:\s|$)", skey):
                    ident = tid
                    break
        if ident and ident in self.bound:
            return self._hit(ident, exact=True, phrase_len=len(skey.split()))
        return None
