"""Флагманский порядок линеек, деприоритизация дополнений и аудитория по количеству мест."""
import re
import yaml

from kuznitsa.text import normalize
from .feed import ALIASES, EXACT_ONLY_ALIASES, words
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
    "сертификат на ",
    "дополнительные компоненты",
    "комплекты документации",
    "пробная версия",
    "для подключения к фау",
    "поддержк",
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
_DEMOTE_EXPLICIT = frozenset({"курс", "обучение", "поддержка", "коннектор", "connector", "сертификат"})

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
    "enterprise", "standard", "стандарт", "стандартный", "e3", "e5", "f3", "plus", "плюс",
    "premium", "премиум", "cloud", "облачный", "mac", "macos", "linux",
    "professional", "профессиональный", "business", "бизнес", "edition", "редакция",
    "basic", "base", "базовый", "расширенный", "универсальный", "корпоративный",
    "защита", "безопасность", "security", "система", "программа", "сервис",
    "лицензия", "подписка", "версия", "для", "for", "macintosh", "windows",
})

_SERVICE_WORDS = frozenset({
    "продление", "продлить", "renewal", "купить", "покупка", "лицензия", "лицензии",
    "подписка", "бессрочный", "бессрочная", "на", "год", "года", "лет", "мес", "месяц",
    "новый", "новая", "электронный", "электронная", "ключ", "по",
})


def _strip_lead(seq, skip):
    pos = 0
    while pos < len(seq) and seq[pos] in skip:
        pos += 1
    return seq[pos:] if pos < len(seq) else seq


class FeedFlagships:
    """Ранги главных линеек, деприоритизация дополнений и мост семейств KB → фид."""

    def __init__(self, index, kb, cfg):
        self.index = index
        self.rank = {}
        self.demoted = set()
        self.aux_title = set()
        self.card_year = {}
        self.core_generic = {}
        self.core_product = {}
        self._card_entry_id = {}
        self._addon_words = {}
        self._for_addon = {}
        self._has_cal = set()
        self._audience = {}
        self._section_rules = {}
        self._section_demoted = {}
        self._load_yaml(cfg)
        self._compute_cards()
        self._apply_quality()
        index.flagships = self
        index.products.cache_clear()
        self._bridge_kb_families(kb)
        self._align_alias_slang()

    def _load_yaml(self, cfg):
        self._entries = []
        self._section_rules = {}
        self.vendor_aliases = set()
        kb_dir = getattr(cfg, "kb", None)
        path = (kb_dir / "feed_flagships.yaml") if kb_dir else None
        if not path or not path.is_file():
            return
        rows = yaml.load(path.read_text(), Loader=yaml.CSafeLoader) or []
        for row in rows:
            sec_name = row.get("section")
            if sec_name:
                self._section_rules[normalize(sec_name)] = (
                    tuple(normalize(v) for v in row.get("top_vendors", []) if v),
                    tuple(normalize(d) for d in row.get("demote_in_section", []) if d),
                )
                continue
            entry_id = normalize(row.get("id", ""))
            vendors = {normalize(v) for v in row.get("vendors", []) if v}
            vendor_words = {tuple(words(v)) for v in row.get("vendors", []) if v}
            lines = [normalize(t) for t in row.get("lines", []) if t]
            demote = [normalize(d) for d in row.get("demote", []) if d]
            self.vendor_aliases.update(vendors)
            self.vendor_aliases.update(" ".join(vw) for vw in vendor_words if vw)
            self._entries.append((entry_id, vendors, vendor_words, lines, demote))

    def _match_vendor(self, vendor_norm, vendor_w):
        for entry_id, vendors, vwords, lines, demote in self._entries:
            if vendor_norm in vendors or vendor_w in vwords:
                return entry_id, lines, demote
            if any(v and (v in vendor_norm or vendor_norm in v) for v in vendors if len(v) >= 4):
                return entry_id, lines, demote
        return "", (), ()

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

            entry_id, lines, demote = self._match_vendor(vendor_norm, vendor_w)
            if entry_id:
                self._card_entry_id[cid] = entry_id
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

    def _vendor_key(self, cid):
        eid = self._card_entry_id.get(cid)
        if eid:
            return eid
        card = self.index.cat.cards[cid]
        return normalize(card.vendor or card.offers[0].vendor or "")

    def _apply_section_rules(self):
        index = self.index
        self._section_demoted = {}
        if not self._section_rules:
            return
        for sec, group in index.groups.items():
            sec_norm = index.class_names.get(sec) or normalize(index.classes.get(sec, ""))
            rule = self._section_rules.get(sec_norm)
            if not rule:
                continue
            top_vendors, demote_pats = rule
            demoted_cids = set()
            by_top_vendor = {v: [] for v in top_vendors}
            mid = []
            tail = []
            for cid in group:
                title_norm = normalize(index.cat.cards[cid].title)
                if any(p in title_norm for p in demote_pats):
                    demoted_cids.add(cid)
                    tail.append(cid)
                    continue
                vkey = self._vendor_key(cid)
                if vkey in by_top_vendor and cid not in self.demoted:
                    by_top_vendor[vkey].append(cid)
                else:
                    mid.append(cid)
            # Чередуем флагманов приоритетных вендоров в верху раздела (Kaspersky / Dr.Web / PRO32),
            # затем остальные карточки раздела, и в самом конце — деприоритизированные (NGFW и др.).
            interleaved = []
            buckets = [by_top_vendor[v] for v in top_vendors if by_top_vendor[v]]
            for pos in range(max((len(b) for b in buckets), default=0)):
                for b in buckets:
                    if pos < len(b):
                        interleaved.append(b[pos])
            group[:] = interleaved + mid + tail
            if demoted_cids:
                self._section_demoted[sec] = frozenset(demoted_cids)

    def section_demoted(self, section):
        return self._section_demoted.get(section, frozenset())

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
        self._apply_section_rules()
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

    def _align_alias_slang(self):
        """Уточняет семейные записи index.slang по конкретным алиасам (ворд/эксель/аутлук) и неполным однокарточным семействам (нанокад/архикад)."""
        index = self.index
        for phrase, target in ALIASES.items():
            if phrase in EXACT_ONLY_ALIASES or phrase not in index.slang:
                continue
            field, members = index.slang[phrase]
            if field != "families":
                continue
            direct = index.products(target, fuzzy=False)
            if not direct:
                continue
            top_words = set(words(index.cat.cards[members[0]].title)) if members else set()
            direct_words = set(words(index.cat.cards[direct[0]].title))
            target_words = set(words(target))
            is_refinement = bool(target_words and not (target_words <= top_words) and (target_words <= direct_words))
            if is_refinement or (len(direct) < len(members) and set(direct) <= set(members)) or (len(members) < 4 and len(direct) > len(members)):
                index.slang[phrase] = ("families", tuple(direct))

    def has_catalog_alias(self, base):
        """Если алиас ведёт к реальной флагманской линейке в каталоге («ворд» → Word 2021), не подменяем её заглушкой «нет в каталоге»."""
        index = self.index
        aliased = index.correct(base)
        if aliased == base:
            return False
        hits = index.products(aliased, fuzzy=False)
        return bool(hits and self.rank.get(hits[0], 0) > 0 and sold_as(index.cat.cards[hits[0]], aliased))

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
        if cid in self._has_cal and "cal" in qset:
            return False
        if qset & _DEMOTE_EXPLICIT:
            return False
        return True

    def audience_tier(self, cid):
        """+1 бизнес/корпоратив, 0 нейтрально, -1 дом/семья/персональный."""
        return self._audience.get(cid, 0)

    def _named_tier(self, cid, q_terms, qset):
        """Совпадение очищенного запроса с названием карточки: 3 — целиком/покрывает все слова, 2 — редакция, 1 — содержит все слова, 0 — остальное."""
        card = self.index.cat.cards[cid]
        name = words(card.title)
        core_gen = self.core_generic.get(cid, name)
        core_prod = self.core_product.get(cid, name)
        rank = self.rank.get(cid, 0)
        n = len(q_terms)
        if (q_terms == name or q_terms == core_gen
                or (q_terms == core_prod and rank > 0)
                or (len(core_gen) >= 2 and frozenset(core_gen) == qset)):
            return 3
        # Запрос покрывает все значимые слова карточки (напр. с лишним служебным словом), но не короче 2 слов.
        if len(core_gen) >= 2 and frozenset(core_gen) < qset and len(qset - frozenset(core_gen)) <= 1:
            return 3
        if n >= 2 and (core_gen[:n] == q_terms or name[:n] == q_terms or (core_prod[:n] == q_terms and rank > 0)):
            return 2
        if n >= 2 and qset <= frozenset(name):
            return 1
        return 0

    def prioritize_named(self, ids, q):
        """Если запрос без служебных слов совпадает с карточкой целиком — она первая, затем её редакции, затем остальная линейка."""
        if not ids or len(ids) < 2 or not q:
            return ids
        q_terms = tuple(w for w in words(q) if w not in _SERVICE_WORDS)
        if not q_terms:
            return ids
        joined = " ".join(q_terms)
        if len(q_terms) < 2 and (q in self.vendor_aliases or joined in self.vendor_aliases or q in self.index.vendor_names):
            return ids
        qset = frozenset(q_terms)
        tiers = {cid: self._named_tier(cid, q_terms, qset) for cid in ids}
        if not any(t >= 3 for t in tiers.values()):
            return ids
        return sorted(ids, key=lambda cid: tiers[cid], reverse=True)

    def filter_recognized_line(self, ids, q):
        """При распознанной флагманской линейке («office» → Microsoft Office) убирает чужие карточки с тем же словом из других разделов."""
        if not ids or len(ids) < 2 or not q:
            return ids
        q_terms = tuple(w for w in words(q) if w not in _SERVICE_WORDS)
        if not q_terms:
            return ids
        joined = " ".join(q_terms)
        if q in self.vendor_aliases or joined in self.vendor_aliases or q in self.index.vendor_names or joined in self.index.vendor_names:
            return ids
        if len(q_terms) == 1 and (len(q_terms[0]) < 4 or q_terms[0] in EDITION_QUALIFIERS):
            return ids
        n = len(q_terms)
        index = self.index

        def starts_line(cid):
            return (
                self.core_product.get(cid, ())[:n] == q_terms
                or self.core_generic.get(cid, ())[:n] == q_terms
            )

        anchor = ids[0]
        if self.rank.get(anchor, 0) <= 0 or not starts_line(anchor):
            return ids
        anchor_vendor = index.cat.cards[anchor].vendor
        anchor_sec = index.card_sections.get(anchor)
        same_vendor_count = sum(1 for cid in ids if index.cat.cards[cid].vendor == anchor_vendor and starts_line(cid))
        if same_vendor_count < 2:
            return ids
        kept = []
        alien = []
        for cid in ids:
            card = index.cat.cards[cid]
            sec = index.card_sections.get(cid)
            if card.vendor == anchor_vendor or sec == anchor_sec:
                kept.append(cid)
            else:
                alien.append(cid)
        if not alien:
            return ids
        # Если в распознанной линейке достаточно карточек (≥ 4) — убираем случайные совпадения из чужих разделов;
        # иначе сдвигаем их в самый хвост.
        if len(kept) >= 4:
            return kept
        return kept + alien

    def apply_audience_order(self, ids, qty, query_text, *, base_ids=None, selections=None, q=None, section=None, budget=None, renewal=False):
        """Сохраняет прямую линейку при подборе по тиражу и при qty >= 5 поднимает бизнес-редакции (в разделе — только вниз уходят домашние)."""
        if not ids or not qty:
            return ids
        if base_ids and selections and not section and budget is None and not renewal and q:
            q_terms = words(q)
            if len(q_terms) >= 2:
                direct = [cid for cid in base_ids if self.core_generic.get(cid, ())[:len(q_terms)] == q_terms]
                if direct and not any(cid in selections for cid in direct):
                    ids = direct
        if qty.get("value", 0) < 5:
            return ids
        if HOME_EXPLICIT.search(query_text or ""):
            return ids
        if section:
            # В классе порядок раздела и подтверждённый тираж важнее слова Business или Enterprise
            # в названии: такие карточки не обгоняют нейтральные, вниз уходят только домашние редакции.
            return sorted(ids, key=lambda cid: min(self._audience.get(cid, 0), 0), reverse=True)
        return sorted(ids, key=self._audience.get, reverse=True)
