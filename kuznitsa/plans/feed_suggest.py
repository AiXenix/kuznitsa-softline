"""Подсказки при наборе для фида store.softline.ru."""
from bisect import bisect_left, bisect_right
from collections import defaultdict
from functools import lru_cache
from time import perf_counter
import re

from kuznitsa.index.feed import QUESTION, STOP, TASKS, class_words, words
from kuznitsa.index.feed_language import sold_as
from kuznitsa.index.hardware import hardware_head, rank_hardware_section
from kuznitsa.plans import feed_analogs
from kuznitsa.plans.feed import display, task_sections
from kuznitsa.plans.feed_query import HELP, HOME, PURPOSES, license_request, split_conditions
from kuznitsa.text import lemma, normalize
from kuznitsa.understand.repair import LAYOUT, typo_matcher
from kuznitsa.understand.spell_index import roman

TITLE_WRAPPER = re.compile(
    r"^(?:программа|программное обеспечение|операционная система|скзи|пак|медиапакет|система)\s+"
)
AUX_TITLE = re.compile(
    r"поддержк|обучен|курс |сертификат|миграц|продлен|модули |плагин|plugin|connector|учебн",
    re.I,
)
MAC_ONLY = re.compile(r"\bfor mac(?:intosh|os)?\b", re.I)
SERVICE_LEAD = re.compile(
    r"^(?:(?:купить|цена|стоимость|прайс|скачать|заказать|найти|подбор|подобрать|"
    r"нужен|нужна|нужно|нужны|лицензи[яиюй]|подписк[аиу]|ключ[иа]?)\s+)+"
)
SERVICE_TAIL = re.compile(
    r"(?:\s+(?:купить|цена|стоимость|прайс|скачать|заказать|лицензи[яиюй]|подписк[аиу]|ключ[иа]?))+$"
)
DURATION = re.compile(r"\b(?:на\s+)?\d{1,2}\s*(?:год\w*|лет|мес\w*)\b|\bна\s+год\b")
TRAILING_PREP = re.compile(r"(?:\s+(?:для|на|под|от|в|с|по|и|к|о|из|без|при))+$")
CORP_WORDS = {
    "corporation", "corp", "inc", "ltd", "limited", "llc", "gmbh", "systems", "software",
    "разработка", "ооо", "ао", "зао", "программы", "и", "лицензии", "группа", "лаборатория",
}
PREPOSITIONS = {"для", "на", "под", "от", "в", "с", "по", "и", "к", "о", "из", "без", "при"}


@lru_cache(131072)
def skey(text):
    return re.sub(r"[^а-яa-z0-9]+", " ", normalize(text)).strip()


def _vendor_prefixes(vendor):
    vk = skey(vendor)
    if not vk:
        return ()
    out = [vk]
    parts = [w for w in vk.split() if w not in CORP_WORDS]
    if parts:
        short = " ".join(parts)
        if short != vk:
            out.append(short)
        if len(parts) > 1 and len(parts[0]) >= 3:
            out.append(parts[0])
    return tuple(dict.fromkeys(out))


def _clean_title(title, vendor):
    tk = skey(title)
    if not tk:
        return "", ""
    clean = TITLE_WRAPPER.sub("", tk).strip() or tk
    for pref in _vendor_prefixes(vendor):
        if clean.startswith(pref + " ") and len(clean) > len(pref) + 1:
            clean = clean[len(pref) + 1:].strip()
            break
    clean = TITLE_WRAPPER.sub("", clean).strip() or clean
    return tk, clean


def _strip_parens(text):
    return re.sub(r"\s*\([^)]*\)", "", str(text or "")).strip()


def _same_script(a, b):
    return bool(re.search("[а-я]", a)) == bool(re.search("[а-я]", b))


def _is_win_term(pk):
    return "win" in pk or "винд" in pk or "вынд" in pk


class FeedSuggestIndex:
    """Предрасчитанные структуры по началам слов для быстрых подсказок фида."""

    def __init__(self, index, kb, lex=None):
        self.index = index
        self.kb = kb
        self.lex = lex

        self.title_k = {}
        self.clean_k = {}
        self.title_toks = {}
        self.clean_toks = {}
        self.is_aux = {}
        self.is_cal = {}
        self.is_mac_only = {}
        self.card_pop = {}
        self.vendor_offers = defaultdict(int)
        self.vendor_raw = {}

        title_rows = []
        for cid, card in index.cat.cards.items():
            o = card.offers[0]
            raw_v = o.vendor or ""
            tk, ck = _clean_title(card.title, raw_v)
            self.title_k[cid] = tk
            self.clean_k[cid] = ck
            self.title_toks[cid] = tuple(tk.split())
            self.clean_toks[cid] = tuple(ck.split())
            self.is_aux[cid] = bool(AUX_TITLE.search(card.title))
            self.is_cal[cid] = "cal" in self.title_toks[cid]
            self.is_mac_only[cid] = bool(MAC_ONLY.search(card.title))
            vid = index.card_vendors.get(cid)
            if vid:
                self.vendor_offers[vid] += len(card.offers)
                if vid not in self.vendor_raw and raw_v:
                    self.vendor_raw[vid] = raw_v
            if tk:
                title_rows.append((tk, cid, False))
            # Для оборудования не снимаем бренд в начале (чтобы «Defender Офисное кресло» не искалось по «оф»).
            if ck and ck != tk and o.domain != "hardware":
                title_rows.append((ck, cid, True))

        title_rows.sort(key=lambda r: r[0])
        self.title_keys = [r[0] for r in title_rows]
        self.title_rows = title_rows

        # Короткие имена вендоров фида («Программы и лицензии Microsoft Corporation» → «microsoft»).
        # Не индексируем первое слово составного имени («Office Kit» ≠ «office», «САПР-Альфа» ≠ «сапр»).
        self.short_vendor_map = {}
        for feed_v, raw_v in sorted(
            self.vendor_raw.items(),
            key=lambda kv: self.vendor_offers.get(kv[0], 0),
            reverse=True,
        ):
            vk = skey(raw_v)
            if not vk:
                continue
            parts = [w for w in vk.split() if w not in CORP_WORDS]
            cands = [vk]
            if parts:
                short = " ".join(parts)
                if short != vk:
                    cands.append(short)
            for pref in cands:
                if len(pref) >= 2 and pref not in self.short_vendor_map:
                    self.short_vendor_map[pref] = feed_v

        for cid, rank in getattr(index, "line_popularity", {}).items():
            if rank:
                self.card_pop[cid] = max(self.card_pop.get(cid, 0), int(rank[0]))

        self.vendor_kb_to_feed = {}
        for vid, row in kb.rows["vendors"].items():
            names = [row.get("name"), row.get("name_ru"), *row.get("aliases", [])]
            for name in names:
                if not name:
                    continue
                nk = normalize(str(name))
                sk = skey(str(name))
                actual = (
                    index.vendor_names.get(nk)
                    or index.vendor_names.get(" ".join(words(str(name))))
                    or self.short_vendor_map.get(sk)
                )
                if actual:
                    self.vendor_kb_to_feed[vid] = actual
                    break

        # Разворачиваем семейства и категории KB в карточки фида.
        self.family_cards = {}
        self.family_pop = {}
        self.family_canonical = {}
        self.kb_cat_cards = defaultdict(list)

        for fid, row in kb.rows["families"].items():
            pop = int(row.get("popularity") or 3)
            self.family_pop[fid] = pop
            base = _strip_parens(row.get("name", ""))
            self.family_canonical[fid] = base or row.get("name", "")
            feed_vendor = self.vendor_kb_to_feed.get(row.get("vendor"))
            members = list(index.tags["families"].get(fid, ()))
            if not members:
                candidates = []
                if base:
                    candidates.append(base)
                    if "/" in base:
                        parts = [p.strip() for p in base.split("/") if p.strip()]
                        head_words = parts[0].split()
                        candidates.append(parts[0])
                        if len(head_words) >= 2:
                            brand = head_words[0]
                            for tail in parts[1:]:
                                if len(tail.split()) == 1:
                                    candidates.append(f"{brand} {tail}")
                if row.get("title"):
                    candidates.append(_strip_parens(row["title"]))
                for alias in row.get("aliases", [])[:6]:
                    if isinstance(alias, str) and len(alias.strip()) >= 3:
                        candidates.append(alias.strip())
                found = []
                for cand in dict.fromkeys(candidates):
                    norm_c = normalize(cand)
                    if not norm_c or len(norm_c) < 2:
                        continue
                    hits = index.products(norm_c, fuzzy=False)
                    if not hits:
                        continue
                    cand_words = set(words(norm_c))
                    confirmed = [
                        cid for cid in hits
                        if sold_as(index.cat.cards[cid], norm_c)
                        or (feed_vendor and index.card_vendors.get(cid) == feed_vendor
                            and cand_words <= set(words(index.cat.cards[cid].title)))
                    ]
                    if confirmed:
                        found = confirmed
                        break
                members = found
            if members:
                base_k = skey(base)
                ordered = tuple(sorted(
                    dict.fromkeys(members),
                    key=lambda cid: (
                        self.clean_k[cid] == base_k or self.title_k[cid] == base_k,
                        not self.is_aux[cid],
                        not self.is_cal[cid],
                        not self.is_mac_only[cid],
                        index.quality[cid],
                        cid,
                    ),
                    reverse=True,
                ))
                self.family_cards[fid] = ordered
                for cid in ordered:
                    if not self.is_aux[cid] and not self.is_cal[cid]:
                        self.card_pop[cid] = max(self.card_pop.get(cid, 0), pop)
                cat_id = row.get("category")
                if cat_id:
                    self.kb_cat_cards[cat_id].extend(ordered)

        for cat_id, members in index.tags["classes"].items():
            if cat_id in kb.rows["categories"] and not self.kb_cat_cards.get(cat_id):
                self.kb_cat_cards[cat_id].extend(members)

        for cat_id in list(self.kb_cat_cards):
            dedup = list(dict.fromkeys(self.kb_cat_cards[cat_id]))
            dedup.sort(
                key=lambda cid: (
                    not self.is_aux[cid],
                    not self.is_cal[cid],
                    self.card_pop.get(cid, 0),
                    index.quality[cid],
                    cid,
                ),
                reverse=True,
            )
            self.kb_cat_cards[cat_id] = tuple(dedup)

        # Словарь сущностей (семейства, бренды, сленг, алиасы).
        # Значение: список кортежей (kind, ident, query_text, cards_tuple, weight)
        self.entities = defaultdict(list)

        def add_entity(phrase, kind, ident, target, cards, weight):
            pk = skey(phrase)
            if not pk or len(pk) < 2:
                return
            self.entities[pk].append((kind, ident, target, cards, weight))

        for fid, cards in self.family_cards.items():
            row = kb.rows["families"][fid]
            pop = self.family_pop[fid]
            canon = self.family_canonical[fid]
            add_entity(canon, "family", fid, canon, cards, pop + 2)
            for alias in row.get("aliases", []):
                if isinstance(alias, str) and len(alias.strip()) >= 2:
                    add_entity(alias, "family", fid, canon, cards, pop + 1)

        # Вендоры из фида и KB (включая короткие очищенные имена вроде «microsoft»).
        self.vendor_canonical = {}
        for feed_v, raw_v in self.vendor_raw.items():
            self.vendor_canonical[feed_v] = raw_v
        for vid, row in kb.rows["vendors"].items():
            feed_v = self.vendor_kb_to_feed.get(vid)
            if not feed_v:
                continue
            canon = row.get("name") or self.vendor_canonical.get(feed_v, "")
            if canon:
                self.vendor_canonical[feed_v] = canon
            weight = 5 if self.vendor_offers.get(feed_v, 0) >= 100 else 3
            for name in (row.get("name"), row.get("name_ru"), *row.get("aliases", [])):
                if isinstance(name, str) and len(name.strip()) >= 2:
                    add_entity(name, "vendor", feed_v, canon, (), weight)
        for vname, feed_v in index.vendor_names.items():
            canon = self.vendor_canonical.get(feed_v, vname)
            weight = 4 if self.vendor_offers.get(feed_v, 0) >= 100 else 2
            add_entity(vname, "vendor", feed_v, canon, (), weight)
        for short_v, feed_v in self.short_vendor_map.items():
            canon = self.vendor_canonical.get(feed_v, short_v)
            weight = 5 if self.vendor_offers.get(feed_v, 0) >= 100 else 2
            add_entity(short_v, "vendor", feed_v, canon, (), weight)

        # Словарь разделов, задач (все секции из feed_tasks.yaml), категорий KB и оборудования.
        # Значение: список кортежей (kind, section_ids_tuple, kb_cat_id, weight)
        self.sections = defaultdict(list)

        def add_section(phrase, kind, sec_ids, kb_cat=None, weight=4):
            pk = skey(phrase)
            secs = tuple(dict.fromkeys(str(s) for s in sec_ids if str(s) in index.groups))
            if not pk or len(pk) < 2 or not secs:
                return
            self.sections[pk].append((kind, secs, kb_cat, weight))

        # Маппинг задач feed_tasks.yaml на все их разделы и подходящую категорию KB.
        task_to_kb_cat = {
            "vpn": "ngfw_vpn",
            "esign": "e_signature",
            "office_suite": "office_suite",
            "backups": "backup_recovery",
            "home_security": "home_antivirus",
            "business_security": "endpoint_security",
            "cloud_antivirus": "endpoint_security",
            "os_linux": "desktop_os_ru",
        }
        self.kb_cat_task_secs = defaultdict(list)
        self.kb_cat_keywords = defaultdict(set)
        for tid, row in kb.rows["feed_tasks"].items():
            secs = [
                index.class_by_name[normalize(label)]
                for label in row.get("sections", [])
                if normalize(label) in index.class_by_name
            ]
            if not secs:
                continue
            kb_cat = task_to_kb_cat.get(tid)
            if kb_cat:
                self.kb_cat_task_secs[kb_cat].extend(secs)
                for a in row.get("aliases", []):
                    for w in skey(a).split():
                        if len(w) >= 3 and w not in PREPOSITIONS:
                            self.kb_cat_keywords[kb_cat].add(lemma(w))
                            if len(w) >= 5:
                                self.kb_cat_keywords[kb_cat].add(w[:5])
        if self.kb_cat_task_secs.get("home_antivirus"):
            self.kb_cat_task_secs["endpoint_security"].extend(self.kb_cat_task_secs["home_antivirus"])
        for cat_id, row in kb.rows["categories"].items():
            for label in (row.get("title_short"), *row.get("synonyms", []), *row.get("slang", [])):
                if isinstance(label, str):
                    for w in skey(label).split():
                        if len(w) >= 3 and w not in PREPOSITIONS:
                            self.kb_cat_keywords[cat_id].add(lemma(w))
                            if len(w) >= 5:
                                self.kb_cat_keywords[cat_id].add(w[:5])

        # Сленг из всех kb/slang*.yaml (включая slang_n5.yaml).
        for phrase, row in kb.rows["slang"].items():
            target = row.get("maps_to") or {}
            pk = skey(phrase)
            if not pk or len(pk) < 2:
                continue
            if pk.split()[0] in PREPOSITIONS:
                continue
            if "family" in target:
                fid = target["family"]
                cards = self.family_cards.get(fid, ())
                if cards:
                    add_entity(pk, "family", fid, self.family_canonical.get(fid, ""), cards, self.family_pop.get(fid, 3) + 1)
            elif "vendor" in target:
                feed_v = self.vendor_kb_to_feed.get(target["vendor"])
                if feed_v:
                    canon = self.vendor_canonical.get(feed_v, target["vendor"])
                    weight = 5 if self.vendor_offers.get(feed_v, 0) >= 100 else 3
                    add_entity(pk, "vendor", feed_v, canon, (), weight)
            elif "category" in target:
                # Категории относятся к разделам, а не к брендам (чтобы «мониторинг» не перебивал «монитор»).
                cat_id = target["category"]
                secs = tuple(dict.fromkeys(self.kb_cat_task_secs.get(cat_id, ())))
                if not secs:
                    cards = self.kb_cat_cards.get(cat_id, ())
                    secs = tuple(dict.fromkeys(index.card_sections[cid] for cid in cards[:12] if cid in index.card_sections))
                if secs:
                    add_section(pk, "kb_cat", secs, cat_id, 5)
            elif target.get("text") or target.get("query") or target.get("platform"):
                val = str(target.get("text") or target.get("query") or target.get("platform")).replace("_", " ")
                if "platform" in target and re.search(r"\d", pk) and not re.search(r"\d", val):
                    continue
                if target.get("platform") == "linux":
                    continue
                if target.get("platform") == "windows":
                    # Только явные написания Windows (не «ноут»/«ноутбук», у которых platform: windows).
                    if _is_win_term(pk):
                        add_entity(pk, "alias", pk, "windows", (), 5)
                else:
                    add_entity(pk, "alias", pk, val, (), 4)

        for phrase, val in index.aliases.items():
            pk = skey(phrase)
            if not pk or pk.split()[0] in PREPOSITIONS:
                continue
            if re.search(r"\d", pk) and not re.search(r"\d", val):
                continue
            if pk == "офис" or val == "linux":
                continue
            if val == "windows" and not _is_win_term(pk):
                continue
            add_entity(pk, "alias", pk, val, (), 4)

        self.entity_keys = sorted(self.entities)

        for tid, row in kb.rows["feed_tasks"].items():
            secs = [
                index.class_by_name[normalize(label)]
                for label in row.get("sections", [])
                if normalize(label) in index.class_by_name
            ]
            if not secs:
                continue
            kb_cat = task_to_kb_cat.get(tid)
            if kb_cat and not self.kb_cat_cards.get(kb_cat):
                kb_cat = None
            for alias in row.get("aliases", []):
                if skey(alias) in {"винда", "виндовс"}:
                    continue
                add_section(alias, "task", secs, kb_cat, 6)
            for phrase in row.get("phrases", []):
                add_section(phrase, "task_phrase", secs, kb_cat, 3)

        # Названия разделов фида и их очищенные хвосты.
        section_lead = re.compile(
            r"^(?:программное обеспечение для|программы для|системы|средства|решения для)\s+"
        )
        for sid, name in index.class_names.items():
            add_section(name, "section", (sid,), None, 5)
            nk = skey(name)
            tail = section_lead.sub("", nk).strip()
            if tail and tail != nk and len(tail) >= 4:
                add_section(tail, "section", (sid,), None, 4)
            if index.cat.cards[index.groups[sid][0]].offers[0].domain == "hardware":
                first_w = nk.split()[0] if nk else ""
                if len(first_w) >= 4:
                    add_section(lemma(first_w), "hardware", (sid,), None, 6)

        # Категории KB (синонимы и сленг) → секции фида + kb_cat_cards.
        for cat_id, row in kb.rows["categories"].items():
            secs = tuple(dict.fromkeys(self.kb_cat_task_secs.get(cat_id, ())))
            if not secs:
                cards = self.kb_cat_cards.get(cat_id, ())
                secs = tuple(dict.fromkeys(index.card_sections[cid] for cid in cards[:12] if cid in index.card_sections))
            if not secs:
                continue
            for label in (row.get("title_short"), *row.get("synonyms", []), *row.get("slang", [])):
                if isinstance(label, str) and len(label.strip()) >= 2:
                    lk = skey(label)
                    if lk in {"винда", "виндовс", "виндоус", "windows", "windows 10", "windows 11", "microsoft windows"}:
                        continue
                    add_section(lk, "kb_cat", secs, cat_id, 5)

        # Оборудование из index.hardware.
        for term, hw_row in index.hardware.items():
            secs = [str(k) for k in hw_row.get("hardware_feed_classes", []) if str(k) in index.groups]
            if secs:
                add_section(term, "hardware", secs, None, 6)

        self.section_keys = sorted(self.sections)

        # Алиасы, указывающие на раздел («антивирь» → «антивирус»), не должны маскироваться под бренд в entities.
        for pk in list(self.entities):
            kept = [e for e in self.entities[pk] if not (e[0] == "alias" and skey(e[2]) in self.sections)]
            if kept:
                self.entities[pk] = kept
            else:
                del self.entities[pk]
        self.entity_keys = sorted(self.entities)

        # Словарь для исправления опечаток и транслитерации.
        spell_words = set()
        self.roman_to_term = {}
        for pool in (self.entity_keys, self.section_keys):
            for phrase in pool:
                if " " not in phrase and len(phrase) >= 4 and phrase.isalpha():
                    spell_words.add(phrase)
                    if re.search("[а-я]", phrase):
                        r = roman(phrase)
                        self.roman_to_term.setdefault(r, phrase)
                        self.roman_to_term.setdefault(r.replace("i", "y"), phrase)
        self.high_value_words = frozenset(spell_words)
        for w, cids in index.postings.items():
            if len(w) >= 5 and w.isalpha() and len(cids) >= 2:
                spell_words.add(w)
        self.typo_match = typo_matcher(spell_words)
        self.roman_keys = sorted(self.roman_to_term)

        self._section_top_cache = {}
        self._vendor_cards_cache = {}

    def _vendor_products(self, feed_v, canon_name):
        """Порядок продуктов бренда — из FeedIndex.products и index.quality (совместимо с N3)."""
        cached = self._vendor_cards_cache.get(feed_v)
        if cached is not None:
            return cached
        index = self.index
        queries = []
        raw_v = self.vendor_raw.get(feed_v, "")
        for cand in (canon_name, raw_v):
            q = normalize(cand or "")
            if q and len(q) >= 2 and q not in queries:
                queries.append(q)

        best_hits = ()
        for q in queries:
            hits = index.products(q, fuzzy=False)
            if not hits:
                continue
            same_v = tuple(cid for cid in hits if index.card_vendors.get(cid) == feed_v)
            chosen = same_v if same_v else hits
            # Если каноническое латинское имя («Yandex») дало лишь 2 карточки, а русское имя вендора фида («Яндекс»)
            # даёт заметно больше карточек того же вендора (включая «Яндекс 360 для бизнеса»), берём более полный набор.
            if not best_hits or (len(best_hits) < 4 and len(chosen) > len(best_hits)):
                best_hits = chosen

        if len(best_hits) < 4:
            members = index.language.vendor_cards.get(feed_v, ())
            extra = sorted(
                (cid for cid in members if cid not in best_hits),
                key=lambda cid: (not self.is_aux[cid], not self.is_cal[cid], index.quality[cid], cid),
                reverse=True,
            )
            best_hits = tuple(list(best_hits) + extra)

        self._vendor_cards_cache[feed_v] = best_hits
        return best_hits

    def _diversify_by_vendor(self, ranked_cids, limit=12):
        """Не даёт одному вендору занять все 4 позиции в выдаче раздела/категории."""
        index = self.index
        first_pass = []
        overflow = []
        seen_v = set()
        seen_c = set()
        for cid in ranked_cids:
            if cid in seen_c:
                continue
            seen_c.add(cid)
            vid = index.card_vendors.get(cid) or cid
            if vid not in seen_v:
                seen_v.add(vid)
                first_pass.append(cid)
            else:
                overflow.append(cid)
        return (first_pass + overflow)[:limit]

    def _section_cards(self, secs, kb_cat=None, query_terms=()):
        key = (secs, kb_cat, tuple(sorted(query_terms)))
        if key in self._section_top_cache:
            return self._section_top_cache[key]
        index = self.index

        q_toks = tuple(t for t in query_terms if len(t) >= 3)
        q_lemmas = {lemma(t) for t in q_toks}

        # Для разделов оборудования добавляем ключевые слова самого раздела («принтер», «мфу», «монитор»),
        # чтобы при запросе «прин» / «принтер» карточки со словом «Принтер» / «МФУ» поднимались в топ.
        sec_head_lemmas = set()
        for s in secs[:2]:
            sname = index.class_names.get(s, "")
            if sname and index.groups.get(s) and index.cat.cards[index.groups[s][0]].offers[0].domain == "hardware":
                for w in skey(sname).split():
                    if len(w) >= 3 and w not in PREPOSITIONS:
                        sec_head_lemmas.add(lemma(w))

        def title_matches_query(cid):
            ttoks = self.title_toks[cid]
            if q_toks:
                for t in q_toks:
                    for w in ttoks:
                        if w.startswith(t) or lemma(w) in q_lemmas:
                            return True
            if sec_head_lemmas:
                for w in ttoks:
                    if lemma(w) in sec_head_lemmas:
                        return True
            return False

        sec_set = set(secs)
        primary_sec = secs[0] if secs else None
        candidates = []
        seen = set()

        if kb_cat and self.kb_cat_cards.get(kb_cat):
            kb_pool = [cid for cid in self.kb_cat_cards[kb_cat] if not self.is_aux[cid] and not self.is_cal[cid]]
            in_sec = [cid for cid in kb_pool if index.card_sections.get(cid) in sec_set]
            if len(in_sec) >= 3:
                kb_pool = in_sec
            kb_pool.sort(
                key=lambda cid: (
                    index.card_sections.get(cid) in sec_set,
                    index.card_sections.get(cid) == primary_sec or title_matches_query(cid),
                    self.card_pop.get(cid, 0),
                    index.quality[cid],
                    cid,
                ),
                reverse=True,
            )
            for cid in self._diversify_by_vendor(kb_pool, limit=12):
                if cid not in seen:
                    seen.add(cid)
                    candidates.append(cid)

        if len(candidates) < 8:
            pooled = []
            for s in secs:
                pooled.extend(index.groups.get(s, ()))
            cat_kws = self.kb_cat_keywords.get(kb_cat) if kb_cat else None
            # При доборе из широкой секции («Программы для защиты информации») для категории KB («эцп»)
            # берём только карточки, совпадающие с ключевыми словами категории.
            if cat_kws:
                kw_pooled = [
                    cid for cid in pooled
                    if not self.is_aux[cid] and not self.is_cal[cid]
                    and any(lemma(w) in cat_kws or (len(w) >= 5 and w[:5] in cat_kws) for w in self.title_toks[cid])
                ]
                if kw_pooled or len(candidates) >= 2:
                    pooled = kw_pooled
            if len(secs) > 1 or q_toks or sec_head_lemmas or cat_kws:
                pooled.sort(
                    key=lambda cid: (
                        not self.is_aux[cid],
                        not self.is_cal[cid],
                        title_matches_query(cid),
                        self.card_pop.get(cid, 0),
                        index.quality[cid],
                        cid,
                    ),
                    reverse=True,
                )
            for cid in self._diversify_by_vendor(pooled, limit=12):
                if cid not in seen:
                    seen.add(cid)
                    candidates.append(cid)
                    if len(candidates) >= 12:
                        break

        result = tuple(candidates)
        self._section_top_cache[key] = result
        return result

    def _prefix_slice(self, sorted_keys, q, limit=64):
        lo = bisect_left(sorted_keys, q)
        hi = bisect_right(sorted_keys, q + "\U0010ffff")
        return lo, min(hi, lo + limit)

    def _title_prefix_hits(self, q, limit=80):
        lo = bisect_left(self.title_keys, q)
        hi = bisect_right(self.title_keys, q + "\U0010ffff")
        if lo == hi:
            return ()
        cids = []
        seen = set()
        for i in range(lo, hi):
            _, cid, _ = self.title_rows[i]
            if cid not in seen:
                seen.add(cid)
                cids.append(cid)
        return self._rank_product_hits(cids, q)[:limit]

    def _token_prefix_hits(self, q, limit=40):
        """Поиск карточек по всем словам ввода, где последнее слово — префикс."""
        index = self.index
        toks = q.split()
        if not toks:
            return ()
        pools = []
        for idx, tok in enumerate(toks):
            if tok in STOP and len(toks) > 1:
                continue
            is_last = idx == len(toks) - 1
            pool = set(index.postings.get(lemma(tok), ())) | set(index.raw_terms.get(tok, ()))
            if is_last:
                lo = bisect_left(index.prefix_vocab, tok)
                hi = bisect_right(index.prefix_vocab, tok + "\U0010ffff")
                for w in index.prefix_vocab[lo:min(hi, lo + 250)]:
                    pool.update(index.raw_terms[w])
            if not pool:
                return ()
            pools.append(pool)
        if not pools:
            return ()
        ids = set.intersection(*pools)
        if not ids:
            return ()
        return self._rank_product_hits(ids, q)[:limit]

    def _rank_product_hits(self, cids, q):
        index = self.index
        q_toks = q.split()
        want_cal = "cal" in q_toks
        want_mac = any(t.startswith("mac") or t == "мак" for t in q_toks)
        last = q_toks[-1] if q_toks else ""
        head_toks = tuple(q_toks[:-1])
        head_lemmas = {lemma(t) for t in head_toks if t not in STOP}

        def score(cid):
            tk = self.title_k[cid]
            ck = self.clean_k[cid]
            ctoks = self.clean_toks[cid]
            ttoks = self.title_toks[cid]
            exact = (ck == q) or (tk == q)
            word_start = exact or ck.startswith(q + " ") or tk.startswith(q + " ")
            contig_prefix = word_start or ck.startswith(q) or tk.startswith(q)
            first_word_exact = bool(q_toks and (ctoks[:1] == (q_toks[0],) or ttoks[:1] == (q_toks[0],)))
            first_word_prefix = bool(q_toks and (
                (ctoks and ctoks[0].startswith(q_toks[0])) or (ttoks and ttoks[0].startswith(q_toks[0]))
            ))
            aux_ok = not self.is_aux[cid]
            cal_ok = want_cal or not self.is_cal[cid]
            mac_ok = want_mac or not self.is_mac_only[cid]
            head_in_title = not head_lemmas or head_lemmas <= {lemma(w) for w in ttoks}
            last_whole = bool(last and (last in ctoks or last in ttoks))
            kb_pop = self.card_pop.get(cid, 0)
            return (
                exact,
                contig_prefix and aux_ok and cal_ok and mac_ok,
                word_start and aux_ok and cal_ok and mac_ok,
                aux_ok,
                cal_ok,
                mac_ok,
                first_word_exact,
                first_word_prefix,
                head_in_title,
                last_whole,
                kb_pop,
                index.quality[cid],
                cid,
            )

        return tuple(sorted(cids, key=score, reverse=True))

    def _resolve_entity_entry(self, entry):
        kind, ident, target, cards, weight = entry
        if kind in {"family", "kb_cat"}:
            return cards
        if kind == "vendor":
            return self._vendor_products(ident, target)
        if kind == "alias":
            tk = skey(target)
            if not tk:
                return ()
            hits = self.index.products(tk, fuzzy=False)
            if hits:
                want_cal = "cal" in tk.split()
                if not want_cal:
                    non_cal = tuple(cid for cid in hits if not self.is_cal[cid] and not self.is_aux[cid])
                    if non_cal:
                        return non_cal
                return hits
            return self._title_prefix_hits(tk, 16)
        return ()

    def _match_entities(self, q):
        """Точные и префиксные совпадения по брендам, семействам и сленгу."""
        exact_entries = self.entities.get(q, ())
        prefix_entries = []
        if len(q) >= 2:
            lo, hi = self._prefix_slice(self.entity_keys, q, limit=48)
            for phrase in self.entity_keys[lo:hi]:
                if phrase == q:
                    continue
                if len(q) == 2 and (len(phrase) == 3 or (" " in phrase and not phrase.startswith(q + " "))):
                    continue
                for entry in self.entities[phrase]:
                    prefix_entries.append((phrase, entry))
        return exact_entries, prefix_entries

    def _match_sections(self, q):
        """Точные и префиксные совпадения по разделам, задачам и оборудованию."""
        exact_entries = self.sections.get(q, ())
        prefix_entries = []
        if len(q) >= 2:
            lo, hi = self._prefix_slice(self.section_keys, q, limit=48)
            for phrase in self.section_keys[lo:hi]:
                if phrase == q:
                    continue
                if len(q) == 2 and len(phrase) == 3:
                    continue
                for entry in self.sections[phrase]:
                    prefix_entries.append((phrase, entry))
        return exact_entries, prefix_entries

    def _section_with_qualifier(self, q):
        """Раздел или оборудование + уточнение: «ноутбук len», «монитор 27», «мышь log», «принтер hp»."""
        toks = q.split()
        if len(toks) < 2:
            return None
        index = self.index
        for split_at in range(min(3, len(toks) - 1), 0, -1):
            head = " ".join(toks[:split_at])
            tail = " ".join(toks[split_at:])
            if not tail or tail in PREPOSITIONS:
                continue
            secs = []
            hw_row = index.hardware.get(head) or index.hardware.get(lemma(head))
            if hw_row:
                secs.extend(str(k) for k in hw_row.get("hardware_feed_classes", []) if str(k) in index.groups)
            if not secs:
                for entry in self.sections.get(head, ()) or self.sections.get(lemma(head), ()):
                    if entry[0] in {"hardware", "section", "task", "kb_cat"}:
                        secs.extend(entry[1])
            if not secs:
                cm = index.class_match(head)
                if cm:
                    secs.append(cm)
            secs = tuple(dict.fromkeys(secs))
            if not secs:
                continue
            pool = []
            for s in secs:
                pool.extend(index.groups.get(s, ()))
            if not pool:
                continue
            pool_set = set(pool)

            tail_toks = tail.split()
            matched = []
            tail_entity_cards = set()
            exact_e, pref_e = self._match_entities(tail)
            for entry in exact_e:
                tail_entity_cards.update(self._resolve_entity_entry(entry))
            if not tail_entity_cards:
                for _, entry in pref_e[:8]:
                    tail_entity_cards.update(self._resolve_entity_entry(entry))
            tail_entity_cards &= pool_set

            for cid in pool:
                if cid in tail_entity_cards:
                    matched.append(cid)
                    continue
                hay = self.title_k[cid] + " " + skey(index.cat.cards[cid].offers[0].vendor or "")
                hay_toks = hay.split()
                ok = True
                for i, t in enumerate(tail_toks):
                    if t in STOP and len(tail_toks) > 1:
                        continue
                    if i == len(tail_toks) - 1:
                        if not any(w.startswith(t) for w in hay_toks):
                            ok = False
                            break
                    else:
                        if t not in hay_toks and lemma(t) not in {lemma(w) for w in hay_toks}:
                            ok = False
                            break
                if ok:
                    matched.append(cid)
            if matched:
                ranked = sorted(
                    matched,
                    key=lambda cid: (
                        not self.is_aux[cid],
                        all(t in self.title_toks[cid] for t in tail_toks),
                        any(w.startswith(tail_toks[-1]) for w in self.title_toks[cid]),
                        index.quality[cid],
                        cid,
                    ),
                    reverse=True,
                )
                return tuple(ranked[:4]), secs
        return None

    def _strip_modifiers(self, q):
        """Убираем служебные слова, количество, срок и висячий предлог для толкования."""
        text = SERVICE_LEAD.sub("", q).strip()
        text = SERVICE_TAIL.sub("", text).strip()
        text, _, _ = split_conditions(text)
        text = DURATION.sub(" ", text)
        text = " ".join(text.split())
        text = SERVICE_LEAD.sub("", text).strip()
        text = SERVICE_TAIL.sub("", text).strip()
        text = TRAILING_PREP.sub("", text).strip()
        return text or q

    def interpret(self, engine, q):
        """Единый конвейер толкования без исправления опечаток.

        Возвращает (kind, ids, sections, extra_dict) или None.
        """
        index = self.index
        if not q or len(q) < 2 or q in {"про", "pro"}:
            return None

        # 1. Явная редакция продукта (test_m3j.py: «винда хоум», «офис про 2021», «касперский плюс»).
        edition = index.edition(q)
        if edition:
            return ("edition", tuple(edition.cards[:4]), (), dict(edition=edition))

        # 2. Снятый или отсутствующий продукт → аналоги в каталоге (test_m3h.py).
        # Если ввод является компонентом или написанием семейства, которое ЕСТЬ в каталоге
        # («ворд»/«эксель» → Microsoft Office, «постгрес» → Postgres Pro), показываем само семейство.
        has_catalog_family = any(e[0] == "family" and e[3] for e in self.entities.get(q, ()))
        if not has_catalog_family:
            row = index.analogs.lookup(q)
            if row and not row["in_catalog"]:
                sections, seeds = feed_analogs.row_candidates(index, row)
                choices = feed_analogs.choose(index, q, row, sections, seeds, [], False)
                if choices:
                    return ("analogs", tuple(cid for cid, _ in choices[:3]), (), {})
                return ("analogs_empty", (), (), {})

        # 3. Запрос по программе лицензирования или метрике («oem», «лицензия на пользователя»).
        lic_filter = license_request(engine, q)
        if lic_filter:
            lic_hits = index.license_offers.get(lic_filter, {})
            if lic_hits:
                ids = tuple(sorted(lic_hits, key=index.quality.get, reverse=True)[:4])
                return ("license", ids, (), dict(license_hits=lic_hits))

        # 4. Убираем служебные слова, тираж и срок.
        q_clean = self._strip_modifiers(q)
        if q_clean != q:
            edition2 = index.edition(q_clean)
            if edition2:
                return ("edition", tuple(edition2.cards[:4]), (), dict(edition=edition2))

        res = self._interpret_core(engine, q_clean)
        if res is not None:
            return res

        # 5. Если ввод содержит отдельное число («кас 10»), которое не совпало с версией/размером,
        # убираем число и толкуем оставшуюся часть.
        toks = q_clean.split()
        if len(toks) >= 2 and any(t.isdigit() for t in toks):
            no_num = " ".join(t for t in toks if not t.isdigit()).strip()
            no_num = TRAILING_PREP.sub("", no_num).strip()
            if no_num and len(no_num) >= 2 and no_num != q_clean:
                return self._interpret_core(engine, no_num)
        return None

    def _interpret_core(self, engine, q):
        index = self.index
        if not q or len(q) < 2:
            return None

        # A. Точное совпадение оборудования («комп», «принтак», «свитч», «ноут», «принтер»).
        hw_key = hardware_head(index, q)
        if hw_key and hw_key in index.hardware and " " not in q:
            secs = tuple(str(k) for k in index.hardware[hw_key].get("hardware_feed_classes", []) if str(k) in index.groups)
            if secs:
                # Порядок тот же, что в выдаче: первая подсказка совпадает с первой карточкой поиска.
                members = rank_hardware_section(index, secs[0], q, list(index.groups[secs[0]]))
                return ("section", tuple(members[:4]), secs, {})

        # B. Точный запрос задачи/цели (PURPOSES / TASKS / feed_tasks / вопросы вроде «что от вирусов»).
        if HOME.search(q) and "антивир" in q:
            home_sec = index.class_by_name.get("антивирусы для дома")
            if home_sec:
                return ("section", tuple(index.groups[home_sec][:4]), (home_sec,), {})

        hint = next((label for pattern, label in (*PURPOSES, *TASKS) if re.search(pattern, q)), None)
        task_sec = index.task_class(q)
        is_question = bool(HELP.search(q) or QUESTION.search(q) or any(w.endswith(("ть", "ться")) for w in words(q)))
        if hint and (len(words(q)) > 1 or re.fullmatch(r"антивир\w*", q)):
            target_sec = index.class_by_name.get(normalize(hint)) or index.class_match(hint)
            if target_sec:
                return ("section", tuple(index.groups[target_sec][:4]), (target_sec,), {})
        if task_sec and len(words(q)) > 1:
            return ("section", tuple(index.groups[task_sec][:4]), (task_sec,), {})

        # C. Раздел/оборудование с уточнением («ноутбук len», «монитор 27», «мышь log», «принтер hp»).
        qualified = self._section_with_qualifier(q)
        if qualified:
            ids, secs = qualified
            return ("section_qualified", ids, secs, {})

        # D. Кандидаты по убыванию силы:
        #    1) точное начало названия линейки/продукта;
        #    2) бренд / семейство / русские написания (entities);
        #    3) раздел / синонимы / задачи / оборудование (sections);
        #    4) совпадение слов в названии (token_prefix).
        title_hits = self._title_prefix_hits(q, limit=24)
        exact_entities, pref_entities = self._match_entities(q)
        exact_sections, pref_sections = self._match_sections(q)

        strong_title = [
            cid for cid in title_hits
            if not self.is_aux[cid] and (self.clean_k[cid].startswith(q) or self.title_k[cid].startswith(q))
        ]
        # Для многословного запроса («dr web sec», «windows 11 p», «windows 10», «kaspersky st», «microsoft off»):
        if " " in q and strong_title:
            return ("title", tuple(strong_title[:4]), (), {})

        # Точное совпадение сущности (семейство/бренд/алиас: «постгрес», «ворд», «эксель»,
        # «фотошоп», «автокад», «нанокад», «виндовс», «касп», «каспер», «касперский», «win», «яндекс»).
        if exact_entities:
            kind_prio = {"family": 4, "vendor": 3, "alias": 1}
            ordered_e = sorted(exact_entities, key=lambda e: (kind_prio.get(e[0], 0), e[4]), reverse=True)
            best_e = ordered_e[0]
            e_cards = self._resolve_entity_entry(best_e)
            if e_cards:
                # Точное совпадение целого слова в начале названия продукта («office» → Microsoft Office),
                # но НЕ подстроки другого слова («win» ≠ «wine@etersoft»!).
                whole_word_titles = [
                    c for c in strong_title
                    if self.clean_k[c] == q or self.title_k[c] == q
                    or self.clean_k[c].startswith(q + " ") or self.title_k[c].startswith(q + " ")
                ]
                if whole_word_titles and best_e[0] != "vendor" and not any(
                    self.clean_k[c] == q or self.title_k[c] == q for c in e_cards[:2]
                ):
                    exact_titles = [c for c in whole_word_titles if self.clean_k[c] == q or self.title_k[c] == q]
                    if exact_titles:
                        merged = tuple(dict.fromkeys([*exact_titles, *e_cards]))[:4]
                        return ("entity", merged, (), {})
                if whole_word_titles and best_e[0] == "alias" and any(self.card_pop.get(c, 0) >= 4 for c in whole_word_titles[:2]):
                    merged = tuple(dict.fromkeys([*whole_word_titles[:4], *e_cards[:4]]))[:4]
                    return ("title", merged, (), {})
                return ("entity", tuple(e_cards[:4]), (), {})

        # Точное совпадение раздела / задачи / категории («антивирус», «впн», «эцп», «линукс», «офис», «офисный пакет»,
        # «бэкап», «сапр», «кресло», «антивирус для дома»).
        if exact_sections:
            exact_prod = [
                c for c in strong_title
                if self.clean_k[c] == q or self.title_k[c] == q
                or (self.clean_k[c].startswith(q + " ") and self.card_pop.get(c, 0) >= 4)
            ]
            if not exact_prod:
                best_s = max(exact_sections, key=lambda s: (s[2] is not None, s[3], len(s[1])))
                cards = self._section_cards(best_s[1], best_s[2], q.split())
                if cards:
                    return ("section", tuple(cards[:4]), best_s[1], {})

        # Префиксные совпадения: выбираем лучшую сущность и лучший раздел/оборудование.
        best_pref_entity = None
        if pref_entities:
            def entity_rank(item):
                phrase, entry = item
                kind, ident, target, cards, weight = entry
                cards_resolved = cards if cards else (
                    self._vendor_products(ident, target) if kind == "vendor" else ()
                )
                if not cards_resolved and kind == "alias":
                    cards_resolved = self._resolve_entity_entry(entry)
                if not cards_resolved:
                    return (-1,)
                top_cid = cards_resolved[0]
                is_single_word = " " not in phrase
                offers = self.vendor_offers.get(ident, 0) if kind == "vendor" else len(index.cat.cards[top_cid].offers)
                pop = weight + (2 if self.card_pop.get(top_cid, 0) >= 4 else 0)
                return (
                    1,
                    is_single_word,
                    kind in {"family", "vendor", "alias"},
                    pop,
                    offers,
                    -len(phrase),
                    phrase,
                )

            ranked_pe = sorted(pref_entities, key=entity_rank, reverse=True)
            top_pe = ranked_pe[0]
            if entity_rank(top_pe)[0] > 0:
                best_pref_entity = (top_pe[0], top_pe[1], self._resolve_entity_entry(top_pe[1]))

        best_pref_section = None
        if pref_sections:
            def sec_rank(item):
                phrase, entry = item
                kind, secs, kb_cat, weight = entry
                is_hw_or_sec = kind in {"hardware", "section", "task", "kb_cat"}
                first_word_match = phrase.split()[0].startswith(q) if " " not in q else phrase.startswith(q)
                is_single = " " not in phrase
                prefer_single = is_single if " " not in q else False
                return (
                    is_hw_or_sec,
                    first_word_match,
                    prefer_single,
                    weight,
                    -len(phrase),
                    kb_cat is not None,
                    phrase,
                )

            ranked_ps = sorted(pref_sections, key=sec_rank, reverse=True)
            top_ps = ranked_ps[0]
            s_cards = self._section_cards(top_ps[1][1], top_ps[1][2], q.split())
            if s_cards:
                best_pref_section = (top_ps[0], top_ps[1], s_cards)

        # Решаем, кто сильнее: точное начало продукта, префикс бренда/семейства или префикс раздела/оборудования.
        if strong_title:
            top_t = strong_title[0]
            top_t_pop = self.card_pop.get(top_t, 0)
            top_t_offers = len(index.cat.cards[top_t].offers)
            top_t_domain = index.cat.cards[top_t].offers[0].domain
            has_raw_title_start = any(self.title_k[c].startswith(q) for c in strong_title[:4])

            # 1) Бренд / семейство по префиксу (проверяем ДО раздела: «авток» → AutoCAD, «фотош» → Photoshop,
            #    «micr» → Microsoft, «autoc» → AutoCAD, «винд» → Windows).
            if best_pref_entity:
                pe_phrase, pe_entry, pe_cards = best_pref_entity
                if pe_cards:
                    pe_top = pe_cards[0]
                    pe_pop = self.card_pop.get(pe_top, 0)
                    pe_offers = len(index.cat.cards[pe_top].offers)
                    if pe_entry[0] == "vendor" and self.vendor_offers.get(pe_entry[1], 0) >= 200 and pe_phrase.startswith(q):
                        v_cards = [c for c in strong_title if index.card_vendors.get(c) == pe_entry[1]]
                        merged = tuple(dict.fromkeys([*v_cards, *pe_cards]))[:4]
                        return ("entity", merged, (), {})
                    if pe_entry[0] in {"family", "alias"} and (
                        (pe_pop >= 4 and top_t_pop < 4)
                        or (pe_entry[0] == "family" and pe_offers > top_t_offers * 2 and top_t_pop < 4)
                    ):
                        return ("entity", tuple(pe_cards[:4]), (), {})
                    if pe_entry[0] == "family" and any(c in pe_cards for c in strong_title[:8]):
                        merged = tuple(dict.fromkeys([*pe_cards[:4], *strong_title[:4]]))[:4]
                        return ("entity", merged, (), {})

            # 2) Раздел / оборудование по префиксу («антив», «резерв», «клав», «мони», «прин», «оф»).
            if best_pref_section:
                ps_phrase, ps_entry, ps_cards = best_pref_section
                ps_kind = ps_entry[0]
                if ps_kind == "hardware" and (top_t_domain != "hardware" or top_t_pop < 4):
                    return ("section", tuple(ps_cards[:4]), ps_entry[1], {})
                if ps_kind in {"section", "task", "kb_cat"} and ps_entry[2] is not None:
                    if (top_t_pop < 4 and top_t_offers < 30) or (len(q) <= 3 and not has_raw_title_start):
                        return ("section", tuple(ps_cards[:4]), ps_entry[1], {})

            return ("title", tuple(strong_title[:4]), (), {})

        # Если нет совпадения по началу названия карточки — выбираем между префиксом сущности и раздела.
        if best_pref_entity and best_pref_section:
            pe_phrase, pe_entry, pe_cards = best_pref_entity
            ps_phrase, ps_entry, ps_cards = best_pref_section
            pe_single = " " not in pe_phrase
            ps_single = " " not in ps_phrase
            # Раздел побеждает, если это короткий/однословный раздел («антив» → антивирус, «мони» → монитор),
            # а не длинная составная фраза вроде «кассовое оборудование» против короткого бренда «касп».
            if ps_entry[0] in {"hardware", "task", "section", "kb_cat"} and ps_phrase.split()[0].startswith(q):
                if pe_entry[0] not in {"family", "vendor", "alias"}:
                    return ("section", tuple(ps_cards[:4]), ps_entry[1], {})
                if ps_single and (not pe_single or len(ps_phrase) <= len(pe_phrase)) and pe_entry[4] <= ps_entry[3]:
                    return ("section", tuple(ps_cards[:4]), ps_entry[1], {})
            return ("entity", tuple(pe_cards[:4]), (), {})

        if best_pref_entity:
            return ("entity", tuple(best_pref_entity[2][:4]), (), {})

        if best_pref_section:
            return ("section", tuple(best_pref_section[2][:4]), best_pref_section[1][1], {})

        # E. Поиск по словам/префиксу в любом месте названия («office 2021», «pdf», «почт», «1с», «битрикс»).
        tok_hits = self._token_prefix_hits(q, limit=12)
        non_aux = [cid for cid in tok_hits if not self.is_aux[cid]]
        if non_aux:
            return ("tokens", tuple(non_aux[:4]), (), {})
        if tok_hits:
            return ("tokens", tuple(tok_hits[:4]), (), {})

        # F. Вопросительная задача (только если ничего выше не подошло).
        if is_question and len(words(q)) >= 2:
            options, focus, _, _ = task_sections(engine, q, hint)
            sec = next(iter(options), None)
            if sec:
                ids = tuple(dict.fromkeys([*(i for i in focus if index.card_sections[i] == sec), *index.groups[sec]]))[:4]
                if ids:
                    return ("task", ids, (sec,), {})

        return None

    def repair_query(self, raw, norm):
        """Кандидаты исправления ввода: раскладка → транслитерация → опечатка."""
        candidates = []

        # 1. Раскладка клавиатуры (на сыром вводе до удаления пунктуации, чтобы сохранить ,.;'[]).
        layout = skey(normalize(raw).translate(LAYOUT))
        if layout and layout != norm and len(layout) >= 2:
            candidates.append(layout)

        # 2. Транслитерация латиница↔кириллица по известным терминам и звучанию.
        toks = norm.split()
        if toks:
            if len(toks) == 1 and re.fullmatch("[a-z]{3,}", norm):
                if norm in self.roman_to_term:
                    candidates.append(self.roman_to_term[norm])
                else:
                    lo = bisect_left(self.roman_keys, norm)
                    if lo < len(self.roman_keys) and self.roman_keys[lo].startswith(norm):
                        candidates.append(self.roman_to_term[self.roman_keys[lo]])
            if any(re.fullmatch("[а-я]{4,}", t) for t in toks):
                _, sound_q = self.index.sound_products(norm)
                sk = skey(sound_q)
                if sk and sk != norm:
                    candidates.append(sk)

        # 3. Опечатки (Дамерау-Левенштейн по словарю сущностей, разделов и частых слов).
        if toks:
            repaired_toks = []
            changed = False
            for t in toks:
                if len(t) < 4 or not t.isalpha():
                    repaired_toks.append(t)
                    continue
                if t in self.entities or t in self.sections or t in self.index.postings or t in STOP:
                    repaired_toks.append(t)
                    continue
                dist = 1 if len(t) < 8 else 2
                matches = self.typo_match(t, 8, dist)
                best = None
                best_key = None
                for word, d, _ in matches:
                    if not _same_script(t, word):
                        continue
                    if len(t) == 4 and (word not in self.high_value_words or word[0] != t[0] or d > 1):
                        continue
                    if d == 2 and len(word) < 6:
                        continue
                    rank = (
                        -d,
                        word in self.high_value_words,
                        word[0] == t[0],
                        len(self.index.postings.get(word, ())),
                        -len(word),
                    )
                    if best_key is None or rank > best_key:
                        best_key = rank
                        best = word
                if best and best != t:
                    repaired_toks.append(best)
                    changed = True
                else:
                    repaired_toks.append(t)
            if changed:
                cand = " ".join(repaired_toks)
                if cand != norm:
                    candidates.append(cand)

        return tuple(dict.fromkeys(candidates))


def suggestions(engine, raw, norm, profile, start):
    """Точка входа подсказок для фида: один путь для любого ввода."""
    index = engine.catalog.feed
    fs = getattr(engine.suggestions, "feed_suggest", None)
    if fs is None:
        fs = FeedSuggestIndex(index, engine.kb, getattr(engine, "lex", None))
        if hasattr(engine, "suggestions"):
            engine.suggestions.feed_suggest = fs

    def entry(cid, preferred=None):
        c = display(engine, cid, profile, preferred)
        return dict(
            text=c["title"],
            kind="product",
            meta=cid,
            card_id=cid,
            picture=c["picture"],
            image=c["picture"],
            oldprice=c["offer"]["oldprice"],
            price=c["offer"]["price"],
            price_on_request=c["offer"]["price_on_request"],
            badges=c["badges"],
            q=c["title"],
        )

    if not norm or len(norm) < 2 or norm in {"про", "pro"}:
        return dict(q=raw, corrected=None, groups=[], ms=round((perf_counter() - start) * 1000, 2))

    # Единый путь: сначала прямое толкование; если пусто — исправление и ТО ЖЕ толкование.
    corrected = None
    result = fs.interpret(engine, norm)
    if result is None:
        for cand in fs.repair_query(raw, norm):
            trial = fs.interpret(engine, cand)
            if trial is not None:
                result = trial
                corrected = cand
                break

    groups = []
    if result is None:
        return dict(q=raw, corrected=None, groups=[], ms=round((perf_counter() - start) * 1000, 2))

    kind, ids, matched_secs, extra = result

    # Отсутствующий товар → аналоги в каталоге.
    if kind in {"analogs", "analogs_empty"}:
        if ids:
            groups.append(dict(
                type="analogs",
                title="Аналоги в каталоге",
                items=[entry(cid) for cid in ids],
            ))
        return dict(q=raw, corrected=corrected, groups=groups, ms=round((perf_counter() - start) * 1000, 2))

    # Дедупликация карточек на весь ответ.
    ids = tuple(dict.fromkeys(ids))[:4]
    used_cards = set(ids)

    if corrected and corrected != norm:
        groups.append(dict(
            type="corrections",
            title="Возможно, вы искали",
            items=[dict(text=corrected, q=corrected, kind="correction", meta="repair")],
        ))

    license_hits = extra.get("license_hits") or {}
    if ids:
        groups.append(dict(
            type="products",
            title="Товары",
            items=[entry(cid, license_hits.get(cid)) for cid in ids],
        ))

    # Разделы строго соответствуют показанным карточкам (гарантия test_m3b.py).
    card_secs = list(dict.fromkeys(index.card_sections[cid] for cid in ids if cid in index.card_sections))
    if matched_secs:
        ordered_secs = [s for s in matched_secs if s in card_secs] + [s for s in card_secs if s not in matched_secs]
    else:
        ordered_secs = card_secs
    matching = [(k, index.classes[k]) for k in ordered_secs[:3] if k in index.classes]
    if matching:
        groups.append(dict(
            type="categories",
            title="Разделы",
            items=[dict(text=v, q=v, meta=k, kind="category") for k, v in matching],
        ))

    # Продолжения поисковых запросов.
    q_for_queries = corrected or norm
    previous = engine.suggestions.prefix(q_for_queries, profile.segment, set())
    groups.extend(g for g in previous if g["type"] == "queries")

    # Сопутствующие товары без повторов карточек из основной группы.
    edition = extra.get("edition")
    upsell_q = edition.query if edition else q_for_queries
    picks = index.recommend.picks(
        engine.journal,
        upsell_q,
        list(ids),
        4,
        edition_audience=edition.audience if edition else None,
    )
    unique_picks = []
    for cid, rule in picks:
        if cid in used_cards:
            continue
        used_cards.add(cid)
        unique_picks.append((cid, rule))
        if len(unique_picks) >= 2:
            break
    if unique_picks:
        groups.append(dict(
            type="upsell",
            title="Возможно, вам понадобится",
            items=[
                dict(
                    entry(
                        cid,
                        index.recommend.target_offer(cid, rule["offer"]["audience"])
                        if rule["offer"].get("audience")
                        else None,
                    ),
                    reason=rule["reason"],
                    rule_id=rule["id"],
                )
                for cid, rule in unique_picks
            ],
        ))

    return dict(
        q=raw,
        corrected=corrected if corrected and corrected != norm else None,
        groups=groups,
        ms=round((perf_counter() - start) * 1000, 2),
    )
