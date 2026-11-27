"""Два уровня поиска в фиде: страницы продуктов и классы магазина."""
from collections import defaultdict
from functools import lru_cache
import json
import re

import numpy as np
from rapidfuzz import process, fuzz
from kuznitsa.text import normalize, lemma
from kuznitsa.llm.decisions import choice


HARDWARE = {"сервер":"сервера", "ноутбук":"ноутбука", "моноблок":"моноблока",
            "принтер":"принтера", "коммутатор":"коммутатора", "монитор":"монитора", "ибп":"ИБП"}
ALIASES = {
    "винда": "microsoft windows", "365": "microsoft 365", "офис": "офисные пакеты",
    "астра линукс": "astra linux", "мдаемон": "mdaemon", "крипто про": "криптопро",
    "антивирь": "антивирус", "макс патрол": "maxpatrol", "max patrol": "maxpatrol",
    "кибер бекап": "кибер бэкап",
    "w10": "windows 10", "w11": "windows 11", "win10": "windows 10", "win11": "windows 11",
    "win 10": "windows 10", "win 11": "windows 11",
    "win srv": "windows server", "вин сервер": "windows server", "вин серв": "windows server",
    "виндовс сервер": "windows server", "виндоус сервер": "windows server",
    "виндоус": "windows", "виндовс": "windows",
    "o365": "microsoft 365", "о365": "microsoft 365", "m365": "microsoft 365", "м365": "microsoft 365",
    "office 365": "microsoft 365", "office365": "microsoft 365", "офис 365": "microsoft 365", "офис365": "microsoft 365",
    "finereader": "contentreader pdf", "файнридер": "contentreader pdf", "abbyy finereader": "contentreader pdf",
    "автокад лт": "autocad lt", "автокад": "autocad", "акад": "autocad",
    "фотошоп": "adobe photoshop", "фш": "adobe photoshop",
    "иллюстратор": "adobe illustrator", "люстра": "adobe illustrator", "премьер": "adobe premiere",
    "акробат": "adobe acrobat",
    "корел дро": "coreldraw", "корел": "coreldraw",
    "вин рар": "winrar", "винрар": "winrar",
    "мс sql": "microsoft sql server", "ms sql": "microsoft sql server", "скуль": "microsoft sql server",
    "вижуал студио": "visual studio", "визуал студио": "visual studio",
    "экселька": "microsoft office excel", "эксель": "microsoft office excel",
    "ворд": "microsoft office word",
    "эксчендж": "microsoft exchange", "ексчендж": "microsoft exchange", "эксчейндж": "microsoft exchange",
    "касперский": "kaspersky", "каспер": "kaspersky", "кав": "kaspersky",
    "дрвеб": "dr web", "доктор веб": "dr web",
    "нанокад": "nanocad",
    "антивирусс": "антивирус",
}
EXACT_ONLY_ALIASES = frozenset({"офис", "фш", "кав"})
_SUBSTRING_ALIASES = tuple(
    (a, b, re.compile(r"\b" + re.escape(a) + r"\b"))
    for a, b in sorted(ALIASES.items(), key=lambda pair: len(pair[0]), reverse=True)
    if not a.isdigit() and a not in EXACT_ONLY_ALIASES
)
_SSD_WORD = re.compile(r"\bssd\b")
_AUX_TITLE_RE = re.compile(r"поддержк|обучен|курс |сертификат|миграц|продлен", re.I)
TASKS = [(r"вирус|антивир", "антивирусы для организаций"),(r"защит.*почт|почт.*защит","защита почты"),
         (r"чертеж","системы автоматизированного проектирования"),(r"контрагент","проверка контрагентов")]
STOP={"и","по","для","на","в","от","купить"}
QUESTION=re.compile(r"^(?:что (?:использовать|выбрать|подойд[её]т|поставить|нужно)|как(?:ой|ое|ую|ая|ие|им) (?:программ|приложен|софт|инструмент|антивирус|систем|по)|чем |на ч[её]м |как (?:проверить|защитить|настроить|организовать|сделать)|программ\w* для|нужн[аоы] программ|сколько стоит|где купить|что есть у )")
COMPLEX=re.compile(r"\n|;|\b(продлен\w*|продлить|до|мест|лицензий|сравни\w*|комплект|аналог|заменить|реестр\w*|куплен\w*|заказ\w*)\b")
PLATFORM_FIELD=re.compile(r"\bплатформа:\s*([^•;\n]+)",re.I)
PLATFORM_WORD=re.compile(r"\b(mac(?:\s?os\w*)?|windows|linux)\b",re.I)


@lru_cache(50000)
def words(s):
    return tuple(lemma(w) for w in re.findall(r"[\w]+",normalize(s)) if w not in STOP)


def class_words(text):
    generic={"программа","софт","приложение","программный","обеспечение","система","решение","по","работа","утилита"}
    roots={"текстовый":"текст","сетевой":"сеть","видеоредактирование":"видеоредактор"}
    terms=set()
    for word in words(text):
        word=roots.get(word,word)
        media=re.fullmatch(r"(видео|аудио|фото)(редактор|конвертер|плеер)",word)
        terms.update(media.groups() if media else [word])
    return frozenset(terms)-generic


class FeedIndex:
    def __init__(self,cat,kb,cfg):
        self.cat=cat
        self.groups=defaultdict(list)
        self.classes={}
        self.postings=defaultdict(set)
        self.terms={}
        self.raw_terms=defaultdict(set)
        self.license_offers=defaultdict(dict)
        self.server_offers={}
        self.platform_offers=defaultdict(dict)
        self.browse_quality={}
        self.quality={}
        self.tags=defaultdict(lambda:defaultdict(set))
        self.aliases=ALIASES.copy()
        self.products=lru_cache(512)(self.products)
        self.sections=lru_cache(256)(self.sections)
        tree=cfg.data/"feed_categories.json"
        lines=json.loads(tree.read_text()) if tree.exists() else {}
        for cid,c in cat.cards.items():
            o=c.offers[0]
            path=o.category_path
            section=o.class_id or (path[1] if len(path)>1 else c.category)
            self.groups[section].append(cid)
            self.classes[section]=path[min(1,len(path)-1)] if path else str(section)
            line=lines.get(o.group_id,[""])[0] if o.group_id else ""
            if line:
                c.title=line
            if o.domain in {"software","cloud","service"}:
                best_server,server_available=0,False
                for variant in c.offers:
                    platform_field=PLATFORM_FIELD.search(variant.description or "")
                    labels=" ".join(variant.platforms)
                    if platform_field:labels+=" "+platform_field[1]
                    for platform in PLATFORM_WORD.findall(labels.lower()):
                        key="macos" if platform.startswith("mac") else platform
                        self.platform_offers[key].setdefault(cid,variant)
                    server_score=2 if variant.lic.metric=="server" else int(bool(re.search(r"\b(?:server|сервер(?:\w*)?)\b",variant.name,re.I)))
                    if (server_score and variant.lic.action in (None,"new") and variant.lic.audience in (None,"business")
                            and (server_score,variant.available) > (best_server,server_available)):
                        self.server_offers[cid]=(server_score,variant)
                        best_server,server_available=server_score,variant.available
                    if variant.lic.metric:
                        self.license_offers["metric",variant.lic.metric].setdefault(cid,variant)
                    program=variant.attrs.get("license_program")
                    if isinstance(program,str) and program:
                        self.license_offers["license_type",program.casefold().strip()].setdefault(cid,variant)
            name=words(c.title)
            keys=set(name+words(o.vendor or "")+words(line))
            if o.group_id and not line:
                keys.update(words(o.name.split("(")[0].split(",")[0]))
            for raw in re.findall(r"[\w]+",normalize(c.title+" "+(o.vendor or ""))):
                self.raw_terms[raw].add(cid)
            self.terms[cid]=keys
            for w in keys:self.postings[w].add(cid)
            self.quality[cid]=(o.available,o.price is not None,len(c.offers),-len(c.title))
            # Технические дополнения остаются в разделе за самостоятельными линейками.
            auxiliary=bool(set(name) & {"клиент","client","агент","agent","модуль","плагин","plugin","connector","поддержка"})
            self.browse_quality[cid]=(not auxiliary,max(v.popularity for v in c.offers),
                                      o.available,len(c.offers),o.price is not None)
            for k,values in {"classes":[section,c.category,o.attrs.get("kb_category")],"families":[c.family,o.group_id,c.category,c.title,line],
                             "vendors":[o.vendor,c.vendor]}.items():
                for v in values:
                    if v:self.tags[k][str(v).casefold()].add(cid)
        for group in self.groups.values():group.sort(key=self.quality.get,reverse=True)
        self.card_sections={cid:k for k,group in self.groups.items() for cid in group}
        self.popular=sorted(cat.cards,key=self.quality.get,reverse=True)
        self.vocab=sorted(self.postings)
        self.prefix_vocab=sorted(self.raw_terms)
        from .feed_words import Sounds
        from .feed_tree import TreeVectors
        self.sounds=Sounds(self.vocab)
        descriptions={}
        for offer in cat.offers_by_id.values():
            if offer.group_id and offer.description:
                descriptions.setdefault(offer.group_id,offer.description)
        self.tree=TreeVectors(lines,descriptions,cat.dense,cfg)
        self.class_ids=list(self.groups)
        self.class_names={k:normalize(v) for k,v in self.classes.items()}
        self.class_by_name={v:k for k,v in self.class_names.items()}
        self.class_terms={k:set(words(v)) for k,v in self.classes.items()}
        for phrase,row in kb.rows["slang"].items():
            target=row["maps_to"]
            value=target.get("text") or target.get("query") or target.get("platform")
            if value:self.aliases.setdefault(normalize(phrase),str(value).replace("_"," "))
        vendor_spelling=defaultdict(set)
        for name,members in self.tags["vendors"].items():
            vendor_spelling[" ".join(words(name))].update(members)
        for ident,row in kb.rows["vendors"].items():
            for alias in (row.get("name"),row.get("name_ru"),*row.get("aliases",[])):
                if alias:
                    self.tags["vendors"][ident].update(vendor_spelling.get(" ".join(words(str(alias))),()))
        from kuznitsa.rank.upsell import Recommendations
        self.recommend=Recommendations(self,kb,cfg)
        self.slang={}
        for phrase,row in kb.rows["slang"].items():
            for kind,field in (("family","families"),("vendor","vendors"),("category","classes"),
                               ("line_id","families"),("class_id","classes")):
                target=row["maps_to"].get(kind)
                if target is None:continue
                members=self.tags[field].get(str(target).casefold())
                if members:
                    label=kb.rows["families"].get(target,{}).get("name") if field=="families" else None
                    exact=normalize(label) if label else None
                    ordered=sorted(members,key=lambda i:(exact is not None and normalize(cat.cards[i].title)==exact,
                                                          self.quality[i],i),reverse=True)
                    self.slang[normalize(phrase)]=(field,tuple(ordered))
                    break
        rows=kb.rows["hardware_hints"].values()
        self.hardware={}
        by_class={row["hardware_class"]:row for row in rows}
        for row in rows:
            for term in row["trigger_words"]:
                self.hardware[normalize(term)]=row
        from .hardware import hardware_kind
        def hardware_definition(value):
            kind,labels=hardware_kind(value)
            if kind in by_class:return by_class[kind]
            sections=[k for k,title in self.class_names.items() if
                      cat.cards[self.groups[k][0]].offers[0].domain=="hardware" and
                      any(label in words(title) for label in labels)]
            if sections:return dict(hardware_feed_classes=sections,software_classes=[])
            return {}

        for term,row in kb.rows["slang"].items():
            target=row["maps_to"]
            if target.get("attr")!="hardware_class":continue
            definition=hardware_definition(target.get("value",""))
            # Часть сокращений относится к более узкому классу, указанному в примечании.
            match=re.search(r"фид\s+([\d, ]+)",row.get("note",""))
            keys=[k for k in re.findall(r"\d+",match[1]) if k in self.groups
                  and cat.cards[self.groups[k][0]].offers[0].domain=="hardware"] if match else []
            if keys or definition:
                base=self.hardware.get(normalize(term),definition)
                self.hardware[normalize(term)]={**base,"hardware_class":target["value"],
                    "hardware_feed_classes":keys or base["hardware_feed_classes"]}
        for alias,kind in {"ноут":"laptop","нетбук":"laptop","сервак":"server","комп":"desktop",
                           "мфушка":"printer_mfp","принтак":"printer_mfp","свитч":"switch","моник":"monitor",
                           "бесперебойник":"ups","ssd":"ssd"}.items():
            definition=hardware_definition(kind)
            if definition:self.hardware.setdefault(alias,definition)
        self.class_aliases={}
        for key,title in self.class_names.items():
            signature=class_words(title)
            if signature:self.class_aliases.setdefault(signature,[]).append(key)
        class_tasks=defaultdict(list)
        self.task_cues=[]
        self.section_phrases={}
        for row in kb.rows["feed_tasks"].values():
            target=next((self.class_by_name[normalize(label)] for label in row["sections"]
                         if normalize(label) in self.class_by_name),None)
            if target is None:continue
            class_tasks[target].extend(row.get("phrases",[]))
            for phrase in row.get("aliases",[]):
                self.section_phrases[frozenset(words(phrase))]=target
            for phrase in row.get("phrases",[]):
                cue=frozenset(words(phrase))
                if cue:self.task_cues.append((cue,target))
        self.task_cues.sort(key=lambda pair:len(pair[0]),reverse=True)
        self.class_vec=None
        if hasattr(cat.dense,"model"):
            documents=[]
            for section in self.class_ids:
                group=self.groups[section]
                card=cat.cards[group[0]]
                category=kb.rows["categories"].get(card.category,{})
                description=category.get("description","")
                examples=", ".join(cat.cards[cid].title for cid in group[:4])
                documents.append(". ".join(filter(None,(self.classes[section],description,
                                    ", ".join(class_tasks[section]),examples))))
            self.class_vec=cat.dense.cached_embeddings(cfg,documents)
        self.card_vendors={cid:c.vendor or normalize(c.offers[0].vendor or "") for cid,c in cat.cards.items()}
        self.vendor_names={normalize(c.offers[0].vendor):self.card_vendors[cid] for cid,c in cat.cards.items() if c.offers[0].vendor}
        self.vendor_names.update({" ".join(words(name)):ident for name,ident in self.vendor_names.items()})
        for vid,row in kb.rows["vendors"].items():
            actual=next((self.vendor_names[" ".join(words(name))] for name in [row.get("name"),row.get("name_ru"),*row.get("aliases",[])]
                         if name and " ".join(words(name)) in self.vendor_names),None)
            if actual:
                for name in [row.get("name"),row.get("name_ru"),*row.get("aliases",[])]:
                    if name:self.vendor_names.setdefault(" ".join(words(name)),actual)
        from .feed_language import FeedLanguage
        self.language=FeedLanguage(self,kb)
        from .feed_flagships import FeedFlagships
        self.flagships=FeedFlagships(self,kb,cfg)
        self.products.cache_clear()
        self.unsold_sections={normalize(name):parent for key,(name,parent) in lines.items()
                              if key not in cat.cards and parent in self.groups}
        self.unsold_brands=defaultdict(list)
        for name,parent in self.unsold_sections.items():
            if words(name):self.unsold_brands[words(name)[0]].append(parent)
        self.software_sections=[k for k,members in self.groups.items()
                                if cat.cards[members[0]].offers[0].domain in {"software","cloud","service"}]
        self.platform_sections={k:{self.card_sections[cid] for cid in group} for k,group in self.platform_offers.items()}
        self.replacements={}
        for row in kb.rows["analogs"].values():
            for phrase in [row.get("product"),*row.get("aliases",[])]:
                if phrase:self.replacements[normalize(phrase)]=row
        self.task_rows=kb.rows["use_cases"]
        from .feed_repair import FeedRecovery
        self.recovery=FeedRecovery(self,kb)
        from .feed_analogs import AnalogIndex
        from .feed_editions import resolve
        self.edition=lru_cache(512)(lambda text:resolve(self,text))
        self.analogs=AnalogIndex(self,kb.rows["feed_analogs"])
        from .feed_solutions import SolutionIndex
        self.solutions=SolutionIndex(self,cfg.kb)

    def correct(self,q):
        if q in HARDWARE:return q
        if q in self.aliases:return self.aliases[q]
        for a,b,pat in _SUBSTRING_ALIASES:
            if a in q:q=pat.sub(b,q)
        if q!="ssd" and "ssd" in q and _SSD_WORD.search(q):
            expanded=_SSD_WORD.sub("твердотельный накопитель",q)
            if self.products(expanded,fuzzy=False):return expanded
        return q

    def products(self,q,prefix=False,domain=None,fuzzy=True,segment=None):
        terms=list(words(q))
        if not terms:return ()
        pools=[]
        for w in terms:
            group=self.postings.get(w,set())
            if prefix and w==terms[-1]:
                from bisect import bisect_left
                from bisect import bisect_right
                partial=re.findall(r"[\w]+",normalize(q))[-1]
                i=bisect_left(self.prefix_vocab,partial)
                end=bisect_right(self.prefix_vocab,partial+chr(0x10ffff))
                group=group.union(*(self.raw_terms[v] for v in self.prefix_vocab[i:end]))
            if fuzzy and not group and len(w)>=5:
                recovery=getattr(self,"recovery",None)
                if not (recovery and recovery.is_protected(w)):
                    best=process.extractOne(w,self.vocab,scorer=fuzz.ratio,score_cutoff=85)
                    if best:group=self.postings[best[0]]
            if group:pools.append(group)
        if len(pools)!=len(terms):return ()
        ids=set.intersection(*pools)
        if domain:ids={i for i in ids if self.cat.cards[i].offers[0].domain==domain}
        named_year=any(re.fullmatch(r"20[012]\d",w) for w in terms)
        named_audience={"семья","дом","учеба","бизнес","personal","student","home","business"}.intersection(terms)
        edition_terms=({"учеба","student","personal","персональный"} if segment in {"edu","individual"}
                       else {"бизнес","business"})
        prefer_edition=bool(segment and named_year and not named_audience)
        flagships=getattr(self,"flagships",None)
        terms_tuple=tuple(terms)
        qset=frozenset(terms)
        n_terms=len(terms)
        def score(i):
            c=self.cat.cards[i]
            name=words(c.title)
            core_gen=flagships.core_generic.get(i,name) if flagships else name
            core_prod=flagships.core_product.get(i,name) if flagships else name
            f_rank=flagships.rank.get(i,0) if flagships else 0
            exact=(terms_tuple==name or terms_tuple==core_gen or (terms_tuple==core_prod and f_rank>0))
            is_addon=flagships.is_addon(i,qset) if flagships else False
            is_demoted=flagships.is_demoted(i,qset) if flagships else False
            aux_hit=(i in flagships.aux_title) if flagships else bool(_AUX_TITLE_RE.search(c.title))
            primary=(not is_demoted and not is_addon
                     and not aux_hit
                     and ("cal" not in name or "cal" in qset))
            version=flagships.card_year.get(i,0) if flagships else max((int(y) for y in name if re.fullmatch(r"20[012]\d",y)),default=0)
            first=min(
                min((core_gen.index(w) for w in terms if w in core_gen),default=99),
                min((core_prod.index(w) for w in terms if w in core_prod),default=99),
                min((name.index(w) for w in terms if w in name),default=99),
            )
            starts_line=(core_gen[:n_terms]==terms_tuple or core_prod[:n_terms]==terms_tuple
                         or name[:n_terms]==terms_tuple)
            consumer=int(("family" in name or "семья" in name)
                         and (segment=="individual" or bool(named_audience & {"семья","дом","home"})))
            starts=prefix and any(t.startswith(terms[-1]) for t in name[:2])
            fitting_release=prefer_edition and bool(edition_terms.intersection(name))
            return (primary,exact,starts,all(w in name for w in terms),f_rank>0,f_rank,-first,
                    fitting_release,self.quality[i][0],starts_line,version,consumer,*self.quality[i][1:],i)
        return tuple(sorted(ids,key=score,reverse=True))

    def sound_products(self,q):
        raw=[w for w in re.findall(r"[\w]+",normalize(q)) if w not in STOP
             and lemma(w) not in ("клиент","лицензия","приложение","продукт")]
        if not raw:return (),q
        recovery=getattr(self,"recovery",None)
        if recovery and (any(recovery.is_hard_protected(w) for w in raw) or (len(raw)==1 and recovery.is_protected(raw[0]))):
            return (),q
        alternatives=[]
        single_word=len(raw)==1
        for w in raw:
            lw=lemma(w)
            # Не подменяем одиночное кириллическое слово каталога созвучным английским («антивирус» ↛ «antivirus»).
            if single_word and re.fullmatch(r"[а-я]+",w) and (w in self.postings or lw in self.postings):
                alternatives.append((lw,))
            else:
                alternatives.append(tuple(dict.fromkeys((lw,*self.sounds.lookup(w),*self.sounds.lookup(lw)))))
        if not any(len(opts)>1 for opts in alternatives):return (),q
        pools=[set().union(*(self.postings.get(w,()) for w in opts)) for opts in alternatives]
        matches=set.intersection(*pools)
        if not matches:return (),q
        best=max(matches,key=lambda i:(sum(any(w in words(self.cat.cards[i].title) for w in opts)
                                           for opts in alternatives),self.quality[i],i))
        corrected=" ".join(next(w for w in opts if w in self.terms[best]) for opts in alternatives)
        return self.products(corrected),corrected

    def matching_sections(self,q):
        signature=class_words(q)
        candidates=self.class_aliases.get(signature,[])
        if not candidates and len(signature)>=2:
            # «Защита смартфонов» также соответствует «Защита информации для смартфонов».
            supersets=[s for s in self.class_aliases if signature < s and len(s)==len(signature)+1]
            candidates=[cid for s in supersets for cid in self.class_aliases[s]]
        return sorted(candidates,key=lambda k:len(self.groups[k]),reverse=True)

    def class_match(self,q):
        return (self.class_by_name.get(normalize(q)) or self.section_phrases.get(frozenset(words(q)))
                or next(iter(self.matching_sections(q)),None))

    def task_class(self,q):
        hit=self.solutions.match(q)
        if hit and hit.sections:return hit.sections[0]
        terms=set(words(q))
        return next((section for cue,section in self.task_cues if cue<=terms),None)

    def sections(self,q,hint="",software_only=False,platform=None):
        words_hint=set(words(hint or q))
        vector=self.cat.dense.encode(q) if self.class_vec is not None else None
        emb=np.einsum("ij,j->i",self.class_vec,vector) if vector is not None else np.zeros(len(self.class_ids))
        leaf=self.tree.scores(vector) if vector is not None else {}
        scores={}
        exact=normalize(hint or q)
        for i,k in enumerate(self.class_ids):
            common=len(words_hint & self.class_terms[k])/max(len(words_hint),1)
            scores[k]=.6*float(emb[i])+.4*leaf.get(k,0)+common+(exact==self.class_names[k])
        pool=self.software_sections if software_only else self.class_ids
        if platform in self.platform_sections:pool=[k for k in pool if k in self.platform_sections[platform]]
        return sorted(pool,key=scores.get,reverse=True)[:8]

    def decide(self,e,q,options,sid,req,calls,focus=()):
        labels={}
        for k in options:
            examples=[i for i in focus if i in self.groups[k]][:3] or self.groups[k][:3]
            title=self.classes[k]
            root=self.cat.cards[self.groups[k][0]].offers[0].category_path[0]
            labels[k]=root+" / "+title+". "+", ".join(self.cat.cards[i].title for i in examples)
        labels["none"]="Подходящего раздела нет"
        from time import perf_counter
        answers,meta=e.decisions.decide_before(perf_counter()+.59,sid,req.model_source,"intent",{"запрос":q},
                         {"section":choice("Какой раздел магазина решает задачу покупателя?",labels)})
        calls.append(meta)
        answer=answers.get("section",{})
        k=answer.get("choice")
        return k if k in options and answer.get("probabilities",{}).get(k,0)>=.55 else None
