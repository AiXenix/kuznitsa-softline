"""Рекомендации магазина, привязанные к продаваемым карточкам."""
from collections import defaultdict
from hashlib import blake2s
from random import Random
import yaml
from kuznitsa.optional import optional_module


class Recommendations:
    def __init__(self,index,kb,cfg):
        self.index=index
        path=cfg.kb/"upsell_r9.yaml"
        self.base=yaml.safe_load(path.read_text()) if path.exists() else []
        if isinstance(self.base,dict):self.base=self.base.get("rules",[])
        self.legacy=[]
        aliases=defaultdict(set)
        for fid,row in kb.rows["families"].items():
            for name in (row.get("name"),row.get("title"),*row.get("aliases",[])[:3]):
                if name:
                    matches=index.products(name.lower())
                    if matches:
                        aliases[fid].update(matches[:3])
                        break
        for fid,members in aliases.items():
            index.tags["families"][fid].update(members)
            category=kb.rows["families"][fid].get("category")
            if category:index.tags["classes"][category].update(members)
        for rule in kb.rows["crosssell"].values():
            for item in rule["suggest"]:
                self.legacy.append(dict(id=rule["id"],weight=.4,when=rule["when"],
                    offer=(dict(families=item["families"]) if any(f in aliases for f in item.get("families",[])) else dict(classes=[item.get("category")])),reason=item["reason"]))
        self.provider=optional_module("kuznitsa.analytics.upsell_rules")
        self.version=None
        self.compiled=self.compile(self.base or [])

    def members(self,selectors):
        sets=[]
        for k in ("classes","categories","families","vendors"):
            if selectors.get(k):
                lookup=self.index.tags["classes" if k=="categories" else k]
                sets.append(set().union(*(lookup.get(str(v).casefold(),()) for v in selectors[k])))
        return set.intersection(*sets) if sets else set()

    def compile(self,rules):
        result=[]
        for rule in [*rules,*self.legacy]:
            if not rule.get("enabled",True):continue
            when=rule["when"]
            offer=rule["offer"]
            members=self.members(offer)
            if not members and offer.get("families"):
                members=self.members({k:offer[k] for k in ("families","vendors") if k in offer})
            if not members and offer.get("classes"):
                members=self.members({"classes":offer["classes"]})
                if members and offer.get("families"):
                    rule=dict(rule,reason="Сопутствующий товар из рекомендованного раздела")
            targets=sorted(members,key=lambda i:(self.index.quality[i],i),reverse=True)
            if targets:result.append((self.members(when),when.get("query_words",[]),targets,rule))
        return sorted(result,key=lambda r:-float(r[3].get("weight",0)))

    def picks(self,journal,q,ids,limit):
        if self.provider:
            version,rules=self.provider.active_rules(journal)
            if self.version!=version:
                self.compiled=self.compile(rules)
                self.version=version
        if not ids:return []
        found=[]
        seen=set(ids)
        for members,words,targets,rule in self.compiled:
            if words and not any(str(w).lower() in q for w in words):continue
            if any(rule["when"].get(k) for k in ("classes","categories","families","vendors")) and ids[0] not in members:continue
            for target in targets:
                if target not in seen:
                    seen.add(target)
                    found.append((target,rule))
                    break
            if len(found)>=limit:break
        return found


def interleave(q,cards,extra):
    slots=list(range(1,len(cards)+1))
    Random(blake2s(q.encode()).digest()).shuffle(slots)
    for i,item in sorted(zip(slots,extra[:len(cards)//2]),reverse=True):
        cards.insert(i,item)
