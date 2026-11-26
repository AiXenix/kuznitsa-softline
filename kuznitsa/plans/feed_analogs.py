"""Подбор замен по назначению в пределах классов загруженного фида."""
from collections import Counter
import re
from time import perf_counter
from uuid import uuid4

from kuznitsa.index.feed import words
from kuznitsa.index.feed_language import sold_as
from kuznitsa.llm.decisions import choice
from kuznitsa.llm.recovery import cost_summary
from kuznitsa.text import normalize
from kuznitsa.understand.intent import TITLES
from .presentation import profile_info

REQUEST = re.compile(r"\b(?:аналог(?:и|а|ов)?|замен[ауые]|чем\s+(?:можно\s+)?заменить|заменить|альтернатив[ауые])\b")
DOMESTIC = re.compile(r"\b(?:российск\w*|отечественн\w*|в россии|из реестра)\b")
AUXILIARY = re.compile(r"\b(?:плагин\w*|plug-?in|модул\w*|надстройк\w*|дополнени\w*|поддержк\w*|обновлени\w*|расширени\w*)\b", re.I)


def requested(text):
    marker = REQUEST.search(text)
    if not marker:
        return None
    subject = DOMESTIC.sub("", text[marker.end():]).strip(" ?,:-«»")
    subject = re.sub(r"^(?:(?:для|на|программы|программе)\s+)+", "", subject)
    if not subject:
        subject = DOMESTIC.sub("", text[:marker.start()]).strip(" ?,:-«»")
    return subject or None


def model_section(engine, req, name, nearest, sid, calls, platform):
    index = engine.catalog.feed
    eligible = index.platform_sections.get(platform, index.classes)
    # Близкие листья плюс представители крупных разделов обеих ветвей дерева.
    # В маленьком снимке модели доступны все классы.
    large = sorted(eligible, key=lambda k: (-len(index.groups[k]), index.classes[k]))
    roots = {}
    for section in large:
        path = index.cat.cards[index.groups[section][0]].offers[0].category_path
        roots.setdefault(path[0] if path else section, section)
    options = list(dict.fromkeys([*nearest, *roots.values(), *large]))[:60]
    labels = {k: index.classes[k] for k in options}
    labels["none"] = "Назначение неизвестно или такого раздела нет"
    question = choice("По вашим знаниям, для чего предназначен этот продукт? Выберите раздел, "
                      "товары которого могут его заменить по назначению. При сомнении выберите none.", labels)
    answers, meta = engine.decisions.decide_before(perf_counter()+.59, sid, req.model_source, "intent",
                                {"название продукта":name}, {"section":question})
    calls.append(meta)
    answer = answers.get("section", {})
    selected = answer.get("choice")
    if selected in options and answer.get("probabilities", {}).get(selected, 0)>=.55:
        return selected


def native_members(index, section):
    label = index.class_names[section]
    # В фиде импортозамещение может иметь отдельный класс с тем же назначением.
    def meaning(text):
        return set(words(text))-{"российский","решение","импортозамещение","отечественный","программа"}
    required = meaning(label)-{"windows","linux","unix","macos"}
    return [k for k, title in index.class_names.items() if k!=section and k in index.analogs.domestic_sections
            and required and meaning(title)==required]


# В названиях международных линеек назначение часто записано по-английски.
# Например, File Commander и Work Folders работают с одним типом объектов.
PURPOSE_WORDS = (
    {"file","files","folder","folders","файл","файловый","папка","ftp"},
    {"audio","music","daw","studio","аудио","музыка","звукозапись"},
    {"photography","photo","фоторедактор","фото","фотография"},
    {"desktop","remote","удаленный","дистанционный"},
    {"cad","сапр","чертеж"},
    {"os","linux","ос","операционный"},
)


def purpose_words(text):
    terms=set(words(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text.replace("_"," "))))
    for group in PURPOSE_WORDS:
        if terms & group:
            terms.update(group)
    return terms


def choose(index, name, row, sections, seeds, source, russian, platform=None, registry=False, budget=None):
    """Сначала по одному представителю каждой рекомендации, затем её варианты и класс."""
    ranked, seen = [], set()
    blocked = set(source)
    allowed = index.platform_offers.get(platform) if platform else None
    def add(cid, marked=False, fill=False):
        if cid in seen or cid in blocked or (allowed is not None and cid not in allowed):
            return
        if registry and cid not in index.analogs.registered:
            return
        if budget is not None and not any(o.price is not None and o.price<=budget for o in index.cat.cards[cid].offers):
            return
        if russian and not (marked or cid in index.analogs.domestic):
            return
        seen.add(cid)
        ranked.append((cid, fill))

    for targets in seeds:
        for cid, marked in targets:
            before = len(ranked)
            add(cid, marked)
            if len(ranked)>before:
                break
    for targets in seeds:
        for cid, marked in targets:
            if len(ranked)>=4:
                break
            add(cid, marked, fill=True)

    if row and len(ranked)>=4:
        return ranked
    members = [cid for k in sections for cid in index.groups[k] if cid not in seen and cid not in blocked]
    anchor = source[0] if source else ranked[0][0] if ranked else None
    similarity = index.tree.neighbors(anchor, members) if anchor else {}
    purpose = purpose_words(" ".join(index.classes[k] for k in sections)+" "+(row["kind"] if row else ""))
    anchor_text = set()
    if anchor:
        card = index.cat.cards[anchor]
        purpose.update(purpose_words(card.title))
        if not similarity:
            anchor_text = set(words(card.title+" "+card.offers[0].description[:400]))
    purpose -= {"для","система","программа","решение","импортозамещение","российский"}
    def score(cid):
        card = index.cat.cards[cid]
        overlap = len(anchor_text.intersection(words(card.title+" "+card.offers[0].description[:400]))) if anchor_text else 0
        title_overlap = len(purpose.intersection(words(card.title)))
        return (title_overlap>0, similarity.get(cid,0), overlap, title_overlap, index.browse_quality[cid], cid)
    for cid in sorted(members,key=score,reverse=True):
        card = index.cat.cards[cid]
        if AUXILIARY.search(card.title) or sold_as(card, name):
            continue
        # Надстройка под исходный продукт не заменяет сам продукт.
        if re.search(r"\b(?:для|for)\s+"+re.escape(name)+r"\b", normalize(card.title)):
            continue
        add(cid, fill=bool(seeds))
        if row and len(ranked)>=4:
            break
    return ranked


def row_candidates(index, row):
    sections, bindings = index.analogs.bound[row["id"]]
    seeds = []
    for target, matches in bindings:
        title = normalize(target["title"])
        ordered = sorted(matches, key=lambda cid: (normalize(index.cat.cards[cid].title)!=title,
                         bool(AUXILIARY.search(index.cat.cards[cid].title)), len(index.cat.cards[cid].title), cid))
        in_section = [cid for cid in ordered if index.card_sections[cid] in sections]
        if ordered:
            seeds.append([(cid, target.get("russian",False)) for cid in (in_section or ordered)])
    return list(sections), seeds


def family_neighbors(engine, source, section):
    """Подтверждённая связь семейств уточняет назначение внутри класса фида."""
    index=engine.catalog.feed
    families=engine.kb.rows["families"]
    same_class=set(index.groups[section])
    anchors=same_class.intersection(source)
    linked=[]
    for fid, family in families.items():
        if family.get("analogs") and anchors.intersection(index.tags["families"].get(fid,())):
            linked.append(family)
    linked.sort(key=lambda f:f.get("popularity") or 0,reverse=True)
    seeds=[]
    for fid in dict.fromkeys(fid for family in linked for fid in family["analogs"]):
        members=same_class.intersection(index.tags["families"].get(fid,()))-anchors
        if members:
            seeds.append([(cid,False) for cid in sorted(members,key=index.quality.get,reverse=True)])
    return seeds


def search(engine, req, profile, trace, priorities, record, subject, row=None, explicit=False,
           known=None, qty=None, budget=None):
    from .feed import display, finish, order
    from .feed_query import matching_variants
    index = engine.catalog.feed
    name = row["names"][0] if row else subject
    russian = bool(DOMESTIC.search(normalize(req.q)) or req.filters.get("registry"))
    calls, sections, seeds, source = [], [], [], []
    sid = "s_"+uuid4().hex
    model = None
    platform_match = re.search(r"\b(?:для|под|на|for) (mac(?:os)?|windows|linux)\b",subject)
    platform = platform_match[1] if platform_match else None
    if platform=="mac":
        platform="macos"
    if row:
        sections, seeds = row_candidates(index, row)
    if explicit and (not row or row["in_catalog"]):
        for spelling in (subject, index.correct(subject), normalize(name)):
            source = [cid for cid in index.products(spelling) if sold_as(index.cat.cards[cid], spelling)]
            if source:
                break
        if not source and (slang:=index.slang.get(subject)):
            source = list(slang[1])
        if source and not row:
            section = index.card_sections[source[0]]
            if subject in index.vendor_names:
                # Для вендора с несколькими направлениями берём основной класс его линеек.
                section = Counter(index.card_sections[cid] for cid in source).most_common(1)[0][0]
                source.sort(key=lambda cid:index.card_sections[cid]!=section)
            sections = [section]
            seeds = family_neighbors(engine,source,section)
    missing = not (explicit and (row["in_catalog"] if row else source))
    nearest = []
    if not sections and not seeds:
        legacy = index.replacements.get(subject)
        if legacy and not source:
            for target in legacy.get("russian_analogs", []):
                matches = index.tags["families"].get(target["family"], ())
                seeds.append([(cid,False) for cid in sorted(matches,key=index.quality.get,reverse=True)])
            sections = list(dict.fromkeys(index.card_sections[cid] for group in seeds for cid,_ in group))
        if not sections:
            known = known or index.unsold_sections.get(subject)
            possible = known or index.language.possible_section(subject)
            nearest = index.sections(subject,software_only=bool(platform) or not explicit,platform=platform)
            if not known and req.mode=="smart" and engine.decisions:
                model = model_section(engine,req,name,nearest,sid,calls,platform)
            selected = known or model or possible
            if selected:
                sections = [selected]
    if russian:
        sections = list(dict.fromkeys([*sections, *(k for s in sections for k in native_members(index,s))]))
    registry=bool(req.filters.get("registry"))
    choices = choose(index, normalize(name), row, sections, seeds, source, russian, platform, registry, budget)
    clarify = not sections and not choices
    options = []
    if clarify:
        # Из ближайших выбираем три раздела с доступными примерами. Если в первых
        # трёх всего три карточки, ищем ближайший раздел со вторым примером.
        groups = []
        for k in nearest:
            examples = []
            for cid in index.groups[k]:
                if registry and cid not in index.analogs.registered:
                    continue
                if russian and cid not in index.analogs.domestic:
                    continue
                if platform in index.platform_offers and cid not in index.platform_offers[platform]:
                    continue
                examples.append((cid,True))
                if len(examples)==4:
                    break
            if examples:
                if len(groups)<3:
                    options.append(k)
                    groups.append(examples)
                elif len(examples)>len(groups[-1]):
                    options[-1], groups[-1] = k, examples
            if len(groups)==3 and sum(map(len,groups))>=4:
                break
        choices = [(g[i][0],True) for i in range(4) for g in groups if len(g)>i][:4]
    selections = {}
    if qty or budget is not None:
        selections = matching_variants(index,[cid for cid,_ in choices],profile,qty,False,
                    {"price_max":budget} if budget is not None else {})
        if budget is not None:
            choices = [c for c in choices if c[0] in selections]
    section = sections[0] if sections else index.card_sections[choices[0][0]] if choices and not clarify else None
    label = index.classes.get(section,"")
    title = ("Нет в каталоге. " if missing else "")+"Похожие по назначению"+(f": {label}" if label else "")
    note = (f"В каталоге нет «{name}». " if missing else "")+(
        "Уточните назначение, чтобы подобрать замену." if clarify else
        f"Подбираем {'российские ' if russian else ''}замены для «{name}»"+(f" в разделе «{label}»." if label else "."))
    if not choices and not clarify:
        note+=" Подходящих замен в продаже не найдено."
    elif 0<len(choices)<4 and not clarify:
        note+=f" Число подходящих карточек в продаже — {len(choices)}."
    intent = "out_of_catalog" if missing and not explicit else "analog"
    start = (req.page-1)*req.page_size
    items = []
    for cid, fill in choices[start:start+req.page_size]:
        category = index.classes[index.card_sections[cid]]
        reason = f"Из раздела «{category}»" if clarify else f"Аналог {name}: {category}"
        preferred = index.platform_offers.get(platform,{}).get(cid)
        if russian and preferred is None:
            preferred=index.analogs.registered.get(cid)
        card = display(engine,cid,profile,preferred,selections.get(cid))
        if fill and not clarify:
            reason=f"Близкий товар для {name} из раздела «{category}»"
        card.update(reason=reason, fill=fill, label=reason)
        card["score"]["why"].insert(0,reason)
        items.append(card)
    trace.add("retrieve","Подбор замен",note,candidates=len(choices))
    if calls:
        trace.add("intent","Выбор класса по назначению",label or note,calls=calls)
    merch = order(engine,req,profile,trace,priorities,intent,section,items)
    if merch is None:
        return None
    items = merch["cards"]
    by_id={cid for cid,_ in choices}
    items=[c for c in items if c["card_id"] in by_id]
    for pos,card in enumerate(items,1):
        card["position"]=pos
    blocks = [dict(type="not_in_catalog",title="Нет в каталоге",reason="gap",text=note)] if missing else []
    if clarify:
        blocks.append(dict(type="clarify",title="Уточните раздел",question="Для какой задачи нужна замена?",
                 options=[dict(label=index.classes[k],apply=dict(q=index.classes[k],category=k)) for k in options]))
        if items:
            blocks.append(dict(type="products",title="Примеры из предложенных разделов",items=items,total=len(choices)))
    else:
        blocks.append(dict(type="analogs",title=title,category_id=section,items=[dict(card=c,reason=c["reason"]) for c in items]))
    filters = {"category":sections} if sections else {}
    if russian:filters["domestic"]=True
    if req.filters.get("registry"):filters["registry"]=True
    if budget is not None:filters["price_max"]=budget
    zero = "not_in_catalog" if missing else None
    result = dict(search_id=sid,engine="kuznitsa",engine_version="1.0",mode=req.mode,
        query=dict(raw=req.q,normalized=normalize(req.q),corrected=subject,corrections=[],did_you_mean=None),
        understood=dict(intent=intent,intent_title=TITLES[intent],intent_conf=.9,intent_source="jev" if model else "rules",
                        filters=filters,exclude={},qty=qty,entities=[],chips=[],zero_reason=zero,agent_note=note),
        blocks=blocks,facets=[],notes=[],banners=merch["banners"],relax_hints=[],related_queries=[],
        profile=profile_info(profile),cost=cost_summary(calls,engine.usd_rub),trace=trace.steps,timing_ms={})
    return finish(engine,req,trace,record,result,items,len(items),calls)
