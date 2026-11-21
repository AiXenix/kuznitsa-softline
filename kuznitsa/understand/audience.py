"""Назначение линейки и уточнение необъяснённой части запроса."""
import re
from collections import defaultdict

from kuznitsa.llm.decisions import choice
from kuznitsa.text import lemma,tokens

LABELS=dict(home="для дома",micro_office="для малого офиса",business="для организации",
            enterprise="для крупного предприятия",gov="для госучреждения",edu="для образования",
            server="для серверов",mobile="для мобильных устройств",industrial="для промышленности")
PATTERNS={
    "home":r"хоум|домик|домашн|для (?:дома|семьи)|маме|папе|родител|ребенк|себе|личн(?:ого|ый|ых|ое)|\bhome\b",
    "micro_office":r"маленьк\w* фирм|для ип\b|микроофис|микробизнес|мал(?:ого|ый|еньк\w*) (?:офис|бизнес)|небольш\w* офис",
    "mobile":r"мобил|телефон|смартфон|планшет|андроид|android|айфон|iphone",
    "server":r"\bсервер", "industrial":r"промышлен|асу тп|завод",
    "edu":r"для школ|для вуз|студент|учебн|образоват", "gov":r"госучрежд|госсектор",
    "enterprise":r"крупн\w* (?:предприят|компани)", "business":r"для (?:офиса|компании|бизнеса)|корпоративн"}
PLATFORMS={"android":r"андроид|android","ios":r"айфон|iphone|\bios\b","macos":r"макбук|\bмак(?:а|е|и)?\b|macos",
           "linux":r"линукс|\blinux\b","server":r"\b(?:сервер|server|сервак)","windows":r"\bноут|на компьютер\b|\bwindows\b"}
PURPOSE={"micro_office":r"мал\w+ (?:бизнес|офис)|small office","server":r"для .*сервер|file server|серверн",
         "mobile":r"мобильн|мобилити|mobile","industrial":r"промышлен|industrial|асу тп"}
def audience(text):
    return next((key for key,pat in PATTERNS.items() if re.search(pat,text)),None)


class Lines:
    def __init__(self,catalog):
        self.rows={}
        self.vendors=defaultdict(set)
        self.categories=defaultdict(set)
        for c in catalog.cards.values():
            available=[o for o in c.offers if o.available and o.kind=="license" and o.lic.action in (None,"new")]
            if not available or c.kb.get("for_sale_b2b") is False:continue
            row=self.rows.setdefault(c.family,dict(title=c.kb.get("title") or c.offers[0].family_name or c.title,
                desc=c.kb.get("for_whom") or c.kb.get("summary",""), popularity=c.kb.get("popularity") or 0,audiences=set()))
            row["audiences"].update(o.lic.audience for o in available)
            targets=c.kb.get("target_audiences") or []
            row.update(targets=set(targets),primary=next(iter(targets),None),category=c.category)
            row.setdefault("terms",set(map(lemma,tokens(row["title"]))))
            row.setdefault("details",set(map(lemma,tokens(str(row["desc"])))))
            self.vendors[c.vendor].add(c.family)
            self.categories[c.category].add(c.family)

    def options(self,engine,f,a,text):
        family_rows=engine.kb.rows["families"]
        vendors=f.get("vendor") or [family_rows.get(fid,{}).get("vendor") for fid in f.get("family",[])]
        by_vendor=set().union(*(self.vendors[v] for v in vendors))
        by_class=set().union(*(self.categories[v] for v in f.get("category",[])))
        ids=by_vendor & by_class or by_vendor or by_class
        terms=set(map(lemma,tokens(text)))-{"на","по","для","до","и","в","компания","пользователь","устройство","пк","место","лицензия"}
        def priority(fid):
            row=self.rows[fid]
            fit=a in row["audiences"] if a in ("home","gov","edu") else a in PURPOSE and re.search(PURPOSE[a],(row["title"]+" "+str(row["desc"])).lower())
            title_fit=len(terms & row["terms"])
            detail_fit=len(terms & row["details"])
            return (a not in row["targets"],-title_fit,a!=row["primary"],-detail_fit,not bool(fit),-row["popularity"],fid)
        return {fid:self.rows[fid]["title"]+" · "+str(self.rows[fid]["desc"])[:180] for fid in sorted(ids,key=priority)[:8]}


def absent_source(rows):
    return any(row.get("for_sale_b2b") is False or row.get("catalog") is False for row in rows)


def resolve(engine,req,intent,text,residual,f,smart,deadline,sid,calls,trace,entities=()):
    families=engine.kb.rows["families"]
    rows=[families.get(fid,{}) for fid in f.get("family",[])]
    a=audience(text) or f.get("audience")
    if not a and rows and all("home" in row.get("target_audiences",[]) and row.get("for_sale_b2b") is False for row in rows):a="home"
    if a!="home" and f.get("audience") in ("gov","edu","enterprise","industrial","micro_office"):a=f["audience"]
    if a in (None,"server","business") and re.search("министерств|госсектор|госучрежд",text):a="gov"
    if a in (None,"server","business") and re.search(r"\bцод\b|холдинг",text):a="enterprise"
    if not a and re.search(r"рабочи[ех] мест|сотрудник|организаци",text):a="business"
    if not a and re.search(r"\bserver\b",text):a="server"
    if not a and len(rows)==1 and rows[0].get("for_sale_b2b") is False:
        a=next(iter(rows[0].get("target_audiences") or []),None)
    if not a and re.search(r"небольш\w* ип\b",text):a="micro_office"
    if a not in LABELS:a=None
    platform=next((p for p,pat in PLATFORMS.items() if re.search(pat,text)),None)
    if platform and rows and any(platform in str(row.get("name","")).casefold() for row in rows):
        # ОС в названии — предмет покупки. Отдельная платформа вводится предлогом.
        if not re.search(r"\b(?:под|на|для) (?:ос )?"+"(?:%s)" % PLATFORMS[platform],text):
            platform=None
    if platform=="linux" and a in ("gov","server") and re.search(r"на сервер",text) and not re.search(r"(?:на|под) (?:астра |astra )?линукс",text):
        platform="server"
    if not platform and len(rows)==1 and "linux" in rows[0].get("platforms",[]) and str(rows[0].get("category","")).startswith("desktop_os_ru"):
        platform="linux"
    if platform and "platform" not in req.ignore and "platform" not in req.filters:
        existing=f.get("platform",[])
        if platform!="server" and (not existing or existing==["windows"] or existing==["server"]):
            f["platform"]=[platform]
        elif existing==["server"]:
            f.pop("platform",None)
    if "audience" in req.ignore:a=None
    result=dict(audience=a,line=None,source="dict",probability=1. if a else 0.)
    # Назначение уточняет догадку о линейке. Явно выбранное семейство остаётся опорой.
    named=any(e["type"]=="family" and e["id"] in f.get("family",[]) for e in entities)
    if req.filters.get("family") or absent_source(rows) or named and a in ("business",None):
        flexible=False
    else:
        stated=[row for row in rows if any(len(alias)>2 and alias.casefold() in text for alias in [row.get("name",""),row.get("title","")])]
        flexible=bool(a and (not stated or any(row.get("target_audiences") and a not in row["target_audiences"] for row in stated)))
    opts=engine.lines.options(engine,f,a,text)
    if flexible and a!="home" and opts and rows:
        scope=set(f.get("vendor",[])) or {r.get("vendor") for r in rows}
        if scope and any(engine.lines.rows[fid]["targets"] for fid in opts):
            pool=[fid for fid in opts if fid in set().union(*(engine.lines.vendors[v] for v in scope)) and a in engine.lines.rows[fid]["targets"]]
            current=f.get("family",[])[0]
            if pool and (a not in engine.lines.rows.get(current,{}).get("targets",[]) or current not in pool or (len(pool)>1 and engine.lines.rows[pool[0]]["primary"]==a!=engine.lines.rows[current]["primary"])):
                result["line"]=pool[0]
    noise={"для","по","лицензия","купить","на","от","до","пк","место","год","лет","пользователь",
           "за","рубль","руб","тысяча","тыс","бюджет","всего","дешевле","цена","стоимость","месяц"}
    significant={lemma(w) for w in tokens(residual) if w.isalpha()}-noise
    absent=bool(f.get("family") and not any(fid in engine.lines.rows for fid in f["family"]))
    ask=bool(significant or absent or a=="home" or len({str(engine.lines.rows[fid]["desc"] or engine.lines.rows[fid]["title"]) for fid in opts})>=3 and intent in ("broad","category","vendor"))
    meta=None
    questions={}
    if ask and smart and "audience" not in req.ignore:
        questions={"audience":choice("Для кого покупатель выбирает ПО? Цена и количество сами по себе не определяют аудиторию. Без признака назначения выбирай none.",{**LABELS,"none":"Не указано"}),
                   "line":choice("Выбери линейку, только если покупатель назвал её или описал конкретное назначение. При общем запросе или отсутствии подходящей выбери none.",{**opts,"none":"Не определена"})}
        answers,meta=engine.decisions.decide_before(deadline,sid,req.model_source,"refine",{"запрос":text},questions)
        calls.append(meta)
        meta["probabilities"]={key:ans["probabilities"] for key,ans in answers.items()}
        for key in ("audience","line"):
            if key not in answers:continue
            ans=answers[key]
            val=ans["choice"]; p=ans["probabilities"][val]
            if val=="none" or p<.55 or val not in questions[key]["criteria"]:continue
            if key=="audience" and (a and val!=a and not (a=="business" and val in ("enterprise","micro_office")) or not (a or significant)):continue
            if key=="line" and (not (significant or a) or absent or f.get("family") and not flexible or req.filters.get("family") or "family" in req.ignore):continue
            if key=="line" and result["line"] and a in engine.lines.rows[result["line"]]["targets"] and a not in engine.lines.rows[val]["targets"]:continue
            if key=="line" and (a=="home" and "home" not in engine.lines.rows[val]["audiences"] or not significant and not result["audience"]):continue
            result.update({key:val},source="jev",probability=p)
    a=result["audience"]
    if not result["line"] and a in PURPOSE and (f.get("vendor") or len(opts)==1) and not f.get("family") and "family" not in req.ignore:
        for fid,label in opts.items():
            if a in engine.lines.rows[fid]["targets"] or re.search(PURPOSE[a],label.lower()):
                result["line"]=fid
                break
    if result["line"] and "family" not in req.ignore:f["family"]=[result["line"]]
    if a and "vendor" not in req.ignore and not f.get("vendor") and len(rows)==1 and rows[0].get("vendor") and (absent or a=="home"):
        f["vendor"]=[rows[0]["vendor"]]
    if f.get("audience") in LABELS and f["audience"] not in ("home","edu","business","gov"):
        f.pop("audience")
    if result["audience"] in ("home","gov","edu","business") and "audience" not in req.filters:
        f["audience"]=result["audience"]
    trace.add("refine","Уточнение назначения",LABELS.get(result["audience"],"Назначение не уточнено"),
              "fallback" if meta and not meta["ok"] else "ok" if a or meta else "skip",questions=questions,
              choices=result.copy(),calls=[meta] if meta else [],usd=(meta or {}).get("usd",0),
              rub=(meta or {}).get("usd",0)*engine.usd_rub)
    return result
