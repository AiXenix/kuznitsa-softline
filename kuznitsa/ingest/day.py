"""Rehearse the entire data handover against a new, isolated snapshot."""
from collections import Counter
from dataclasses import replace
from functools import lru_cache
from itertools import islice
import json
import os
import yaml
from pathlib import Path
from tempfile import mkdtemp
from time import monotonic
from zipfile import BadZipFile

from lxml.etree import XMLSyntaxError
from kuznitsa.analytics import insights, replay
from kuznitsa.engine import Engine
from kuznitsa.kb.loader import load
from kuznitsa.text import tokens, lemma
from . import history
from .adapters import tables
from .ai_backend import search_client
from .catalog import import_catalog
from .mapping import field_for, infer
from .nameparse import Parser
from .selfcheck import selfcheck

FORMATS={".tsv",".csv",".txt",".xlsx",".json",".jsonl",".ndjson",".xml",".yml"}


class DayError(ValueError):
    """The failed rehearsal still has a report on disk."""


def identify(path,explicit=None,parser=None):
    explicit=explicit or {}
    aliases={str(a).lower():k for k,opts in history.ALIASES.items() for a in [k,*opts]}
    def history_role(sample):
        headers={str(h).strip().lower() for h in sample}
        keys={aliases.get(h) for h in headers}
        if "ym:s:visitid" in headers:
            return "metrika_visits"
        if "ym:pv:visitid" in headers:
            return "metrika_hits"
        if "q" in keys:
            role="metrika" if any(h.startswith("ym:") for h in headers) or keys & {"visits","bounce"} else "history"
            return role
    if path.suffix.lower() not in FORMATS:
        return "unknown",[]
    if path.suffix.lower() in {".tsv",".csv",".txt",".xlsx",".jsonl"}:
        rows=history.records(path,aliases)
        try:
            sample=next((r for r in islice(rows,20) if isinstance(r,dict) and r),{})
        finally:
            rows.close()
        role=history_role(sample)
        if role:
            return role,list(sample)
    for _, rows in tables(path,explicit):
        values=[r for _,r in islice(rows,25) if r]
        sample=dict.fromkeys(h for r in values for h in r)
        keys={field_for(h) for h in sample} | {k for k,h in explicit.items() if h in sample}
        role=history_role(sample)
        if role:
            return role,list(sample)
        if parser and "parent" not in keys and ("name" not in keys or not keys.intersection({"sku","price","vendor"})):
            keys=set(infer(sample,values,explicit,parser()).values())
        if keys & {"name","family_name"} and keys & {"price","vendor","sku","lic","family_id","category_path"}:
            return "catalog",list(sample)
        if keys & {"id","category_id"} and "parent" in keys:
            return "categories",list(sample)
    return "unknown",[]


def coverage(engine,cfg):
    kb=load(cfg.kb).rows
    counts=Counter()
    vendors,classes,missing=Counter(),Counter(),Counter()
    vocab={lemma(w) for w in engine.lex.words}
    total=0
    with (cfg.data/"catalog.jsonl").open() as stream:
        for line in stream:
            o=json.loads(line)
            total+=1
            recognized=[]
            for field,group in [("vendor","vendors"),("family","families"),("category","categories")]:
                ok=o.get(field+"_id") in kb[group]
                counts[field]+=ok
                recognized.append(ok)
            counts["all"]+=all(recognized)
            if not recognized[0]:
                vendors[o.get("vendor") or "Без производителя"]+=1
            if not recognized[2]:
                classes[" / ".join(o.get("category_path",[])) or "Без класса"]+=1
            for value in [o["name"],o.get("sku"),o.get("vendor"),o.get("family_name"),o.get("description"),
                          *o.get("category_path",[]),*o.get("attrs",{}).values()]:
                vocab.update(lemma(w) for w in tokens(str(value or "")))
    for row in engine.journal.rows("SELECT q_raw,count(*) n FROM active_history GROUP BY q_raw"):
        for w in set(tokens(row["q_raw"])):
            if lemma(w) not in vocab:
                missing[w]+=row["n"]
    def top(c,n=None):
        return [{"name":k,"count":v} for k,v in c.most_common(n)]
    return dict(offers=total,recognized={k:counts[k]/total for k in ("vendor","family","category","all")},
                unknown_vendors=top(vendors,50),unknown_classes=top(classes,50),unknown_query_words=top(missing))


def markdown(r):
    lines=["# День данных","",f"Каталог данных — `{r['out']}`. Время — {r['seconds']:.2f} с.","",
           "| Файл | Назначение | Принято строк | Пропущено |","|---|---|---:|---:|"]
    roles=dict(catalog="Каталог",categories="Справочник категорий",history="История запросов",
               metrika="Отчёт Метрики",metrika_hits="Хиты Метрики",metrika_visits="Визиты Метрики",
               unknown="Не распознан")
    for f in r["files"]:
        lines.append(f"| {f['file']} | {roles[f['role']]} | {f.get('accepted','—')} | {f.get('skipped','—')} |")
    for f in r["files"]:
        if f.get("error"):
            lines+=["",f"{f['file']} — {f['error']}"]
    if all(k in r for k in ("coverage","agent","selfcheck","replay")):
        c=r["coverage"]
        lines+=["","## Покрытие базы знаний","",f"Предложений — {c['offers']}. "+
                ", ".join(f"{label} — {c['recognized'][key]:.1%}" for key,label in
                          [("vendor","вендор"),("family","семейство"),("category","класс"),("all","все три признака")])]
        for key,title in [("unknown_vendors","Неизвестные вендоры"),("unknown_classes","Неизвестные классы"),
                          ("unknown_query_words","Слова запросов без совпадений")]:
            lines+=["",title+" — "+(", ".join(f"{v['name']} ({v['count']})" for v in c[key][:50]) or "нет")]
        lines+=["",f"Повторный прогон — {r['replay']['processed']} фраз. Предложений агента — {r['agent']['count']}.",
                "","| Самопроверка | Проб | Топ-3 | Топ-5 |","|---|---:|---:|---:|"]
        for k,v in r["selfcheck"]["groups"]["all"].items():
            lines.append(f"| {k} | {v['n']} | {v['top3']:.1%} | {v['top5']:.1%} |")
    if r.get("agent",{}).get("items"):
        lines+=["","## Предложения агента",""]
        lines.extend("- "+item["title"] for item in r["agent"]["items"])
    if r.get("catalog"):
        lines+=["","[Качество каталога и соответствие столбцов](import_report.json) · [Решения раскладки](import_ai.jsonl)"]
    if r.get("error"):
        lines+=["","Остановка — "+r["error"]]
    return "\n".join(lines)+"\n"


def day(folder,cfg,out=None,ai="embed",budget=.5,n=300,mapping=None):
    started=monotonic()
    folder=Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError("Укажите входную папку с файлами организаторов")
    if n<=0:
        raise ValueError("Размер выборки должен быть положительным")
    inputs=[]
    for root,dirs,names in os.walk(folder):
        base=Path(root)
        dirs[:]=sorted(d for d in dirs if not d.startswith(".") and
                       (base/d).resolve()!=cfg.data.resolve() and not (base/d/"day_report.json").is_file())
        inputs.extend(base/name for name in sorted(names) if not name.startswith(".") and (base/name).is_file())
    if mapping:
        inputs=[p for p in inputs if p.resolve()!=Path(mapping).resolve()]
    if out is None:
        cfg.data.parent.mkdir(parents=True,exist_ok=True)
        out=Path(mkdtemp(prefix="day-",dir=cfg.data.parent))
    else:
        out=Path(out).resolve()
        if out==cfg.data.resolve() or out.is_relative_to(cfg.data.resolve()):
            raise ValueError("Укажите новый каталог вне действующего каталога данных")
        out.mkdir(parents=True,exist_ok=False)
    cfg=replace(cfg,data=out,cache=out/"cache")
    report=dict(input=str(folder),out=str(out),files=[])
    engine=None
    try:
        @lru_cache(1)
        def parser():
            return Parser(load(cfg.kb))
        explicit=yaml.safe_load(Path(mapping).read_text()) if mapping else {}
        files=[]
        for path in inputs:
            f=dict(file=str(path.relative_to(folder)))
            try:
                f["role"],f["columns"]=identify(path,explicit,parser)
                if f["role"]=="unknown":
                    f["error"]="Назначение файла не распознано. Проверьте формат и заголовки."
            except (OSError,ValueError,BadZipFile,XMLSyntaxError,KeyError) as exc:
                f.update(role="unknown",error=str(exc))
            files.append((path,f))
            report["files"].append(f)
        cats=[p for p,f in files if f["role"] in {"catalog","categories"}]
        if not cats:
            raise ValueError("Не удалось распознать каталог по столбцам товаров")
        catalog=import_catalog(cats,out,cfg.kb,mapping=mapping,ai=ai,ai_budget_usd=budget,config=cfg)
        if not catalog["offers"]:
            raise ValueError("Нет пригодных предложений. Проверьте заголовки и цены.")
        report["catalog"]={k:catalog[k] for k in ("rows","offers","rejected","duplicates","ai","currency")}
        engine=Engine.open(cfg,llm=search_client("fast"))
        report["cards"]=len(engine.catalog.cards)
        for p,f in sorted(files,key=lambda item:item[1]["role"]=="metrika_hits"):
            if f["role"] in {"catalog","categories"}:
                sources=[s for k,s in catalog["sources"].items() if k==str(p) or k.startswith(str(p)+"/")]
                f["accepted"]=sum(s.get("offers",0)+s.get("references",0) for s in sources)
                f["skipped"]=sum(s.get("rows",0)+s.get("reference_rows",0) for s in sources)-f["accepted"]
            elif f["role"]!="unknown":
                try:
                    stats=history.ingest(engine,p)
                    aliases={a:k for k,opts in history.ALIASES.items() for a in [k,*opts]}
                    count=sum(1 for _ in history.records(p,aliases))
                    f.update(history=stats,accepted=count-stats["skipped"],skipped=stats["skipped"])
                except (OSError,ValueError,KeyError) as exc:
                    f["error"]=str(exc)
        report["replay"]=replay.run(engine)
        report["agent"]=insights.discover(engine)
        report["agent"]["items"]=[{k:item[k] for k in ("id","type","title","status")} for item in insights.listing(engine.journal)]
        report["coverage"]=coverage(engine,cfg)
        report["selfcheck"]=selfcheck(cfg,n,"fast",7,engine=engine)
    except Exception as exc:
        report["error"]=str(exc)
        raise DayError(f"{exc}. Отчёт — {out / 'day_report.md'}") from exc
    finally:
        if engine:
            engine.close()
        report["seconds"]=round(monotonic()-started,3)
        (out/"day_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
        (out/"day_report.md").write_text(markdown(report))
    return report
