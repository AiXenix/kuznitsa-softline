"""Рекомендации магазина, привязанные к продаваемым карточкам."""
from collections import defaultdict
from hashlib import blake2s
from random import Random
import re
from kuznitsa.text import normalize
from kuznitsa.kb.upsell import query_matches
from kuznitsa.optional import optional_module


def audience_values(value):
    return value if isinstance(value,list) else [value]


def title_words(name):
    return " ".join(re.findall(r"\w+",name.casefold().replace("ё","е")))


def audience(text):
    home=re.search(r"\b(?:для дома|домашн\w*|для семьи|домой|home|family|personal)\b",text,re.I)
    business=re.search(r"\b(?:организаци\w*|корпоративн\w*|бизнес\w*|business|enterprise|corporate|small office)\b",text,re.I)
    if home and not business:return "home"
    if business and not home:return "business"
    return None


class Recommendations:
    def __init__(self,index,kb,cfg):
        self.index=index
        self.base=list(kb.upsell.values())
        self.legacy=[]
        aliases=defaultdict(set)
        index.line_popularity={}
        for fid,row in kb.rows["families"].items():
            for name in (row.get("name"),row.get("title"),*row.get("aliases",[])[:3]):
                if name:
                    matches=index.products(name.lower())
                    if matches:
                        # Связь с семейством требует полного названия линейки.
                        phrase=normalize(name)
                        confirmed=[]
                        for cid in matches[:16]:
                            title=normalize(index.cat.cards[cid].title).removeprefix("программа ")
                            if title!=phrase and not title.startswith(phrase+" "):continue
                            confirmed.append(cid)
                            canonical=normalize(row["name"]).partition(" (")[0]
                            if phrase==canonical:
                                # Основное название, затем версия без обозначения дополнительного модуля.
                                tail=title[len(phrase):].strip()
                                rank=(row.get("popularity") or 0,not tail or bool(re.fullmatch(r"[v\d. -]+",tail)),
                                      -len(tail),index.quality[cid])
                                index.line_popularity[cid]=max(rank,index.line_popularity.get(cid,rank))
                        if confirmed:
                            aliases[fid].update(confirmed)
                            break
        for fid,members in aliases.items():
            index.tags["families"][fid].update(members)
            category=kb.rows["families"][fid].get("category")
            if category:index.tags["classes"][category].update(members)
        for rule in kb.rows["crosssell"].values():
            for item in rule["suggest"]:
                self.legacy.append(dict(id=rule["id"],weight=.4,when=rule["when"],
                    offer=(dict(families=item["families"]) if any(f in aliases for f in item.get("families",[])) else dict(classes=[item.get("category")])),reason=item["reason"]))
        # Индекс явных зависимостей «для X» / «for X». Класс основной
        # покупки отличает конкурирующую программу от сопутствующего оборудования.
        owners=defaultdict(set)
        for c in index.cat.cards.values():
            o=c.offers[0]
            vendor=normalize(o.vendor or "")
            if o.domain!="software" or not vendor:continue
            classes={c.category,o.class_id,o.attrs.get("kb_category")}-{None}
            for name in (vendor,normalize(c.title)):
                owners[name].update((vendor,k) for k in classes)
        for family in kb.rows["families"].values():
            vendor=kb.rows["vendors"].get(family.get("vendor"),{})
            name=normalize(vendor.get("name") or "")
            if name and family.get("category"):
                for alias in [family["name"].partition("(")[0],*family.get("aliases",[])]:
                    if alias:owners[normalize(alias)].add((name,family["category"]))
        self.bindings={}
        for cid,c in index.cat.cards.items():
            bound=set()
            title=normalize(c.title)
            for suffix in re.split(r"\b(?:для|for)\s+",title)[1:]:
                parts=suffix.split()
                for n in range(len(parts),0,-1):
                    found=owners.get(" ".join(parts[:n]))
                    if found:
                        bound.update(found)
                        break
            if not bound:
                # В названии модуля встречается полное имя сторонней платформы и без предлога.
                terms=title.split()
                own=normalize(c.offers[0].vendor or "")
                for start in range(1,len(terms)):
                    for end in range(min(len(terms),start+5),start+1,-1):
                        found=owners.get(" ".join(terms[start:end]))
                        if found and all(v!=own for v,_ in found):
                            bound.update(found)
                            break
            if bound:self.bindings[cid]=bound
        self.family_names=defaultdict(list)
        self.family_ids=defaultdict(set)
        for cid,card in index.cat.cards.items():
            title=title_words(card.title).removeprefix("программа ")
            vendor=title_words(card.offers[0].vendor or "")
            # В карточке может стоять короткое имя издателя, в поле vendor — юридическое.
            publisher_words=set(vendor.split())
            tail=title.split()
            while len(tail)>1 and tail[0] in publisher_words:
                tail=tail[1:]
            for name in {title,title.removeprefix(vendor+" ")," ".join(tail)}:
                if name:self.family_names[name.partition(" ")[0]].append((name+" ",cid))
            for key in (card.family,card.offers[0].group_id):
                if key:self.family_ids[str(key).casefold()].add(cid)
        for key,members in aliases.items():
            self.family_ids[key].update(members)
        self.provider=optional_module("kuznitsa.analytics.upsell_rules")
        self.version=None
        self.compiled=self.compile(self.base or [])

    def card_audience(self,cid):
        section=self.index.card_sections[cid]
        label=audience(self.index.classes[section])
        # Корпоративная мобильная защита и администрирование устройств в дереве магазина.
        if section in {"121467","5984"}:return "business"
        return label or audience(self.index.cat.cards[cid].title)

    def target_offer(self,cid,expected,price_max=None,*,confirmed=False):
        card=self.index.cat.cards[cid]
        label=self.card_audience(cid)
        expected=audience_values(expected) if expected else []
        if expected and label and label not in expected:return None
        unknown=None
        for o in card.offers:
            if price_max is not None and (o.price is None or o.price>price_max):continue
            if not expected:return o
            if o.lic.audience and o.lic.audience not in expected:continue
            actual=audience(o.name) or label or o.lic.audience
            if actual in expected:return o
            if actual is None and unknown is None:unknown=o
        return None if confirmed else unknown

    def members(self,selectors,anchor=False):
        sets=[]
        for k in ("classes","categories","families","vendors"):
            if selectors.get(k):
                if k=="families" and (selectors.get("strict") or anchor):
                    named=set()
                    for label in selectors[k]:
                        key=str(label).casefold()
                        named.update(self.family_ids.get(key,()))
                        if anchor:named.update(self.index.tags["families"].get(key,()))
                        phrase=title_words(str(label))
                        if phrase:
                            named.update(cid for name,cid in self.family_names.get(phrase.partition(" ")[0],())
                                         if name.startswith(phrase+" "))
                    sets.append(named)
                    continue
                lookup=self.index.tags["classes" if k=="categories" else k]
                sets.append(set().union(*(lookup.get(str(v).casefold(),()) for v in selectors[k])))
        return set.intersection(*sets) if sets else set()

    def eligible_targets(self,offer):
        if offer.get("strict") and not (offer.get("families") or offer.get("vendors")):
            return set()
        members=self.members(offer)
        excluded=[w.casefold() for w in offer.get("exclude_words",())]
        if excluded:
            members={cid for cid in members if not any(w in self.index.cat.cards[cid].title.casefold() for w in excluded)}
        if offer.get("audience"):
            members={cid for cid in members if self.target_offer(cid,offer["audience"])}
        return members

    def compile(self,rules):
        result=[]
        for rule in [*rules,*self.legacy]:
            if not rule.get("enabled",True):continue
            when=rule["when"]
            offer=rule["offer"]
            members=self.eligible_targets(offer)
            anchors=self.members(when,anchor=True)
            if not members:continue
            if not anchors:
                if any(when.get(k) for k in ("classes","categories","vendors","families")) or not when.get("query_words"):
                    continue
                anchors=None
            if not offer.get("families"):
                # Один класс фида может содержать и серверы документооборота, и редакторы PDF.
                # Термины назначения из правила уточняют выбор внутри его целевого класса.
                source_text=" ".join(str(v) for k in ("query_words","families","vendors") for v in when.get(k,[])).casefold()
                purpose={t.casefold() for t in re.findall(r"\b[A-Za-z][A-Za-z0-9-]{2,}\b",rule["reason"])
                         if t.casefold() not in source_text}
                if purpose:
                    named={i for i in members if any(term in self.index.cat.cards[i].title.casefold() for term in purpose)}
                    if named:members=named
            def target_rank(cid):
                confirmed=False
                if offer.get("audience"):
                    variant=self.target_offer(cid,offer["audience"])
                    label=self.card_audience(cid)
                    confirmed=bool(variant and (audience(variant.name) or label or variant.lic.audience) in audience_values(offer["audience"]))
                return confirmed,self.index.quality[cid],cid

            targets=sorted(members,key=target_rank,reverse=True)
            result.append((anchors,when.get("query_words",[]),targets,rule))
        return sorted(result,key=lambda r:-float(r[3].get("weight",0)))

    def picks(self,journal,q,ids,limit,blocked=(),edition_audience=None):
        if self.provider:
            version,rules=self.provider.active_rules(journal)
            if self.version!=version:
                self.compiled=self.compile(rules)
                self.version=version
        if not ids:return []
        anchor=self.index.cat.cards[ids[0]].offers[0]
        vendor=normalize(anchor.vendor or "")
        classes={anchor.class_id,anchor.category_id,anchor.attrs.get("kb_category")}-{None}
        explicit=edition_audience or audience(q)
        requested=explicit or self.card_audience(ids[0])
        found=[]
        seen=set(ids)|set(blocked)
        # Широкий префикс может охватывать разные классы и вендоров.
        # Правило должно относиться к основным результатам запроса.
        anchor_ids=ids[:min(3,len(ids))]
        for members,words,targets,rule in self.compiled:
            if requested and rule["when"].get("audience") and requested not in audience_values(rule["when"]["audience"]):continue
            if members is not None and any(cid not in members for cid in anchor_ids):continue
            if words and not (query_matches(words,q) or edition_audience and query_matches(words,normalize(self.index.cat.cards[ids[0]].title))):continue
            for target in targets:
                bound=self.bindings.get(target)
                if (bound and anchor.domain=="software" and not any(v==vendor for v,_ in bound)
                        and any(k in classes for _,k in bound)):
                    continue
                if target not in seen:
                    if explicit=="home" or edition_audience:
                        expected=rule["offer"].get("audience")
                        if expected and explicit not in audience_values(expected):continue
                        if not self.target_offer(target,explicit,confirmed=bool(edition_audience)):continue
                        rule=rule|{"offer":rule["offer"]|{"audience":explicit}}
                    seen.add(target)
                    found.append((target,rule))
                    break
            if len(found)>=limit:break
        return found


def interleave(q,cards,extra,start=1):
    slots=list(range(start,len(cards)+1))
    Random(blake2s(q.encode()).digest()).shuffle(slots)
    for i,item in sorted(zip(slots,extra[:len(cards)//2]),reverse=True):
        cards.insert(i,item)
