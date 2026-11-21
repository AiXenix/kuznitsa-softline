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
from .config import Config,WEIGHTS,MODE_TITLES
from .data_lock import snapshot_lock
from .schema import Client,Request
from .index.store import Catalog
from .kb.loader import load
from .kb.lexicon import Lexicon
from .suggest.index import SuggestIndex
from .text import normalize,sku_key,tokens,lemma
from collections import defaultdict
from .understand.refine import refine,apply_profile,resolve_details,nested_family
from .understand.repair import repair
from .understand.normalize import lookup_skus
from .understand.entities import extract
from .understand.model import chips_for, ignore_conditions
from .understand.intent import TITLES
from .rank.variants import select,public_offer,select_for_workplaces
from .rank.business import ranked
from .rank.fit import TIERS, preference, analog_scope
from .plans.presentation import profile_info,next_queries
from .plans.alternatives import restricted,merch_secondary
from .rank.diversity import diversify
from .plans.base import candidates
from .llm.recovery import ask_recovery,cost_summary
from .llm.advice import questions_for,card_facts,category_options
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
                      for k,g in dict(vendor="vendors",family="families",category="categories",role="roles",industry="industries").items()}
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
        from .understand.spell_index import brand_products
        self.brand_products=brand_products(self)
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
                from .understand.spell_index import phonetics
                phonetics(lex,self.kb)
                lex.spell_words = sorted(w for w in lex.words if len(w)>=4)
                from .understand.spell_index import spell_terms
                lex.roman=spell_terms(lex)
                self._phrases = PhraseRules(r for r in rules if r["kind"] == "text")
                recent=()
                if isinstance(self.journal,Journal):
                    recent=[r["q_norm"] for r in self.journal.rows(
                        "SELECT q_norm FROM searches WHERE source IN ('ui','api','gallery','history') ORDER BY rowid DESC LIMIT 2500")]
                self.suggestions = SuggestIndex(lex,self.names,self.kb,self.catalog,recent)
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
        kb = load(cfg.kb,cfg.data)
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
            card["score"]["tier_label"]=TIERS[card["score"]["tier"]]
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
        trace.add("retrieve",MODE_TITLES["naive"],f"Все слова встретились в названиях {len(offers)} предложений")
        start = (req.page-1)*req.page_size
        cards = [naive.card(self,o,i) for i,o in enumerate(offers[start:start+req.page_size], start+1)]
        trace.add("compose","Выдача по популярности",f"Предложений на странице · {len(cards)}")
        result = dict(search_id="s_"+uuid4().hex, mode="naive", engine="naive", engine_version="0.1.0",
                      query=dict(raw=req.q,normalized=req.q.lower(),corrected=req.q,corrections=[],did_you_mean=None),
                      understood=dict(intent="product",intent_title=MODE_TITLES["naive"],intent_conf=0.,intent_source="fallback",
                                      filters={},exclude={},qty=None,entities=[],chips=[],agent_note="Ищу все слова в названии SKU"),
                      blocks=[dict(type="products",title="Предложения",items=cards,total=len(offers))],
                      banners=[],relax_hints=[],facets=[],related_queries=[],notes=[],trace=trace.steps,cost=cost_summary([],self.usd_rub),
                      timing_ms=dict(total=round((self.timer()-trace.start)*1000,2)),
                      profile=profile_info(profile))
        zero=None if offers else "unknown_term"
        result["understood"]["zero_reason"]=zero
        for card in cards:
            card["score"]["tier_label"]=TIERS[card["score"]["tier"]]
        self.journal.search(self.clock(),req,result,len(offers),zero,False)
        result["timing_ms"]["total"]=round((self.timer()-trace.start)*1000,2)
        if not req.explain:
            result["trace"]=[]
        return result

    def _search(self, req, profile, t, rules, redirect=None, persist=True, sid=None, prior_calls=()):
        sid=sid or "s_"+uuid4().hex
        calls=list(prior_calls)
        deadline=perf_counter()+max(0,.60-(self.timer()-t.start))
        lex, phrases = rules
        raw = redirect["q"] if redirect else req.q
        original_norm = normalize(req.q)
        norm, synonyms = phrases.apply(normalize(raw))
        category = req.category if not ({"category","context"} & set(req.ignore) or req.context=="off") else None
        t.add("normalize","Нормализация",norm or "Пустой запрос")
        exact_offers=lookup_skus(self.catalog,raw) or lookup_skus(self.catalog,norm)
        sku_prefix=False
        if not exact_offers and re.fullmatch(r"[a-zа-я]{1,5}[- ]?\d{3,}",norm):
            for offer in self.catalog.prefix_skus(norm):
                exact_offers.setdefault(offer.card_id,offer)
            sku_prefix=bool(exact_offers)
        sku=next(iter(exact_offers.values()),None)
        t.add("sku_lookup","Точный артикул",", ".join(o.sku for o in exact_offers.values()) or "Совпадений по артикулу нет")
        words,changes= (tokens(norm),[]) if sku or req.verbatim else repair(norm,lex)
        corrected=" ".join(words) if changes else norm
        t.add("repair","Проверка написания",", ".join(x["from"]+" → "+x["to"] for x in changes) or "Запрос сохранён",candidates=changes,criterion="Близость написания, длина совпавшего начала и популярность в каталоге")
        f,exc,entities,qty,residual=extract(words,lex,self.kb)
        nested=nested_family(lex,words,entities)
        if nested:
            entities.append(nested)
            f["family"]=[nested["id"]]
        if sku:
            f,exc,entities={}, {}, []
        qty=refine(self,words,f,exc,entities,qty)
        resolve_details(self,lex,words,f,entities,qty)
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
        if intent=="task":
            task=scenarios.reference(self,"use_case",corrected,entities)
            if task.get("categories"):
                f["category"]=task["categories"][:1]
        if intent=="category" and not (f.get("category") or f.get("family") or f.get("vendor") or qty or category or f.get("registry") or f.get("model")):
            intent="off_topic"
        if intent in ("product","compliance","category") and f.get("family") and f.get("registry") and any(
                self.kb.rows["vendors"].get(self.kb.rows["families"].get(fid,{}).get("vendor"),{}).get("origin")=="foreign"
                for fid in f["family"]):
            intent="analog"
        lead_family=None
        completed_brand=(intent=="vendor" and changes and changes[0]["kind"]=="prefix")
        if (intent=="broad" or completed_brand) and len(words)==1 and changes and changes[0]["kind"] in ("layout","prefix"):
            from .understand.spell_index import leading_product
            fid=leading_product(self,corrected,f.get("vendor",[]))
            if completed_brand:
                lead_family=fid
            elif fid:
                f.pop("vendor",None)
                f["family"]=[fid]
                if not any(e["type"]=="family" and e["id"]==fid for e in entities):
                    entities.append(dict(type="family",id=fid,text=self.names["family"][fid],span=[0,len(words)],source="prefix",conf=.8))
                    chips.append(dict(key="family",label=self.names["family"][fid],source="query",removable=False))
                intent="product"
        if not any(f.get(k) for k in ("vendor","family","category")) and (exc.get("vendor") or exc.get("family")):
            intent="analog"
        code_search=intent in ("compliance","sku") and not sku and bool(re.search(r"реестр.*\d|окпд2|ктру",norm))
        regulations=[self.kb.rows["compliance"].get(e["id"],{}) for e in entities if e["type"]=="compliance"]
        reference_rule=bool(regulations) and all(not r.get("effect") and r.get("explain") for r in regulations)
        reference_only=intent=="compliance" and reference_rule and not any(f.get(k) for k in ("family","vendor","category","registry","certs"))
        if code_search and not reference_rule:
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
        if intent=="off_topic" and not re.search(HARDWARE+"|"+PIRACY,corrected) and not entities and len(words)>1:
            nearest=self.catalog.dense.nearest_knowledge(corrected,threshold=.73)
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
        rejected=[]
        rules_intent=intent
        evidence=bool(entities or category or inherited or intent_source=="embed")
        branches=category_options(self,entities,f,profile,corrected) if smart and intent=="category" and not category else []
        uncertain_category=(intent in ("compliance","category") and not f.get("category") and not f.get("family"))
        uncertain_embedding=intent_source=="embed" and intent_conf<.85
        if smart and not sku and corrected not in self.exact_titles and not reference_only and (evidence or intent=="question" and self.knowledge.nearest("faq",corrected)) and (intent in ("broad","question","task") or uncertain_category or uncertain_embedding or branches):
            owned_products=[self.kb.rows["families"].get(o.get("family_id"),{}) for o in profile.owned]
            state.update(установлено=[r.get("title",r.get("name")) for r in owned_products if r.get("category") in branches],
                         отрасль=self.kb.rows["industries"].get(profile.industry,{}).get("title",profile.industry),парк=profile.fleet.get("os",[]),исходный_сценарий=intent)
            questions=questions_for(self,intent,corrected,entities,f,state,branches)
            answers,meta=self.decisions.decide_before(deadline,sid,req.source,"intent",state,questions)
            meta["probabilities"]={k:a["probabilities"] for k,a in answers.items()}
            calls.append(meta)
            for k,a in answers.items():
                val=a["choice"]
                prob=float(a["probabilities"][val])
                if val=="none" or prob<.55:
                    continue
                if k=="intent":
                    if val!=intent and (prob<(.85 if evidence else .55) or intent in ("question","task","compliance","category") or
                            any(e["type"]=="use_case" for e in entities) or val=="product" and not f.get("family") or val=="off_topic" and evidence):
                        rejected.append(dict(choice=val,probability=prob,reason="Исходная цель подтверждена запросом"))
                    else:
                        intent,intent_conf,intent_source=val,prob,"jev"
                elif k=="category" and val in branches and prob>=.85:
                    f["category"]=[val]
                    intent_source,intent_conf="jev",prob
                elif k=="category" and prob>=(.85 if intent=="compliance" else .55) and not f.get("category") and intent in ("category","task","compliance") and not any(e["type"]=="use_case" for e in entities):
                    f["category"]=[val]
                elif k=="faq":
                    entities.insert(0,dict(type="faq",id=val,text=corrected,span=[0,len(words)],source="jev",conf=prob))
        if not reference_only:
            apply_profile(profile,f,intent)
        for ignored in req.ignore:
            f.pop(ignored,None)
        plan=intent
        if plan=="product" and f.get("family"):
            named=f["family"]
            unavailable=[fid for fid in named if not self.catalog.by["family"].get(fid)]
            sold=[fid for fid in named if fid not in unavailable]
            # Несколько имён могут обозначать предшественника и его преемника.
            if sold and unavailable:
                named_words=set(tokens(norm))-{"купить","лицензия","стоимость","цена","скачать"}
                source=next((fid for fid in unavailable if named_words and named_words<=set(tokens(self.kb.rows["families"].get(fid,{}).get("name","")))),None)
                if source:
                    intent=plan="analog"
                    f["family"]=[source]
                else:
                    f["family"]=sold
        if plan=="product" and f.get("family") and not any(self.catalog.by["family"].get(fid) for fid in f["family"]):
            plan=intent="out_of_catalog"
        scores=None
        if plan=="vendor" and not any(self.catalog.by["vendor"].get(v) for v in f.get("vendor",[])):
            plan=intent="out_of_catalog"
        reason=None
        if intent=="off_topic":
            reason="hardware" if re.search(HARDWARE,corrected) else "piracy" if re.search(PIRACY,raw.lower()+" "+corrected) else "gibberish" if not entities and re.fullmatch("[a-z ]*",corrected) else "other"
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
        t.add("intent","Сценарий запроса",summary,"fallback" if any(not c["ok"] for c in calls) else "ok",redirect=redirect,source=intent_source,probability=intent_conf,rules=rules_intent,rejected=rejected,calls=[m for m in calls if m["kind"]=="intent"])
        t.add("plan","План поиска",TITLES[plan] if intent==plan else f"{TITLES[intent]} · использую план «{TITLES[plan]}»","ok" if intent==plan else "fallback")
        anchor_filters=f
        if plan=="analog" and not f.get("family") and not f.get("vendor") and (exc.get("vendor") or exc.get("family")):
            anchor_filters={**f,**{k:v for k,v in exc.items() if k in ("vendor","family")}}
        special=scenarios.scope(self,intent,anchor_filters,entities,corrected,profile,qty)
        if scores is None:
            need_text=special is None and not sku and not f.get("family") and plan not in {"out_of_catalog","sku","off_topic"}
            # После распознавания раздела сравниваем характеристики внутри него.
            # Смысловой поиск остаётся для запросов без подтверждённой области.
            scoped=plan in ("category","vendor","compliance") and bool(f.get("category") or f.get("vendor")) and intent_source!="embed"
            scores=self.catalog.scores(corrected or " ",semantic=not scoped) if need_text and not code_search and not reference_only else {}
        rel=dict.fromkeys(exact_offers,1.) if sku else special if special is not None else candidates(self.catalog,self.kb,plan,f,scores,None)
        if lead_family:
            rel={cid:(1. if self.catalog.cards[cid].family==lead_family else min(.65,score)) for cid,score in rel.items()}
        if reference_only:
            rel={}
        elif code_search:
            rel=candidates(self.catalog,self.kb,"category",f,{},None)
        if plan in ("analog","out_of_catalog"):
            rel=analog_scope(self,rel,anchor_filters,exc,"дешев" in corrected)
        t.add("retrieve","Отбор кандидатов",f"Подходящих карточек до проверки лицензий · {len(rel)}",
              sources=["Артикул"] if sku else ["Сущности","Совпадения по полям","Фрагменты слов"]+(["Смысл запроса"] if self.catalog.dense.matrix is not None else []))
        # Карточка уже проверена по семейству, вендору и дереву категорий.
        active={k:v for k,v in f.items() if k not in {"family","vendor","category"}}
        notes=[]
        if plan=="question" and active.get("audience")=="home" and re.search(r"в офисе|юрлиц|организаци|\bооо\b",corrected):
            active["audience"]="business"
            active.pop("edition",None)
            notes.append("Для покупки организацией показаны коммерческие лицензии.")
        if plan in ("analog","out_of_catalog","role_kit","industry"):
            active["action"]="new"
        if plan in ("role_kit","industry"):
            active.pop("metric",None)
            active.pop("edition",None)
        relax_hints=[]
        if sku_prefix:
            notes.append("Найдены предложения с таким началом артикула.")
        if code_search and not reference_rule:
            notes.append("Точный регистрационный номер в каталоге не подтверждён. Показан подбор по признаку включения в реестр.")
        if intent=="renewal" and f.get("vendor") and not any(e["type"]=="family" and len(e["text"].split())>1 for e in entities):
            owned={p.get("family_id") for p in profile.owned if self.kb.rows["families"].get(p.get("family_id"),{}).get("vendor") in f["vendor"]}
            if owned and not any(e["type"]=="family" for e in entities):
                rel={cid:.94 for fid in owned for cid in self.catalog.by["family"].get(fid,())}
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
            if re.search("поддержк",corrected) and any(any(o.lic.action=="support" for o in self.catalog.cards[cid].offers) for cid in rel):
                active["action"]="support"
        if qty and f.get("family"):
            upgrades={self.catalog.cards[c].kb.get("upgrade_to") for c in rel if (self.catalog.cards[c].kb.get("max_seats") or float("inf"))<qty["value"]}
            extra={cid:.88 for fid in upgrades for cid in self.catalog.by["family"].get(fid,())}
            if extra:
                rel.update(extra)
                active["action"]="new"
                notes.append("Запрос превышает предел младшей линейки. Показана новая покупка старшей линейки.")
        upgrade_rows=[]
        if qty and plan in ("category","product") and rel:
            visible_families={self.catalog.cards[cid].family for cid in rel}
            for owned in profile.owned:
                row=self.kb.rows["families"].get(owned.get("family_id"),{})
                target=row.get("upgrade_to")
                if target in visible_families and 0<(row.get("max_seats") or 0)<qty["value"]:
                    message=f"У вашей лицензии {row['name']} предел {row['max_seats']} мест. Для {qty['value']} мест нужен переход на {self.names['family'][target]}."
                    notes.append(message)
                    upgrade_rows.append(dict(title=message,qty=owned.get("qty"),expires_in_days=owned.get("expires_in_days"),
                                             card_id=owned.get("card_id"),offer_id=owned.get("offer_id"),renew_offer=None))
                    for cid in self.catalog.by["family"].get(target,()):
                        if cid in rel:
                            rel[cid]=1.
        requested_qty=qty
        if plan=="category" and qty and not f.get("action") and profile.owned:
            # Докупка для меньшего числа рабочих мест к действующей крупной установке.
            for cid in rel:
                card=self.catalog.cards[cid]
                owned=next((p for p in profile.owned if p.get("family_id")==card.family and (p.get("qty") or 0)>qty["value"]*2),None)
                if owned and any(o.lic.action=="addon" for o in card.offers):
                    rel[cid]=max(rel[cid],.91)
        if intent in ("role_kit","industry") and not qty and profile.client_id!="guest":
            qty=dict(value=profile.size_seats,metric=None)
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
                selection=select_for_workplaces(card,profile,active,exc,qty) if plan in ("role_kit","industry") else None
                if plan=="category" and qty and not active.get("action") and any(p.get("family_id")==card.family and
                        (p.get("qty") or 0)>qty["value"]*2 for p in profile.owned):
                    selection=select(card,profile,{**active,"action":"addon"},exc,qty)
                if selection is None:
                    selection=select(card,profile,active,exc,qty,exact_offers.get(cid),relaxed_qty)
                if selection:
                    selected[cid]=selection
            return selected
        selected=collect()
        if plan=="license_ops" and active.get("action")=="addon":
            owned_ids={p["family_id"] for p in profile.owned if p.get("family_id")}
            qualified={cid:sel for cid,sel in selected.items() if self.catalog.cards[cid].family in owned_ids}
            retained=dict(qualified)
            for cid in rel.keys()-qualified.keys():
                card=self.catalog.cards[cid]
                if owned_ids and f.get("vendor"):
                    owned_categories={self.kb.rows["families"].get(fid,{}).get("category") for fid in owned_ids
                                      if self.kb.rows["families"].get(fid,{}).get("vendor") in f["vendor"]}
                    if owned_categories and card.category not in owned_categories:
                        continue
                trial=select(card,profile,{**active,"action":"new"},exc,qty)
                if trial:
                    retained[cid]=trial
            selected=retained
            if retained:
                notes.append("Докупка привязана к приобретённой линейке. Для других продуктов указана стоимость новой лицензии.")
        strict_empty=not selected
        missing=[]
        outside=set()
        if qty and plan in ("product","category","vendor","compliance") and not sku:
            for cid in rel.keys()-selected.keys():
                card=self.catalog.cards[cid]
                trial=select(card,profile,active,exc,qty,relax_qty=True)
                if trial:
                    outside.add(cid)
                    selected[cid]=(trial[0],None,trial[2])
        if outside and strict_empty:
            relax_hints.append(dict(drop="qty",label="Посмотреть все диапазоны количества",count=len(outside),apply=dict(ignore=[*req.ignore,"qty"])))
        audience_choices={}
        if strict_empty and f.get("audience") in ("edu","gov","nonprofit","med") and not sku:
            standard={**active,"audience":"business"}
            for cid in rel:
                selection=select(self.catalog.cards[cid],profile,standard,exc,qty)
                if selection:
                    audience_choices[cid]=selection
            if audience_choices:
                relax_hints.append(dict(drop="audience",label="Посмотреть обычные коммерческие лицензии",count=len(audience_choices),
                                        apply=dict(ignore=[*req.ignore,"audience"])))
        recovery=None
        clarify_class=None
        if smart and strict_empty and not reference_only and len(calls)<2 and plan not in ("account","spec_list","promo","service") and not sku and all(m["ok"] for m in calls):
            options={}
            if outside:
                options["qty"]="Показать ближайший диапазон количества для того же продукта"
            if audience_choices:
                options["audience"]="Показать обычные лицензии с пометкой об отсутствии льготы"
            class_matches={}
            if plan=="category" and not category and not f.get("family") and branches:
                # Второй выбор ограничен классами, для которых в каталоге
                # действительно нашлись SKU со всеми исходными условиями.
                probabilities=next((m.get("probabilities",{}).get("category",{}) for m in calls if m["kind"]=="intent"),{})
                for cid,p in sorted(probabilities.items(),key=lambda kv:-kv[1]):
                    if cid not in branches or cid in f.get("category",[]) or p<.15:
                        continue
                    variants={k:s for k in self.catalog.by["category"].get(cid,()) if (s:=select(self.catalog.cards[k],profile,active,exc,qty))}
                    if variants:
                        key="category_"+cid
                        class_matches[key]=(cid,variants)
                        titles=", ".join(self.catalog.cards[k].title for k in sorted(variants)[:2])
                        options[key]=f"Сохранить условия закупки и предложить {self.names['category'][cid]} ({titles})"
            sample=[self.catalog.cards[c].title for c in sorted(rel,key=rel.get,reverse=True)[:3]]
            recovery=ask_recovery(self,deadline,sid,req,state,calls,t.steps,options,sample)
            # При неоднозначном запросе сохраняем условия закупки и предлагаем
            # подтвердить единственную найденную в каталоге трактовку.
            provisional=(recovery=="clarify" and len(class_matches)==1 and not selected and not audience_choices)
            if recovery in class_matches or provisional:
                recovered_class,selected=class_matches[next(iter(class_matches)) if provisional else recovery]
                previous_class=next(iter(f.get("category",[])),None)
                if provisional and previous_class:
                    clarify_class=[previous_class,recovered_class]
                rel=dict.fromkeys(selected,.70)
                f["category"]=[recovered_class]
                ctx["category_id"]=recovered_class
                decision=next(step for step in t.steps if step["step"]=="intent")
                decision["detail"]["suggested_category"]=recovered_class
                label=self.names["category"][recovered_class]
                notes.append(f"Возможно, вы имели в виду раздел «{label}». Здесь нашлись предложения с указанными условиями." if provisional
                             else f"По условиям закупки подобран раздел «{label}».")
        if audience_choices and (not selected or recovery=="audience"):
            selected=audience_choices
            outside.clear()
            missing=["audience"]
            notes.append("Льготная лицензия на заданное количество отсутствует. Ниже обычные коммерческие лицензии без льготы.")
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
        if selected and plan=="license_ops" and active.get("action")=="addon" and qty and f.get("vendor"):
            # Даже когда к младшей линейке нет отдельного addon-SKU, из ответа
            # видно, к какой покупке добавляют места и почему предлагается новая.
            for h in profile.owned:
                row=self.kb.rows["families"].get(h.get("family_id"),{})
                if row.get("vendor") in f["vendor"]:
                    name=row.get("title") or row["name"]
                    notes.append(f"У организации {h.get('qty') or 'несколько'} мест {name}. Дополнительных мест запрошено: {qty['value']}.")
        if not selected and plan=="sku" and not sku and f.get("family"):
            notes.append("Точный артикул не найден. Ниже другие предложения указанного семейства.")
            rel={cid:.54 for fid in f["family"] for cid in self.catalog.by["family"].get(fid,())}
            selected=collect()
        if not selected and plan=="product" and f.get("family") and not f.get("action") and not sku:
            conditional={"renewal":"продление","upgrade":"переход","addon":"дополнительные места","crossgrade":"переход с другого продукта","support":"сопровождение"}
            for action,label in conditional.items():
                variants={cid:s for cid in rel if (s:=select(self.catalog.cards[cid],profile,{**active,"action":action},exc,qty))}
                if variants:
                    selected=variants
                    notes.append(f"Показано предложение на {label}. Право на эти условия нужно подтвердить.")
                    break
        if not selected and intent=="promo":
            active.pop("promo",None)
            selected=collect()
        if not selected and intent=="license_ops" and active.get("action") in ("addon","upgrade","crossgrade"):
            active["action"]="new"
            notes.append("Вариант изменения лицензии отсутствует. Показана стоимость новой покупки.")
            selected=collect()
        if not selected and plan=="question" and f.get("family"):
            active.pop("registry",None)
            selected=collect()
        if not selected and rel and not sku:
            for key in (*LABEL,"model"):
                if key=="quantity" and qty:
                    relaxed_qty=True
                elif key in active and key!="audience" and not (plan=="analog" and key=="price_max"):
                    del active[key]
                else:
                    continue
                notes.append("Для подбора других вариантов снято условие «"+LABEL.get(key,"модель лицензии")+"».")
                selected=collect()
                if selected:
                    break
        if not selected and rel and not sku:
            # Предлагаем альтернативы с явно обозначенной непроверенной характеристикой.
            for condition in ("platform","certs","registry","metric"):
                if condition not in active or condition in req.filters or condition in ("registry","certs") and plan=="compliance":
                    continue
                trial={k:v for k,v in active.items() if k!=condition}
                possible={cid:s for cid in rel if (s:=select(self.catalog.cards[cid],profile,trial,exc,qty))}
                if possible:
                    selected=possible
                    missing=[condition]
                    label={"registry":"включение в реестр","certs":"сертификат","platform":"платформа","metric":"метрика лицензии"}[condition]
                    notes.append("Нуждается в подтверждении: "+label+".")
                    if not any(h["drop"]==condition for h in relax_hints):
                        relax_hints.append(dict(drop=condition,label="Снять условие «"+label+"»",count=len(selected),apply=dict(ignore=[*req.ignore,condition])))
                    break
        t.add("filters","Проверка ограничений"," ".join(notes) or "Условия запроса сохранены")
        t.add("variants","Выбор лицензии",f"Подобрано вариантов для карточек · {len(selected)}"+(f". Запрошено мест · {qty['value']}" if qty else ""))
        rr=[]
        pre_rerank=rel.copy()
        exact_title=corrected in self.exact_titles
        if smart and len(calls)<2 and not sku and not exact_title and len(selected)>3 and not any(selection[0].lic.action=="renewal" and selection[2] for selection in selected.values()) and not f.get("edition") and (self.timer()-t.start)<.40 and intent not in ("sku","account","spec_list","renewal","license_ops","role_kit","industry","compare","service","promo","out_of_catalog","analog") and all(c["ok"] for c in calls):
            window=sorted(selected,key=lambda c:-rel[c])[:30]
            rr=self.decisions.rerank(sid,req.source,{**state,"сценарий":intent},[card_facts(self,c,selected[c][0],f) for c in window],deadline=deadline)
            calls.extend(rr)
            if all(c["ok"] for c in rr):
                for batch in rr:
                    for cid,p in batch["probabilities"].items():
                        if p.get("no",0)>=.85:
                            rel[cid]=min(.35,rel[cid])
                        else:
                            rel[cid]=min(1.,rel[cid]+.10*(p.get("yes",0)-p.get("no",0)))
        failed=any(not m["ok"] for m in calls)
        if failed and any(m["ok"] for m in calls if m["kind"]=="intent") and not prior_calls:
            retry_trace=Trace(self.timer)
            retry_trace.start=t.start
            return self._search(req,profile,retry_trace,rules,redirect,persist,sid,calls)
        if failed:
            notes.append("Использован локальный поиск. "+next(m["note"] for m in calls if not m["ok"]))
        t.add("rerank","Проверка категоризатором","Использованы оценки модели" if rr and not failed else "Использованы локальные оценки",
              "fallback" if failed else "ok" if rr else "skip",raised=sum(1 for c,v in pre_rerank.items() if rel[c]>v),lowered=sum(1 for c,v in pre_rerank.items() if rel[c]<v),calls=[m for m in calls if m["kind"]=="rerank"])
        weights={**WEIGHTS,**(self.controls.weights() or {}),**(req.weights or {})}
        if profile.client_id=="guest":
            weights["pers"]=0.
        cards=[ranked(self.catalog.cards[c],s,preference(self.catalog.cards[c],corrected,f,float(rel[c])),bool(sku or ("family" in f and "edition" in active)),profile,weights,self.kb) for c,s in selected.items()]
        for item in cards:
            cid=item["card_id"]
            card=self.catalog.cards[cid]
            if missing:
                item["score"]["why"].append(notes[-1])
                item["score"]["tier"]=3
            if cid in outside:
                o=item["offer"]
                n=qty["value"]
                desc=f"от {o['qty_min']} мест" if (o["qty_min"] or 1)>n else f"до {o['qty_max']} мест"
                item["qty_out_of_range"]=True
                item["score"]["why"].append("Ближайшая ступень "+desc)
                item["score"]["tier"]=3
            elif not item["offer"]["available"]:
                item["score"]["tier"]=max(2,item["score"]["tier"])
                item["score"]["why"].append("Сейчас недоступно к заказу")
            if f.get("version") and item["offer"]["version"]==f["version"] and f["version"] not in item["title"]:
                name=self.names["family"].get(card.family,card.title)
                item["title"]=item["title"].replace(name,name+" "+f["version"],1)
            item["score"]["tier_label"]=TIERS[item["score"]["tier"]]
        if intent=="task":
            task=scenarios.reference(self,"use_case",corrected,entities)
            for card in cards:
                if task.get("phrases") and (self.catalog.cards[card["card_id"]].family in task.get("families",[]) or card["category"]["id"] in task.get("categories",[])):
                    card["score"]["why"].append("Решает задачу «"+task["phrases"][0]+"»")
        if plan=="category" and profile.segment=="individual":
            domestic=[c for c in cards if c["offer"]["audience"]=="home"]
            if domestic:
                cards=domestic
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
        merch=self.controls.merch(ctx,cards)
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
        if clarify_class:
            blocks.append(dict(type="clarify",title="Уточните назначение",question="Какой класс программ вы ищете?",
                               options=[dict(label=self.names["category"][cid],apply=dict(q=self.names["category"][cid])) for cid in clarify_class]))
        if plan in ("product","vendor","category") and profile.owned:
            owned_rows=list(upgrade_rows)
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
            blocks.append(dict(type="not_in_catalog",title=title,reason={"left":"vendor_left","restricted":"restricted"}.get(status,"gap"),text=f"{title} не поставляется в Россию. Ближайшие замены:" if status=="left" else f"{title} сейчас нет в продаже."))
        if plan=="sku" and not sku:
            blocks.append(dict(type="not_in_catalog",title=raw,reason="gap",text="Такой артикул в каталоге не найден."))
        page=cards[(req.page-1)*req.page_size:req.page*req.page_size]
        if cards:
            if plan=="out_of_catalog":
                blocks.append(dict(type="analogs",title="Возможные замены",source=dict(title=title,status="unavailable",note=""),items=[dict(card=c,note="Близкий продукт по базе знаний") for c in page]))
            else:
                blocks.append(dict(type="products",title="Подходящие лицензии",total=len(cards),items=page))
        elif plan in {"account","spec_list"} or reference_only:
            pass
        elif plan=="off_topic":
            msg={"hardware":"В каталоге представлены программы и лицензии. Для какого ПО вы подбираете устройство?",
                 "piracy":"Здесь можно подобрать лицензионное ПО."}.get(reason,"Укажите название программы или задачу, например «защита рабочих мест».")
            blocks.append(dict(type="clarify",title="Поиск программного обеспечения",question=msg,options=[]))
        else:
            reason=reason or ("sku_not_found" if plan=="sku" and not sku else "filters_too_strict")
            notes.append("Артикул отсутствует в каталоге." if reason=="sku_not_found" else "Подходящих предложений по заданным условиям нет.")
        if not cards and not reference_only and plan not in ("off_topic","sku","account","question","spec_list","out_of_catalog") and not blocks:
            blocks.append(dict(type="clarify",title="Условия подбора",question="Какие условия закупки можно изменить?",
                               options=[dict(label=h["label"],apply=h["apply"]) for h in relax_hints]))
        if not cards and plan=="sku" and not sku:
            near=process.extract(sku_key(norm),self.catalog.skus.keys(),limit=3,score_cutoff=65)
            if near:
                options=[dict(label=self.catalog.skus[k].sku,apply=dict(q=self.catalog.skus[k].sku)) for k,_,_ in near]
                blocks.append(dict(type="clarify",title="Похожие артикулы",question="Проверьте обозначение в вашем заказе.",options=options))
        if plan=="out_of_catalog" or (not cards and not reference_only and plan not in {"account","spec_list","off_topic"}):
            blocks.append(dict(type="lead",title="Запрос поставки",text="Можно уточнить условия у менеджера.",action="request_quote"))
        def run_line(line):
            child=req.model_copy(update=dict(q=line.replace(","," "),mode="fast",page=1,page_size=3,session_id=""))
            return self._search(child,profile,Trace(self.timer),rules,persist=False)
        blocks=scenarios.compose(self,intent,req,f,entities,qty,cards,profile,blocks,run_line,reason)
        zero=None
        if plan=="off_topic":
            zero="off_topic" if reason in ("hardware","piracy") or len(words)>2 or reason=="gibberish" and (not re.search("[aeiouy]",norm) or norm in "qwertyuiop asdfghjkl zxcvbnm") else "unknown_term"
            if zero=="unknown_term":
                blocks.append(dict(type="lead",title="Уточнить название",text="Подскажите, для какой задачи нужна программа.",action="request_quote"))
        elif plan=="out_of_catalog":
            zero="vendor_left" if reason=="vendor_left" else "not_in_catalog"
        elif not cards and not any(b["type"] in ("answer","spec","my_licenses","kit") for b in blocks):
            zero="filters_too_strict" if relax_hints else "not_in_catalog" if entities or plan=="sku" else "unknown_term"
        elif missing:
            zero="filters_too_strict"
        elif cards and all(c.get("qty_out_of_range") for c in cards):
            zero="qty_out_of_range"
        elif cards and all(not c["offer"]["available"] or c["offer"]["price_on_request"] for c in cards):
            zero="no_available_offer"
        if zero in ("no_available_offer","qty_out_of_range") and not any(b["type"]=="lead" for b in blocks):
            blocks.append(dict(type="lead",title="Уточнить условия поставки",text="Менеджер проверит цену и доступность нужного количества.",action="request_quote"))
        if persist and plan=="product" and cards:
            alt=restricted(self,cards,profile,f,exc,weights)
            if alt:
                notes.append(alt["source"]["note"])
                if merch_secondary(self,ctx,alt,merch,t):
                    blocks.append(alt)
            else:
                vendor=self.kb.rows["vendors"].get(cards[0]["vendor"]["id"],{})
                if vendor.get("market_status") in ("restricted","left"):
                    notes.append(f"Для продукции {vendor['name']} действуют ограничения поставки. Доступность следует подтвердить.")
        if persist:
            extra=companions(self,intent,cards,profile,weights,f,exc)
            if extra:
                shown={i["card"]["card_id"] for b in blocks if b["type"]=="analogs" for i in b["items"]}
                extra["items"]=[i for i in extra["items"] if i["card"]["card_id"] not in shown]
                if extra["items"] and merch_secondary(self,ctx,extra,merch,t):
                    blocks.append(extra)
        t.add("compose","Сборка ответа",f"Карточек в выдаче · {len(cards)}")
        facets=[]
        for key,label in [("vendor","Вендор"),("category","Категория")]:
            counts=Counter(c[key]["id"] for c in cards)
            facets.append(dict(key=key,title=label,values=[dict(id=k,label=self.names[key].get(k,k),count=n) for k,n in counts.most_common() if k]))
        result=dict(search_id=sid,mode="fast" if failed else req.mode,engine="kuznitsa",relax_hints=relax_hints,banners=merch["banners"],engine_version="0.1.0",query=dict(raw=req.q,normalized=original_norm,corrected=corrected,
                    corrections=changes,did_you_mean=None),understood=dict(intent=intent,intent_title=TITLES[intent],intent_conf=intent_conf,
                    zero_reason=zero,intent_source=intent_source,inherited=inherited,entities=entities,filters=f,exclude=exc,qty=requested_qty,chips=chips,subtype=reason if intent=="off_topic" else None,reason=(next((b["reason"] for b in blocks if b["type"]=="not_in_catalog"),reason) if intent=="out_of_catalog" else reason),
                    agent_note=TITLES[intent]+(" · "+", ".join(x["label"] for x in chips) if chips else "")),blocks=blocks,facets=facets,
                    related_queries=next_queries(self,cards,norm,blocks),notes=notes,trace=t.steps,
                    cost=cost_summary(calls,self.usd_rub),timing_ms=dict(total=round((self.timer()-t.start)*1000,2)),
                    profile=profile_info(profile))
        t.add("log","Журнал и стоимость","Запись поиска в журнал. Расходы на внешние модели · 0 ₽")
        started=self.timer()
        if persist:
            if self.sessions:
                self.sessions.save(req,result,cards)
            self.journal.search(self.clock(),req,result,len(cards),zero,relaxed_qty or bool(notes and selected and plan!="sku"))
        t.steps[-1]["ms"]=round((self.timer()-started)*1000,2)
        result["timing_ms"]["total"]=round((self.timer()-t.start)*1000,2)
        if not req.explain:
            result["trace"]=[]
        return result
