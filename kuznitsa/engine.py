from collections import Counter
from datetime import date,datetime,timezone,timedelta
from rapidfuzz import process
from time import perf_counter,time
import json
import re
from uuid import uuid4
from threading import Lock
from .controls import Controls, PhraseRules
from .plans import naive
from .analytics.store import Journal
from .config import Config,WEIGHTS
from .data_lock import snapshot_lock
from .schema import Client,Request
from .index.store import Catalog
from .kb.loader import load
from .kb.lexicon import Lexicon
from .suggest.index import SuggestIndex
from .text import normalize,sku_key,tokens,lemma
from collections import defaultdict
from .understand.refine import refine,apply_profile
from .understand.repair import repair
from .understand.normalize import lookup_skus
from .understand.entities import extract
from .understand.model import chips_for, ignore_conditions
from .understand.intent import TITLES
from .rank.variants import select,public_offer
from .rank.business import ranked
from .rank.diversity import diversify
from .plans.base import candidates
from .llm.jev import Disabled,Jev
from .llm.decisions import Decisions,choice
from .plans.knowledge import KnowledgeIndex
from .plans import scenarios
from .plans.companions import companions
from .understand.routing import route,PIRACY,HARDWARE
import os
from .understand.session import Sessions,inherit

LABEL = dict(delivery="способ поставки",term_months="срок",quantity="количество мест",audience="аудитория",version="версия",
             edition="редакция",platform="платформа",price_max="верхняя граница цены",price_min="нижняя граница цены")



class Trace:
    def __init__(self,timer):
        self.timer=timer
        self.steps = []
        self.start = self.last = timer()

    def add(self,step,title,summary,status="ok",**detail):
        now = self.timer()
        self.steps.append(dict(step=step,title=title,status=status,ms=round(1000*(now-self.last),2),summary=summary,detail=detail))
        self.last = now


class Engine:
    def __init__(self,cat,kb,clients,journal,clock=time,llm=None,timer=perf_counter,controls=None,decisions=None,usd_rub=100.):
        self.catalog,self.kb,self.clients,self.journal = cat,kb,clients,journal
        self.clock,self.llm,self.timer = clock,llm or Disabled(),timer
        self.usd_rub=usd_rub
        self.controls = Controls() if controls is None else controls
        self._rules_lock = Lock()
        self._rules_key = None
        self.names = {k:{i:r.get("title") or r.get("name",i) for i,r in kb.rows[g].items()}
                      for k,g in dict(vendor="vendors",family="families",category="categories").items()}
        for card in cat.cards.values():
            o=card.offers[0]
            for k,ident,name in [("family",card.family,o.family_name or o.name),("vendor",card.vendor,o.vendor),
                                 ("category",card.category,(o.category_path or [None])[-1])]:
                if ident and name:
                    self.names[k].setdefault(ident,name)
        self.exact_titles={normalize(c.title) for c in cat.cards.values()}
        self.exact_titles.update(normalize(c.kb["title"]) for c in cat.cards.values() if c.kb.get("title"))
        self._rules()
        self.vendor_families=defaultdict(list)
        self.family_terms={}
        for fid,row in kb.rows["families"].items():
            self.vendor_families[row.get("vendor")].append(fid)
            self.family_terms[fid]=set(map(lemma,tokens(row.get("title") or row["name"])))
        self.vendor_terms={vid:set(map(lemma,tokens(" ".join([r.get("name",""),*map(str,r.get("aliases",[]))])))) for vid,r in kb.rows["vendors"].items()}
        self.knowledge=KnowledgeIndex(kb,self.lex)
        self.sessions=Sessions(journal.path,clock) if hasattr(journal,"path") else None
        self.decisions=decisions
        if self.decisions is None and self.llm.enabled and hasattr(journal,"path"):
            self.decisions=Decisions(self.llm,journal.path,clock,Config().daily_budget)

    def _rules(self):
        with self._rules_lock:
            controls = self.controls
            key = (controls, controls.version())
            if self._rules_key != key:
                lex = Lexicon(self.kb, self.catalog)
                rules = controls.synonyms()
                for rule in rules:
                    if rule["kind"] != "text":
                        lex.add(rule["phrase"], rule["kind"], rule["to"], "rule:" + rule["rule_id"])
                lex.spell_words = sorted(w for w in lex.words if len(w)>=4)
                from .understand.spell_index import spell_terms
                lex.roman=spell_terms(lex)
                self._phrases = PhraseRules(r for r in rules if r["kind"] == "text")
                self.suggestions = SuggestIndex(lex, self.names)
                self.lex = lex
                self._rules_key = key
            return self.lex, self._phrases

    @classmethod
    def open(cls,cfg=None,clock=time,llm=None,journal=None,controls=None):
        cfg = cfg or Config()
        with snapshot_lock(cfg.data):
            return cls._open_snapshot(cfg,clock,llm,journal,controls)

    @classmethod
    def _open_snapshot(cls,cfg,clock,llm,journal,controls):
        kb = load(cfg.kb)
        extra = cfg.data/"mock_families.jsonl"
        if extra.exists():
            for line in extra.read_text().splitlines():
                f = json.loads(line)
                kb.rows["families"].setdefault(f["id"],f)
        cat = Catalog(cfg,kb)
        clients = {}
        today = datetime.fromtimestamp(clock(),timezone.utc).date()
        clients_path=cfg.data/"clients.jsonl"
        for line in clients_path.read_text().splitlines() if clients_path.exists() else []:
            c = Client.model_validate_json(line)
            for p in c.owned:
                for field,offset,sign in [("expires_at","expires_in_days",1),("purchased_at","purchased_days_ago",-1)]:
                    if p.get(field):
                        p[offset]=(date.fromisoformat(p[field])-today).days*sign
                    elif p.get(offset) is not None:
                        p[field] = str(today+timedelta(days=p[offset]*sign))
            for order in c.orders:
                if "date" not in order and order.get("days_ago") is not None:
                    order["date"] = str(today-timedelta(days=order["days_ago"]))
            clients[c.client_id] = c
        clients.setdefault("guest",Client(client_id="guest",title="Гость",segment="smb",demo=True))
        path=cfg.data/"kuznitsa.sqlite"
        if llm is None and os.getenv("KZ_LLM","auto")!="off" and os.getenv("OPENROUTER_API_KEY"):
            llm=Jev(key=os.environ["OPENROUTER_API_KEY"],url=cfg.jev_url,model=cfg.jev_model)
        if llm is None:
            llm=Disabled()
            llm.model=cfg.jev_model
        decisions=Decisions(llm,path,clock,cfg.daily_budget,price_in=cfg.jev_price_in)
        return cls(cat,kb,clients,journal or Journal(path),clock,llm,controls=controls,decisions=decisions,usd_rub=cfg.usd_rub)

    def close(self):
        if self.decisions:
            self.decisions.pool.shutdown()
        if self.llm.enabled:
            self.llm.close()
        if self.sessions:
            self.sessions.close()

    def card(self,ident,profile_id="guest",qty=None,term=None,action=None):
        if ident.startswith("sku:") and ident not in self.catalog.cards:
            offer = self.catalog.offers_by_id[ident[4:]]
            card = naive.card(self, offer, 1)
            card["variants"] = [public_offer(offer)]
            return card
        c=self.catalog.cards[ident]
        profile=self.clients[profile_id]
        f={k:v for k,v in dict(term_months=term,action=action).items() if v}
        selection=select(c,profile,f,{},dict(value=qty) if qty else None)
        if not selection:
            return dict(card_id=c.id,title=c.title,offer=None,calc=None,variants=[public_offer(o) for o in c.offers],variants_count=len(c.offers))
        card=ranked(c,selection,1,True,profile,WEIGHTS,self.kb)
        card["variants"]=[public_offer(o) for o in c.offers]
        return card

    def search(self,req: Request):
        rules = self._rules()
        profile = self.clients["guest" if "profile" in req.ignore else req.profile_id]
        trace = Trace(self.timer)
        if req.mode == "naive":
            return self._naive(req, profile, trace)
        return self._search(req, profile, trace, rules)

    def _naive(self, req, profile, trace):
        offers = naive.match(self.catalog, req.q, limit=None)
        trace.add("retrieve","Поиск по названию",f"Все слова встретились в названиях {len(offers)} предложений")
        start = (req.page-1)*req.page_size
        cards = [naive.card(self,o,i) for i,o in enumerate(offers[start:start+req.page_size], start+1)]
        trace.add("compose","Выдача по популярности",f"Предложений на странице · {len(cards)}")
        result = dict(search_id="s_"+uuid4().hex, mode="naive", engine="naive", engine_version="0.1.0",
                      query=dict(raw=req.q,normalized=req.q.lower(),corrected=req.q,corrections=[],did_you_mean=None),
                      understood=dict(intent="product",intent_title="Поиск по названию",intent_conf=0.,intent_source="fallback",
                                      filters={},exclude={},qty=None,entities=[],chips=[],agent_note="Ищу все слова в названии SKU"),
                      blocks=[dict(type="products",title="Предложения",items=cards,total=len(offers))],
                      banners=[],relax_hints=[],facets=[],related_queries=[],notes=[],trace=trace.steps,cost=dict(llm_calls=0,cached=0,tokens_in=0,usd=0,rub=0),
                      timing_ms=dict(total=round((self.timer()-trace.start)*1000,2)),
                      profile=dict(id=profile.client_id,title=profile.title,segment=profile.segment))
        self.journal.search(self.clock(),req,result,len(offers),None if offers else "vocabulary_gap",False)
        result["timing_ms"]["total"]=round((self.timer()-trace.start)*1000,2)
        if not req.explain:
            result["trace"]=[]
        return result

    def _search(self, req, profile, t, rules, redirect=None, persist=True, sid=None, prior_calls=()):
        sid=sid or "s_"+uuid4().hex
        calls=list(prior_calls)
        lex, phrases = rules
        raw = redirect["q"] if redirect else req.q
        original_norm = normalize(req.q)
        norm, synonyms = phrases.apply(normalize(raw))
        category = req.category if not ({"category","context"} & set(req.ignore) or req.context=="off") else None
        t.add("normalize","Нормализация",norm or "Пустой запрос")
        exact_offers=lookup_skus(self.catalog,norm)
        sku_prefix=False
        if not exact_offers and re.fullmatch(r"[a-zа-я]{1,5}[- ]?\d{3,}",norm):
            for offer in self.catalog.prefix_skus(norm):
                exact_offers.setdefault(offer.card_id,offer)
            sku_prefix=bool(exact_offers)
        sku=next(iter(exact_offers.values()),None)
        t.add("sku_lookup","Точный артикул",", ".join(o.sku for o in exact_offers.values()) or "Совпадений по артикулу нет")
        words,changes= (tokens(norm),[]) if sku or req.verbatim else repair(norm,lex)
        corrected=" ".join(words) if changes else norm
        t.add("repair","Проверка написания",", ".join(x["from"]+" → "+x["to"] for x in changes) or "Запрос сохранён")
        f,exc,entities,qty,residual=extract(words,lex,self.kb)
        if sku:
            f,exc,entities={}, {}, []
        qty=refine(self,words,f,exc,entities,qty)
        f.update(req.filters)
        exc.update(req.exclude)
        synonyms += [dict(rule_id=e["source"][5:],phrase=e["text"],kind=e["type"],to=e["id"])
                     for e in entities if e["source"].startswith("rule:")]
        previous=self.sessions.previous(req) if self.sessions and persist else None
        qty,inherited=inherit(previous,norm,f,exc,qty)
        if inherited and "совместимость" in inherited["fields"]:
            anchor=self.kb.rows["families"].get(previous["first_family"],{})
            platforms=anchor.get("compat_ru_os",[]) or anchor.get("platforms",[])
            if platforms:
                f["platform"]=platforms[:1]
        entities,qty=ignore_conditions(req.ignore,words,f,exc,entities,qty)
        chips=chips_for(words,entities,self.names,exc,f,qty)
        t.add("entities","Сущности и параметры",", ".join(x["label"] for x in chips) or "Явных условий нет",residual=residual,synonyms=synonyms,ignored=req.ignore)
        if inherited:
            chips.append(dict(key="context",label="В контексте · "+inherited["from_q"],source="context",removable=True))
        if category and not f.get("category"):
            chips.append(dict(key="category",label=self.names["category"].get(category,"Категория страницы"),source="context",removable=False))
            f["category"]=[category]
        if profile.client_id!="guest":
            chips.append(dict(key="profile",label=profile.title,source="context",removable=False))
        t.add("context","Контекст клиента",profile.title+(" · "+self.names["category"].get(category,category) if category else ""))
        intent=route(raw,words,f,entities,sku,category)
        code_search=intent=="sku" and not sku and bool(re.search(r"реестр|окпд2|ктру",norm))
        if code_search:
            f["registry"]=True
            if re.search(r"58[.]29[.]11(?:\D|$)",norm):
                f["category"]=["operating_systems"]
        if inherited and intent not in ("analog","renewal","license_ops"):
            intent="product" if "совместимость" in inherited["fields"] else previous["intent"]
        if not sku and category and re.match(r"^(под|для) ",norm) and f.get("platform") and not f.get("family"):
            f["category"]=[category]
            intent="category"
        intent_source="rules"
        intent_conf=.95 if entities or sku else .55
        if intent=="off_topic" and not entities and len(words)>1 and not re.search("ноутбук|картридж|принтер|торрент|кряк|активатор",corrected):
            nearest=self.catalog.dense.nearest_knowledge(corrected)
            if nearest and nearest[0] not in req.ignore:
                kind,ident,intent_conf=nearest
                intent_source="embed"
                intent={"category":"category","use_case":"task","role":"role_kit","industry":"industry","faq":"question"}[kind]
                entities.append(dict(type=kind,id=ident,text=corrected,span=[0,len(words)],source="embed",conf=intent_conf))
                if kind=="category":
                    f["category"]=[ident]
        state={"запрос":original_norm,"понимание":corrected,"условия":dict(f),"исключения":exc,"количество":qty,
               "сегмент":profile.segment,"раздел":category}
        smart=req.mode=="smart" and self.decisions is not None and not prior_calls
        if smart and not sku and corrected not in self.exact_titles and (intent in ("off_topic","broad","question","task") or intent_conf<.6) and not re.search(PIRACY+"|"+HARDWARE,corrected):
            questions={"intent":choice("Какой сценарий поиска нужен?",TITLES)}
            cats=self.knowledge.nearest("category",corrected)[:6]
            if cats:
                questions["category"]=choice("Какая категория соответствует запросу?",{**{k:self.names["category"][k] for k in cats},"none":"Не указана"})
            faqs=self.knowledge.nearest("faq",corrected)[:6]
            if faqs and intent=="question":
                questions["faq"]=choice("Какой вопрос соответствует запросу?",{**{k:self.kb.rows["faq"][k]["questions"][0] for k in faqs},"none":"Другая тема"})
            answers,meta=self.decisions.request(sid,req.source,"intent",state,questions)
            meta["probabilities"]={k:a["probabilities"] for k,a in answers.items()}
            calls.append(meta)
            for k,a in answers.items():
                val=a["choice"]
                prob=float(a["probabilities"][val])
                if val=="none" or prob<.55:
                    continue
                if k=="intent":
                    intent,intent_conf,intent_source=val,prob,"jev"
                elif k=="category" and not f.get("category") and intent in ("category","task"):
                    f["category"]=[val]
                elif k=="faq":
                    entities.insert(0,dict(type="faq",id=val,text=corrected,span=[0,len(words)],source="jev",conf=prob))
        apply_profile(profile,f,intent)
        for ignored in req.ignore:
            f.pop(ignored,None)
        plan=intent
        if plan=="product" and f.get("family") and not any(self.catalog.by["family"].get(fid) for fid in f["family"]):
            plan=intent="out_of_catalog"
        scores=None
        if plan=="vendor" and not any(self.catalog.by["vendor"].get(v) for v in f.get("vendor",[])):
            plan=intent="out_of_catalog"
        reason=None
        if intent=="off_topic":
            reason="hardware" if re.search(HARDWARE,corrected) else "piracy" if re.search(PIRACY,raw.lower()+" "+corrected) else "gibberish" if not entities and re.fullmatch("[a-z ]*",corrected) else "other"
            if reason=="other" and words:
                scores=self.catalog.scores(corrected)
            if reason=="other" and max((scores or {}).values(),default=0)>=.55:
                plan=intent="product"
                reason=None
        ctx=dict(q_raw=req.q,q_norm=original_norm,intent=intent,category_id=next(iter(f.get("category",[])),category),
                 segment=profile.segment,profile_id=profile.client_id,mode=req.mode)
        if redirect is None:
            redirect=self.controls.redirect(ctx)
            if redirect and redirect.get("q"):
                redirected_trace=Trace(self.timer)
                redirected_trace.start=t.start
                return self._search(req,profile,redirected_trace,rules,redirect,persist,sid)
            if redirect and redirect.get("category"):
                for key in ("family","vendor","edition"):
                    f.pop(key,None)
                f["category"]=[redirect["category"]]
                chips=[c for c in chips if c["key"] not in {"family","vendor","edition","category"}]
                chips.append(dict(key="category",label=self.names["category"].get(redirect["category"],redirect["category"]),
                                  source="rule",removable=False))
                ctx["category_id"]=redirect["category"]
                intent=plan="category"
                exact_offers,sku={},None
                reason=None
            elif redirect and redirect.get("intent") in TITLES:
                intent=redirect["intent"]
                plan=intent
                if plan!="sku":
                    exact_offers,sku={},None
                reason=None
        ctx["intent"]=intent
        summary=TITLES[intent]
        if redirect:
            summary+=" · применено перенаправление магазина"
        t.add("intent","Сценарий запроса",summary,"fallback" if any(not c["ok"] for c in calls) else "ok",redirect=redirect,calls=[m for m in calls if m["kind"]=="intent"])
        t.add("plan","План поиска",TITLES[plan] if intent==plan else f"{TITLES[intent]} · использую план «{TITLES[plan]}»","ok" if intent==plan else "fallback")
        special=scenarios.scope(self,intent,f,entities,corrected,profile,qty)
        if scores is None:
            need_text=special is None and not sku and not f.get("family") and plan not in {"out_of_catalog","sku","off_topic"}
            scores=self.catalog.scores(corrected or " ") if need_text else {}
        rel=dict.fromkeys(exact_offers,1.) if sku else special if special is not None else candidates(self.catalog,self.kb,plan,f,scores,None)
        if code_search:
            rel=candidates(self.catalog,self.kb,"category",f,{},None)
        t.add("retrieve","Отбор кандидатов",f"Подходящих карточек до проверки лицензий · {len(rel)}",
              sources=["Артикул"] if sku else ["Сущности","Совпадения по полям","Фрагменты слов"]+(["Смысл запроса"] if self.catalog.dense.matrix is not None else []))
        # Карточка уже проверена по семейству, вендору и дереву категорий.
        active={k:v for k,v in f.items() if k not in {"family","vendor","category"}}
        notes=[]
        relax_hints=[]
        if sku_prefix:
            notes.append("Найдены предложения с таким началом артикула.")
        if code_search:
            notes.append("Точный регистрационный номер в каталоге не подтверждён. Показан подбор по признаку включения в реестр.")
        if intent=="license_ops" and not f.get("action") and re.search("лицензии на",corrected) and any(
                self.kb.rows["families"].get(p.get("family_id"),{}).get("vendor") in f.get("vendor",[]) for p in profile.owned):
            active["action"]="addon"
            notes.append("У организации уже есть продукт вендора. Проверены лицензии на дополнительные места.")
        if intent=="promo":
            active["promo"]=True
        if intent=="renewal":
            active["action"]="renewal"
        if intent=="product" and "с техподдержкой" in corrected:
            active.pop("action",None)
        if intent=="service":
            for key in ("action","edition","metric"):
                active.pop(key,None)
        if qty and f.get("family"):
            upgrades={self.catalog.cards[c].kb.get("upgrade_to") for c in rel if (self.catalog.cards[c].kb.get("max_seats") or float("inf"))<qty["value"]}
            extra={cid:.88 for fid in upgrades for cid in self.catalog.by["family"].get(fid,())}
            if extra:
                rel.update(extra)
                active["action"]="new"
                notes.append("Запрос превышает предел младшей линейки. Показана новая покупка старшей линейки.")
        requested_qty=qty
        if intent in ("role_kit","industry") and not qty:
            qty=dict(value=profile.size_seats if profile.client_id!="guest" else 1,metric=None)
        if intent=="renewal" and not f.get("family") and f.get("vendor") and not any(
                self.kb.rows["families"].get(o.get("family_id"),{}).get("vendor") in f["vendor"] for o in profile.owned):
            for cid in rel:
                fam=self.catalog.cards[cid].kb
                mentions=fam.get("industries",[])
                popularity=(fam.get("popularity") or 3)/5
                matched_industry=profile.industry in mentions or profile.segment in mentions
                adjustment=.12 if matched_industry else -.24 if mentions else 0
                rel[cid]=max(.22,min(1.,rel[cid]+.16*popularity+adjustment))
        if intent=="renewal" and profile.owned:
            owned_ids={p["family_id"] for p in profile.owned if p.get("family_id")}
            if f.get("vendor") or f.get("family"):
                related={cid:v for cid,v in rel.items() if self.catalog.cards[cid].family in owned_ids}
                fit={cid:v for cid,v in related.items() if not qty or qty["value"]<=(self.catalog.cards[cid].kb.get("max_seats") or float("inf"))}
                if fit:
                    owned_editions={(p["family_id"],p.get("edition")) for p in profile.owned if p.get("family_id")}
                    rel={cid:score for cid,score in fit.items()
                         if (self.catalog.cards[cid].family,self.catalog.cards[cid].offers[0].edition) in owned_editions
                         or (self.catalog.cards[cid].family,None) in owned_editions} or fit
                elif not related and any(self.kb.rows["families"].get(fid,{}).get("upgrade_to") in f.get("family",[]) for fid in owned_ids):
                    active["action"]="new"
                    notes.append("Купленная лицензия относится к другой линейке. Для перехода рассчитана новая покупка.")
                elif related:
                    cats={self.catalog.cards[cid].category for cid in related}
                    vendors={self.catalog.cards[cid].vendor for cid in related}
                    upgrades={self.catalog.cards[cid].kb.get("upgrade_to") for cid in related}-{None}
                    rel={cid:.9 for fid in upgrades for cid in self.catalog.by["family"].get(fid,())} or {
                        cid:.8 for cid,c in self.catalog.cards.items() if c.category in cats and c.vendor in vendors and cid not in related}
                    active["action"]="new"
                    notes.append("Запрошенное количество превышает предел купленной линейки. Для перехода показана новая покупка.")
            elif owned_ids:
                rel={cid:.9 for fid in owned_ids for cid in self.catalog.by["family"].get(fid,())}

        relaxed_qty=False
        def collect():
            selected={}
            for cid in rel:
                card=self.catalog.cards[cid]
                selection=select(card,profile,active,exc,qty,exact_offers.get(cid),relaxed_qty)
                if selection:
                    selected[cid]=selection
            return selected
        selected=collect()
        if len(selected)<3 and rel and not sku:
            for key in ("platform","registry","certs","model","edition","price_max","term_months"):
                if key not in active:
                    continue
                trial={k:v for k,v in active.items() if k!=key}
                count=sum(select(self.catalog.cards[cid],profile,trial,exc,qty) is not None for cid in rel)
                if count>len(selected):
                    drop={"term_months":"term","price_max":"price"}.get(key,key)
                    label={"registry":"реестр ПО","certs":"сертификаты","model":"модель лицензии"}.get(key,LABEL.get(key,key))
                    relax_hints.append(dict(drop=drop,label="Снять условие «"+label+"»",count=count,apply=dict(ignore=list(dict.fromkeys([*req.ignore,drop])))))
        if not selected and intent=="promo":
            active.pop("promo",None)
            selected=collect()
        if not selected and intent=="license_ops" and active.get("action") in ("addon","upgrade","crossgrade"):
            active["action"]="new"
            notes.append("Вариант изменения лицензии отсутствует. Показана стоимость новой покупки.")
            selected=collect()
        if not selected and rel and not sku:
            for key in LABEL:
                if key=="quantity" and qty:
                    relaxed_qty=True
                elif key in active and key!="audience":
                    del active[key]
                else:
                    continue
                notes.append("Для подбора других вариантов снято условие «"+LABEL[key]+"».")
                selected=collect()
                if selected:
                    break
        t.add("filters","Проверка ограничений"," ".join(notes) or "Условия запроса сохранены")
        t.add("variants","Выбор лицензии",f"Подобрано вариантов для карточек · {len(selected)}"+(f". Запрошено мест · {qty['value']}" if qty else ""))
        rr=[]
        exact_title=corrected in self.exact_titles
        if smart and not sku and not exact_title and selected and intent not in ("sku","account","spec_list") and all(c["ok"] for c in calls):
            window=sorted(selected,key=lambda c:-rel[c])[:30]
            rr=self.decisions.rerank(sid,req.source,{**state,"сценарий":intent},[dict(card_id=c,title=self.catalog.cards[c].title,license=selected[c][0].name,
                                                                 price=selected[c][0].price) for c in window])
            calls.extend(rr)
            if all(c["ok"] for c in rr):
                for batch in rr:
                    for cid,p in batch["probabilities"].items():
                        rel[cid]=.5*rel[cid]+.5*(p.get("yes",0)+.5*p.get("part",0))
        failed=any(not m["ok"] for m in calls)
        if failed and rr and any(m["ok"] for m in calls if m["kind"]=="intent") and not prior_calls:
            retry_trace=Trace(self.timer)
            retry_trace.start=t.start
            return self._search(req,profile,retry_trace,rules,redirect,persist,sid,calls)
        if failed:
            notes.append("Использован локальный поиск. "+next(m["note"] for m in calls if not m["ok"]))
        t.add("rerank","Проверка категоризатором","Использованы оценки модели" if rr and not failed else "Использованы локальные оценки",
              "fallback" if failed else "ok" if rr else "skip",calls=[m for m in calls if m["kind"]=="rerank"])
        weights={**WEIGHTS,**(self.controls.weights() or {}),**(req.weights or {})}
        cards=[ranked(self.catalog.cards[c],s,float(rel[c]),bool(sku or ("family" in f and "edition" in active)),profile,weights,self.kb) for c,s in selected.items()]
        if intent=="task":
            task=scenarios.reference(self,"use_case",corrected,entities)
            for card in cards:
                if task.get("phrases") and (self.catalog.cards[card["card_id"]].family in task.get("families",[]) or card["category"]["id"] in task.get("categories",[])):
                    card["score"]["why"].append("Решает задачу «"+task["phrases"][0]+"»")
        if not requested_qty:
            for card in cards:
                calc=card.get("calc") or {}
                if card["offer"]["action"]=="renewal" and calc.get("qty") is not None:
                    card["score"]["why"].append("Количество для продления взято из купленной лицензии")
        cards.sort(key=lambda c:(c["score"]["tier"],-c["score"]["score"],c["card_id"]))
        if inherited and "дешев" in norm:
            cards.sort(key=lambda c:(c["score"]["tier"],(c.get("calc") or {}).get("total") or c["offer"]["price"] or float("inf")))
        if req.sort in ("price_asc","price_desc"):
            cards.sort(key=lambda c:(c["score"]["tier"],c["offer"]["price"] is None,(c["offer"]["price"] or 0)*(1 if req.sort=="price_asc" else -1)))
        if plan in ("category","broad") and not req.sort:
            cards=diversify(cards)
        for i,c in enumerate(cards,1):
            c["position"]=i
        t.add("business","Порядок карточек","В каждой полосе учтены популярность, маржа и профиль клиента",weights=weights)
        merch=self.controls.merch(ctx,[] if plan=="out_of_catalog" else cards)
        if plan!="out_of_catalog":
            cards=merch["cards"]
        fired=merch["fired"]
        pinned={item.get("card_id") for item in fired if item["kind"]=="pin"}
        ordered=iter(sorted((c for c in cards if c["card_id"] not in pinned),key=lambda c:c["score"]["tier"]))
        cards=[c if c["card_id"] in pinned else next(ordered) for c in cards]
        for i,c in enumerate(cards,1):
            c["position"]=i
            if c["card_id"] in pinned:
                c["score"]["why"].append("Закреплено правилом магазина")
        t.add("merch","Правила магазина"," · ".join(item["summary"] for item in fired) or "Правила не сработали",
              "ok" if fired else "skip",fired=fired)
        blocks=[]
        if plan in ("product","vendor","category") and profile.owned:
            owned_rows=[]
            for card in cards:
                history=next((p for p in profile.owned if p.get("family_id")==self.catalog.cards[card["card_id"]].family and p.get("offer_id")),None)
                if history and card["offer"]["action"]=="renewal":
                    owned_rows.append(dict(title=card["title"],qty=history.get("qty"),expires_in_days=history.get("expires_in_days"),renew_offer=card["offer"]))
            if owned_rows:
                blocks.append(dict(type="my_licenses",title="Ваши лицензии",items=owned_rows))

        if plan=="off_topic":
            common=Counter(c.category for c in self.catalog.cards.values())
            blocks.append(dict(type="categories",title="Категории программ",items=[dict(id=k,title=self.names["category"].get(k,k),count=n) for k,n in common.most_common(5) if k]))
        if plan=="broad":
            options=[dict(label=c["title"],apply=dict(q=c["title"])) for c in cards[:2]]
            if not options:
                options=[dict(label=r["title"],apply=dict(q=r["title"])) for r in list(self.kb.rows["categories"].values())[:2]]
            blocks.append(dict(type="clarify",title="Уточните запрос",question="Какой продукт вам нужен?",options=options))
        if plan=="out_of_catalog":
            fid=next(iter(f.get("family",[])),None)
            vid=self.kb.rows["families"].get(fid,{}).get("vendor") or next(iter(f.get("vendor",[])),None)
            title=self.names["family"].get(fid) or self.names["vendor"].get(vid,vid)
            status=self.kb.rows["vendors"].get(vid,{}).get("market_status")
            reason="vendor_left" if status=="left" else "not_in_catalog_known"
            blocks.append(dict(type="not_in_catalog",title=title,reason={"left":"vendor_left","restricted":"restricted"}.get(status,"gap"),text=f"{title} отсутствует в демокаталоге."))
        page=cards[(req.page-1)*req.page_size:req.page*req.page_size]
        if cards:
            if plan=="out_of_catalog":
                blocks.append(dict(type="analogs",title="Возможные замены",source=dict(title=title,status="unavailable",note=""),items=[dict(card=c,note="Близкий продукт по базе знаний") for c in page]))
            else:
                blocks.append(dict(type="products",title="Подходящие лицензии",total=len(cards),items=page))
        elif plan in {"account","spec_list"}:
            pass
        elif plan=="off_topic":
            msg={"hardware":"В каталоге представлены программы и лицензии. Для какого ПО вы подбираете устройство?",
                 "piracy":"Здесь можно подобрать лицензионное ПО."}.get(reason,"Укажите название программы или задачу, например «защита рабочих мест».")
            blocks.append(dict(type="clarify",title="Поиск программного обеспечения",question=msg,options=[]))
        else:
            reason=reason or ("sku_not_found" if plan=="sku" and not sku else "filters_too_strict")
            notes.append("Артикул отсутствует в каталоге." if reason=="sku_not_found" else "Подходящих предложений по заданным условиям нет.")
        if not cards and plan=="sku" and not sku:
            near=process.extract(sku_key(norm),self.catalog.skus.keys(),limit=3,score_cutoff=65)
            if near:
                options=[dict(label=self.catalog.skus[k].sku,apply=dict(q=self.catalog.skus[k].sku)) for k,_,_ in near]
                blocks.append(dict(type="clarify",title="Похожие артикулы",question="Проверьте обозначение в вашем заказе.",options=options))
        if plan=="out_of_catalog" or (not cards and plan not in {"account","spec_list","off_topic"}):
            blocks.append(dict(type="lead",title="Запрос поставки",text="Можно уточнить условия у менеджера.",action="request_quote"))
        def run_line(line):
            child=req.model_copy(update=dict(q=line.replace(","," "),mode="fast",page=1,page_size=3,session_id=""))
            return self._search(child,profile,Trace(self.timer),rules,persist=False)
        blocks=scenarios.compose(self,intent,req,f,entities,qty,cards,profile,blocks,run_line,reason)
        if persist:
            extra=companions(self,intent,cards,profile,weights,f,exc)
            if extra:
                blocks.append(extra)
        t.add("compose","Сборка ответа",f"Карточек в выдаче · {len(cards)}")
        facets=[]
        for key,label in [("vendor","Вендор"),("category","Категория")]:
            counts=Counter(c[key]["id"] for c in cards)
            facets.append(dict(key=key,title=label,values=[dict(id=k,label=self.names[key].get(k,k),count=n) for k,n in counts.most_common() if k]))
        result=dict(search_id=sid,mode="fast" if failed else req.mode,engine="kuznitsa",relax_hints=relax_hints,banners=merch["banners"],engine_version="0.1.0",query=dict(raw=req.q,normalized=original_norm,corrected=corrected,
                    corrections=changes,did_you_mean=None),understood=dict(intent=intent,intent_title=TITLES[intent],intent_conf=intent_conf,
                    intent_source=intent_source,inherited=inherited,entities=entities,filters=f,exclude=exc,qty=requested_qty,chips=chips,subtype=reason if intent=="off_topic" else None,reason=(next((b["reason"] for b in blocks if b["type"]=="not_in_catalog"),reason) if intent=="out_of_catalog" else reason),
                    agent_note=TITLES[intent]+(" · "+", ".join(x["label"] for x in chips) if chips else "")),blocks=blocks,facets=facets,
                    related_queries=list(dict.fromkeys(c["title"] for c in cards if c["title"].lower()!=norm))[:4],notes=notes,trace=t.steps,
                    cost=dict(llm_calls=sum(m["sent"] for m in calls),cached=sum(m["cached"] for m in calls),tokens_in=sum(m["tokens_in"] for m in calls),usd=sum(m["usd"] for m in calls),rub=sum(m["usd"] for m in calls)*self.usd_rub),timing_ms=dict(total=round((self.timer()-t.start)*1000,2)),
                    profile=dict(id=profile.client_id,title=profile.title,segment=profile.segment))
        t.add("log","Журнал и стоимость","Запись поиска в журнал. Расходы на внешние модели · 0 ₽")
        started=self.timer()
        if persist:
            if self.sessions:
                self.sessions.save(req,result,cards)
            self.journal.search(self.clock(),req,result,len(cards),reason,relaxed_qty or bool(notes and selected and plan!="sku"))
        t.steps[-1]["ms"]=round((self.timer()-started)*1000,2)
        result["timing_ms"]["total"]=round((self.timer()-t.start)*1000,2)
        if not req.explain:
            result["trace"]=[]
        return result
