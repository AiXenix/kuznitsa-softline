"""Привязка справочника замен к продаваемым карточкам конкретного снимка."""
from collections import defaultdict
from functools import lru_cache
import json
import re

from rapidfuzz import process
from rapidfuzz.distance import DamerauLevenshtein
from .feed_words import pronunciations
from kuznitsa.text import normalize
from kuznitsa.understand.spell_index import roman


def key(text):
    return " ".join(re.findall(r"\w+", normalize(text)))


def bind(rows, cards, classes):
    """Одинаковые проверки ссылок в поиске и в kb-check."""
    titles = [(cid, key(title), key(vendor or "")) for cid, title, vendor in cards]
    section_ids = defaultdict(list)
    for section, label in classes.items():
        section_ids[key(label)].append(section)
    bound, warnings = {}, []
    for ident, row in rows.items():
        sections, targets = [], []
        for label in row["sections"]:
            ids = section_ids.get(key(label))
            if ids:
                sections.extend(ids)
            else:
                warnings.append(f"feed_analogs [{ident}] · раздел «{label}» отсутствует в снимке")
        for target in row["analogs"]:
            title, vendor = key(target["title"]), key(target.get("vendor", ""))
            matches = [cid for cid, name, brand in titles if title in name and (not vendor or vendor == brand)]
            if not matches:
                warnings.append(f"feed_analogs [{ident}] · карточка «{target['title']}» ({target.get('vendor') or 'любой вендор'}) отсутствует в снимке")
            targets.append((target, matches))
        bound[ident] = (list(dict.fromkeys(sections)), targets)
    return bound, warnings


def check_snapshot(kb, data):
    rows = kb.rows["feed_analogs"]
    catalog = data / "catalog.jsonl"
    if not rows:
        return
    no_feed = "feed_analogs · для проверки разделов и названий укажите снимок фида в KZ_DATA_DIR"
    if not catalog.exists():
        kb.warnings.append(no_feed)
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
            if any(str(offer.attrs.get(k,"")).lower() in ("false","нет","no","0") for k in ("active","sold")):
                continue
            path = offer.category_path
            section = offer.class_id or (path[1] if len(path)>1 else offer.category_id)
            classes[section] = path[min(1,len(path)-1)] if path else str(section)
            if offer.card_id not in cards:
                title = (tree.get(offer.group_id) or [None])[0] or offer.family_name or (path or [offer.name])[-1]
                if offer.domain=="hardware" and not offer.group_id:
                    title=model_title(offer)
                cards[offer.card_id] = (offer.card_id, title, offer.vendor)
    if cards:
        _, warnings = bind(rows, cards.values(), classes)
        kb.warnings.extend(warnings)
    else:
        kb.warnings.append(no_feed)


class AnalogIndex:
    def __init__(self, index, rows):
        self.rows = rows
        self.names = {}
        for ident, row in rows.items():
            for alias in row["names"]:
                name = key(alias)
                self.names.setdefault(name, ident)
        for name, ident in list(self.names.items()):
            self.names.setdefault(roman(name), ident)
            if re.fullmatch(r"[a-z0-9 ]+",name):
                for sound in pronunciations(name):
                    self.names.setdefault(sound,ident)
        self.lookup = lru_cache(512)(self.lookup)
        self.bound, _ = bind(rows, ((c.id, c.title, c.offers[0].vendor) for c in index.cat.cards.values()), index.classes) if rows else ({}, [])
        self.registered = {}
        for cid, card in index.cat.cards.items():
            offer = next((o for o in card.offers if o.registry), None)
            if offer:
                self.registered[cid] = offer
        self.declared_domestic = set()
        self.domestic_sections = {k for k,label in index.class_names.items()
                                  if re.search(r"\(\s*импортозамещение\s*\)",label)}
        for section in self.domestic_sections:
            self.declared_domestic.update(index.groups[section])
        for _, targets in self.bound.values():
            for target, matches in targets:
                if target.get("russian"):
                    self.declared_domestic.update(matches)
        self.domestic = self.declared_domestic.union(self.registered)

    def lookup(self, text, fuzzy=True):
        if not self.names:
            return None
        name = key(text)
        ident = self.names.get(name) or self.names.get(roman(name))
        if not ident:
            base = re.sub(r" (?:v|версия )?\d+(?: \d+)*$", "", name)
            ident = self.names.get(base)
        if not ident and fuzzy and len(name)>=5:
            hits = process.extract(name, self.names.keys(), scorer=DamerauLevenshtein.distance,
                                   score_cutoff=1 if len(name)<11 else 2, limit=3)
            if hits and len({self.names[w] for w,d,_ in hits if d==hits[0][1]})==1:
                ident = self.names[hits[0][0]]
        return self.rows.get(ident)
