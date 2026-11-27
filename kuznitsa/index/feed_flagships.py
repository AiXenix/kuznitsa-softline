"""Флагманский порядок линеек, деприоритизация дополнений и аудитория по количеству мест."""
import re
import yaml

from kuznitsa.text import normalize
from .feed import words
from .feed_language import sold_as

GENERIC_PREFIXES = frozenset({
    "программа", "программный", "обеспечение", "платформа", "операционный",
    "система", "архиватор", "облачный", "пакет", "субд", "пак", "пк",
    "комплекс", "сервис", "swg", "управление", "проект",
})

GLOBAL_DEMOTE = (
    "rights management services",
    "external connector",
    "audit and control management",
    "express course",
    "обучающие курсы",
    "сертификаты технической поддержки",
    "дополнительные компоненты",
    "комплекты документации",
    "пробная версия",
    "для подключения к фау",
    "поддержка",
    "обучен",
    "курс ",
    "миграц",
)

ADDON_WORDS = frozenset({
    "модуль", "плагин", "plugin", "connector", "коннектор", "addon",
    "agent", "агент", "driver", "драйвер", "modplus", "spamfighter",
    "comparer", "exporter", "generator", "masker", "calendar", "backup",
})

_FOR_TAIL_RE = re.compile(r"\b(?:for|для)\s+(.+)$")
_AUX_TITLE_RE = re.compile(r"поддержк|обучен|курс |сертификат|миграц|продлен", re.I)
_YEAR_RE = re.compile(r"20[012]\d")
_DEMOTE_EXPLICIT = frozenset({"курс", "обучение", "поддержка", "коннектор", "connector"})

HOME_EXPLICIT = re.compile(
    r"\b(?:домашн\w*|домой|для дома|для семьи|семья|семейн\w*|персональн\w*|home|family|personal|student|уч[её]б\w*)\b",
    re.I,
)
HOME_TITLE = re.compile(
    r"\b(?:family|семья|семьи|personal|персональн\w*|home|домашн\w*|для дома|для семьи|student|уч[её]б\w*|safe kids)\b",
    re.I,
)
BUSINESS_TITLE = re.compile(
    r"\b(?:business|бизнес\w*|enterprise|корпоратив\w*|f3|e3|e5|endpoint|small office|"
    r"professional|профессиональн\w*|standard|стандартн\w*|server|сервер\w*|"
    r"юридических лиц|для организаций|workstation|рабочая станция|pro)\b",
    re.I,
)
EDITION_QUALIFIERS = frozenset({
    "lt", "лт", "pro", "про", "home", "дом", "server", "сервер",
    "enterprise", "standard", "стандарт", "e3", "e5", "f3", "plus", "плюс",
    "premium", "премиум", "cloud", "облачный", "mac", "macos", "linux",
})


def _strip_lead(seq, skip):
    pos = 0
    while pos < len(seq) and seq[pos] in skip:
        pos += 1
    return seq[pos:] if pos < len(seq) else seq


class FeedFlagships:
    """Ранги главных линеек, распознавание надстроек и мост семейств KB → фид."""

    def __init__(self, index, kb, cfg):
        self.index = index
        self.rank = {}
        self.demoted = set()
        self.aux_title = set()
        self.card_year = {}
        self.core_generic = {}
        self.core_product = {}
        self._addon_words = {}
        self._for_addon = {}
        self._has_cal = set()
        self._audience = {}
        self._load_yaml(cfg)
        self._compute_cards()
        self._apply_quality()
        self._bridge_kb_families(kb)

    def _load_yaml(self, cfg):
        self._entries = []
        kb_dir = getattr(cfg, "kb", None)
        path = (kb_dir / "feed_flagships.yaml") if kb_dir else None
        if not path or not path.is_file():
            return
        rows = yaml.load(path.read_text(), Loader=yaml.CSafeLoader) or []
        for row in rows:
            vendors = {normalize(v) for v in row.get("vendors", []) if v}
            vendor_words = {tuple(words(v)) for v in row.get("vendors", []) if v}
            lines = [normalize(t) for t in row.get("lines", []) if t]
            demote = [normalize(d) for d in row.get("demote", []) if d]
            self._entries.append((vendors, vendor_words, lines, demote))

    def _match_vendor(self, vendor_norm, vendor_w):
        for vendors, vwords, lines, demote in self._entries:
            if vendor_norm in vendors or vendor_w in vwords:
                return lines, demote
            if any(v and (v in vendor_norm or vendor_norm in v) for v in vendors if len(v) >= 4):
                return lines, demote
        return (), ()

    def _compute_cards(self):
        cat = self.index.cat
        for cid, card in cat.cards.items():
            title_norm = normalize(card.title)
            title_words = words(card.title)
            title_set = frozenset(title_words)
            vendor_raw = card.offers[0].vendor or card.vendor or ""
            vendor_norm = normalize(vendor_raw)
            vendor_w = words(vendor_raw)

            generic_stripped = _strip_lead(title_words, GENERIC_PREFIXES)
            vendor_set = set(vendor_w) | GENERIC_PREFIXES
            product_stripped = _strip_lead(generic_stripped, vendor_set)
            self.core_generic[cid] = generic_stripped
            self.core_product[cid] = product_stripped

            if _AUX_TITLE_RE.search(card.title):
                self.aux_title.add(cid)
            years = [int(y) for y in title_words if _YEAR_RE.fullmatch(y)]
            if years:
                self.card_year[cid] = max(years)

            lines, demote = self._match_vendor(vendor_norm, vendor_w)
            is_demoted = False
            if any(pat in title_norm for pat in GLOBAL_DEMOTE):
                is_demoted = True
            if "cal" in title_set:
                is_demoted = True
                self._has_cal.add(cid)
            if any(pat in title_norm for pat in demote):
                is_demoted = True

            rank = 0
            if not is_demoted and lines:
                for pos, line in enumerate(lines):
                    if title_norm == line:
                        rank = max(rank, 200 - pos)
                        break
                if not rank:
                    for pos, line in enumerate(lines):
                        if line and (title_norm.startswith(line + " ") or title_norm.startswith(line + "(")):
                            rank = max(rank, 150 - pos)
                            break
                if not rank:
                    for pos, line in enumerate(lines):
                        if line and len(line) >= 8 and line in title_norm:
                            rank = max(rank, 100 - pos)
                            break

            self.rank[cid] = rank
            if is_demoted:
                self.demoted.add(cid)

            if rank == 0:
                addon_w = title_set & ADDON_WORDS
                if addon_w:
                    self._addon_words[cid] = addon_w
                m = _FOR_TAIL_RE.search(title_norm)
                if m:
                    tail_words = frozenset(words(m.group(1)))
                    lead = words(title_norm[:m.start()])
                    if lead and tail_words:
                        self._for_addon[cid] = (frozenset(lead[:2]), tail_words)

            has_home = bool(HOME_TITLE.search(title_norm))
            has_biz = bool(BUSINESS_TITLE.search(title_norm))
            if has_home and not has_biz:
                self._audience[cid] = -1
            elif has_biz and not has_home:
                self._audience[cid] = 1
            else:
                self._audience[cid] = 0

    def _apply_quality(self):
        index = self.index
        for cid, card in index.cat.cards.items():
            o = card.offers[0]
            r = self.rank.get(cid, 0)
            demoted = cid in self.demoted
            offer_bucket = min(len(card.offers), 40) // 4
            index.quality[cid] = (
                o.available,
                not demoted,
                r > 0,
                r,
                o.price is not None,
                offer_bucket,
                -len(card.title),
            )
            aux_ok = index.browse_quality[cid][0] if cid in index.browse_quality else True
            pop = max((v.popularity for v in card.offers), default=0)
            index.browse_quality[cid] = (
                aux_ok and not demoted,
                r > 0,
                r,
                pop,
                o.available,
                offer_bucket,
                o.price is not None,
            )
        for group in index.groups.values():
            group.sort(key=index.quality.get, reverse=True)
        index.popular = sorted(index.cat.cards, key=index.quality.get, reverse=True)
        for phrase, (field, members) in list(index.slang.items()):
            ordered = tuple(sorted(members, key=lambda i: (index.quality[i], i), reverse=True))
            index.slang[phrase] = (field, ordered)

    def _bridge_kb_families(self, kb):
        index = self.index
        if not kb or "families" not in kb.rows:
            return
        bridged = {}
        for fid, row in kb.rows["families"].items():
            if index.tags["families"].get(fid):
                continue
            if row.get("catalog") is False:
                continue
            name = row.get("name") or ""
            if not name or len(normalize(name)) < 3:
                continue
            hits = index.products(normalize(name), fuzzy=False)
            if not hits:
                continue
            vid = row.get("vendor")
            vendor_members = index.tags["vendors"].get(str(vid).casefold()) if vid else None
            matched = []
            for cid in hits:
                card = index.cat.cards[cid]
                if vendor_members and cid not in vendor_members:
                    continue
                if sold_as(card, name):
                    matched.append(cid)
            if matched:
                index.tags["families"][fid].update(matched)
                bridged[fid] = (name, matched)

        if not bridged:
            return

        for phrase, row in kb.rows["slang"].items():
            key = normalize(phrase)
            if not key or key in index.slang or key in index.aliases:
                continue
            fid = row.get("maps_to", {}).get("family")
            if not fid or fid not in bridged:
                continue
            fam_name, members = bridged[fid]
            fam_words = set(words(fam_name))
            phrase_words = set(words(key))
            # Не подменяем запрос с уточнением редакции (например «автокад лт») всем семейством.
            if (phrase_words & EDITION_QUALIFIERS) - fam_words:
                continue
            exact = normalize(fam_name)
            ordered = tuple(sorted(
                members,
                key=lambda i: (normalize(index.cat.cards[i].title) == exact, index.quality[i], i),
                reverse=True,
            ))
            index.slang[key] = ("families", ordered)

    def is_addon(self, cid, query_terms):
        """Определяет сторонние модули, плагины и утилиты «for <product> / для <product>»."""
        if self.rank.get(cid, 0) > 0:
            return False
        qset = query_terms if isinstance(query_terms, (set, frozenset)) else frozenset(query_terms)
        addon_w = self._addon_words.get(cid)
        if addon_w and (addon_w - qset):
            return True
        pair = self._for_addon.get(cid)
        if pair and qset:
            lead_set, tail_set = pair
            if qset <= tail_set and not (lead_set & qset):
                return True
        return False

    def is_demoted(self, cid, query_terms):
        if cid not in self.demoted:
            return False
        qset = query_terms if isinstance(query_terms, (set, frozenset)) else frozenset(query_terms)
        # Если пользователь явно попросил CAL / курс / поддержку — не штрафуем.
        if cid in self._has_cal and "cal" in qset:
            return False
        if qset & _DEMOTE_EXPLICIT:
            return False
        return True

    def audience_tier(self, cid):
        """+1 бизнес/корпоратив, 0 нейтрально, -1 дом/семья/персональный."""
        return self._audience.get(cid, 0)

    def apply_audience_order(self, ids, qty, query_text, *, base_ids=None, selections=None, q=None, section=None, budget=None, renewal=False):
        """Сохраняет прямую линейку при подборе по тиражу и при qty >= 5 поднимает бизнес-редакции."""
        if not ids or not qty:
            return ids
        if base_ids and selections and not section and budget is None and not renewal and q:
            q_terms = words(q)
            if len(q_terms) >= 2:
                direct = [cid for cid in base_ids if self.core_generic.get(cid, ())[:len(q_terms)] == q_terms]
                if direct and not any(cid in selections for cid in direct):
                    # Ни одна карточка основной запрошенной линейки не имеет явного тиража в фиде —
                    # не позволяем сторонним надстройкам или другим линейкам вытеснить её.
                    ids = direct
        if qty.get("value", 0) < 5:
            return ids
        if HOME_EXPLICIT.search(query_text or ""):
            return ids
        return sorted(ids, key=self._audience.get, reverse=True)
