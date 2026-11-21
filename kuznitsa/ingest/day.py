"""Rehearse the entire data handover against a new, isolated snapshot."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import lru_cache
from itertools import islice
import json
import os
import yaml
from pathlib import Path
from tempfile import mkdtemp, TemporaryDirectory
from time import monotonic
from zipfile import BadZipFile

from lxml.etree import XMLSyntaxError
from kuznitsa.analytics import insights,replay
from inspect import signature
from kuznitsa.engine import Engine
from kuznitsa.kb.loader import load
from kuznitsa.text import tokens, lemma
from . import history
from .adapters import encoding,tables
from .ai_backend import search_client,reuse_knowledge_vectors
from .catalog import import_catalog
from .mapping import field_for, infer
from .nameparse import Parser
from .selfcheck import selfcheck

FORMATS={".tsv",".csv",".txt",".xlsx",".json",".jsonl",".ndjson",".xml",".yml"}


class DayError(ValueError):
    """The failed rehearsal still has a report on disk."""


def identify(path,explicit=None,parser=None,diagnostics=None):
    explicit=explicit or {}
    def decision(role,columns,reason,confidence):
        if diagnostics is not None:
            diagnostics.update(reason=reason,confidence=confidence,best_guess=role)
        return role,list(columns)
    if path.suffix.lower() in {".md",".rst"}:
        return decision("documentation",[],"Сопроводительный текст",.95)
    sniff=getattr(history,"sniff",None)
    if sniff is not None and path.suffix.lower() in FORMATS:
        hint=sniff(path)
        roles={"search_log":"history","metrika_report":"metrika","metrika_hits":"metrika_hits","metrika_visits":"metrika_visits","orders":"orders"}
        roles.update(ga4_events="ga4_events", crm_leads="crm_leads", metrika_external_phrases="metrika_external_phrases")
        if hint["kind"] in roles:
            if diagnostics is not None:
                diagnostics.update(confidence=hint["confidence"],reason=hint["reason"])
            return roles[hint["kind"]],hint["columns"]
    aliases={str(a).lower():k for k,opts in history.ALIASES.items() for a in [k,*opts]}
    def history_role(sample):
        headers={str(h).strip().lower() for h in sample}
        keys={aliases.get(h) for h in headers}
        if "ym:s:visitid" in headers:
            return "metrika_visits"
        if headers & {"ym:pv:visitid","ym:pv:watchid"}:
            return "metrika_hits"
        if "visits" in keys and "bounce" in keys:
            return "metrika"
        if "q" in keys:
            role="metrika" if any(h.startswith("ym:") for h in headers) or keys & {"visits","bounce"} else "history"
            return role
    if path.suffix.lower() not in FORMATS:
        return "unknown",[]
    if sniff is None and path.suffix.lower() in {".tsv",".csv",".txt",".xlsx",".jsonl"}:
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
        role=history_role(sample) if sniff is None or any(str(k).lower().startswith("ym:") for k in sample) else None
        if role:
            return role,list(sample)
        if any(row.get("_parent_id") or row.get("_product") for row in values):
            return decision("catalog",sample,"Варианты CommerceML с Ид товара",1.)
        if keys & {"source_id","sku","id","guid","store_id","supplier_sku"} and "stock" in keys and not keys & {"name","family_name"}:
            return decision("stock",sample,"Код позиции и остаток без названия товара",.95)
        if parser and "parent" not in keys and ("name" not in keys or not keys.intersection({"sku","price","vendor"})):
            keys=set(infer(sample,values,explicit,parser()).values())
        identifiers={"source_id","sku","id","guid","store_id","supplier_sku"}
        if not keys & {"name","family_name"} and keys & identifiers and keys & {"price","stock"}:
            return decision("stock" if "stock" in keys else "prices",sample,"Идентификаторы и коммерческие условия",.90)
        if keys & {"name","family_name"} and keys & {"price","vendor","lic","family_id","category_path",*identifiers}:
            populated=sum(any(str(v or "").strip() for v in row.values()) for row in values)
            confidence=min(.99,.64+.075*len(keys-{None})+.05*populated/max(1,len(values)))
            return decision("catalog",sample,"Названия товаров и коммерческие поля в строках",round(confidence,2))
        if keys & {"id","category_id"} and "parent" in keys:
            return decision("categories",sample,"Идентификаторы категорий и родителей",.98)
        if diagnostics is not None and sample:
            diagnostics.update(columns=list(sample),best_guess="catalog" if keys & {"name","price","vendor","sku"} else "table",
                               confidence=.25 if keys-{None} else .05,reason="Недостаточно опорных полей в заголовке и значениях")
    if path.suffix.lower()==".txt":
        with path.open(encoding=encoding(path),errors="replace") as stream:
            lines=[line.strip() for line in islice(stream,12) if line.strip()]
        if lines and sum(len(s.split())>=7 and not any(c in s for c in ("\t",";","|")) for s in lines)>=len(lines)/2:
            return decision("documentation",[],"Связный текст без табличных полей",.80)
    return "unknown",(diagnostics or {}).get("columns",[])


def coverage(engine,cfg):
    # Auto identifiers use a reserved prefix. The snapshot already loaded the base KB.
    kb=engine.kb.rows
    counts=Counter()
    vendors,classes,missing=Counter(),Counter(),Counter()
    vocab={lemma(w) for w in engine.lex.words}
    @lru_cache(32000)
    def vocabulary(value):
        return tuple(lemma(w) for w in tokens(value))
    total=0
    with (cfg.data/"catalog.jsonl").open() as stream:
        for line in stream:
            o=json.loads(line)
            total+=1
            recognized=[]
            for field,group in [("vendor","vendors"),("family","families"),("category","categories")]:
                ident=o.get(field+"_id") or ""
                ok=not ident.startswith("auto_") and ident in kb[group]
                counts[field]+=ok
                recognized.append(ok)
            counts["all"]+=all(recognized)
            if not recognized[0]:
                vendors[o.get("vendor") or "Без производителя"]+=1
            if not recognized[2]:
                classes[" / ".join(o.get("category_path",[])) or "Без класса"]+=1
            for value in [o["name"],o.get("sku"),o.get("vendor"),o.get("family_name"),o.get("description"),
                          *o.get("category_path",[]),*o.get("attrs",{}).values()]:
                vocab.update(vocabulary(str(value or "")))
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
    roles=dict(ga4_events="События GA4",crm_leads="Заявки CRM",metrika_external_phrases="Метрика · фразы из поисковиков",orders="Заказы",prices="Таблица цен",stock="Остатки",documentation="Сопроводительный текст",catalog="Каталог",categories="Справочник категорий",history="История запросов",
               metrika="Метрика · поиск по сайту",metrika_hits="Хиты Метрики",metrika_visits="Визиты Метрики",
               unknown="Не распознан")
    for f in r["files"]:
        lines.append(f"| {f['file']} | {roles[f['role']]} | {f.get('accepted','—')} | {f.get('skipped','—')} |")
    for f in r["files"]:
        if f["role"]=="unknown":
            lines+=["",f"{f['file']} — {f.get('reason','')}. Ближайшее назначение — {f.get('best_guess','?')} ({f.get('confidence',0):.0%})."]
        elif f.get("error"):
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
    if r.get("timings"):
        lines+=["","Время этапов, с — "+", ".join(f"{k} {v:.2f}" for k,v in r["timings"].items())+"."]
    if r.get("catalog"):
        merge=r["catalog"]["merge"]
        ai=r["catalog"]["ai"]
        lines+=["",f"Совмещено строк — {sum(merge['matched'].values())}. Расхождений значений — {sum(merge['conflicts'].values())}.",
                f"Раскладка добавила класс основной БЗ для {ai.get('coverage_gain_offers',0)} предложений. Расход — ${ai['usd']:.5f}."]
        lines+=["","[Качество каталога и соответствие столбцов](import_report.json) · [Решения раскладки](import_ai.jsonl)"]
    if r.get("error"):
        lines+=["","Остановка — "+r["error"]]
    return "\n".join(lines)+"\n"


def day(folder,cfg,out=None,ai="embed",budget=.5,n=300,mapping=None,replay_limit=None):
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
    # Content-addressed vectors are immutable and independent of the active journal.
    cache=out/"cache"
    cache.mkdir()
    for cached in cfg.cache.glob("dense-*.npy"):
        try:
            os.link(cached,cache/cached.name)
        except OSError:
            pass
    cfg=replace(cfg,data=out,cache=cache)
    report=dict(input=str(folder),out=str(out),files=[],timings={})
    last=started
    def stage(key):
        nonlocal last
        now=monotonic()
        report["timings"][key]=round(now-last,3)
        last=now
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
                f["role"],f["columns"]=identify(path,explicit,parser,f)
                if f["role"]=="unknown":
                    f["error"]="Назначение файла не распознано. Проверьте формат и заголовки."
            except (OSError,ValueError,BadZipFile,XMLSyntaxError,KeyError) as exc:
                f.update(role="unknown",error=str(exc))
            f.setdefault("confidence",0.95 if f["role"]!="unknown" else 0.0)
            f.setdefault("best_guess",f["role"] if f["role"]!="unknown" else "document")
            if f["role"]=="unknown":
                f.setdefault("reason",f.get("error","Недостаточно данных"))
            files.append((path,f))
            report["files"].append(f)
        cats=[p for p,f in files if f["role"] in {"catalog","categories","stock","prices"}]
        if not cats:
            raise ValueError("Не удалось распознать каталог по столбцам товаров")
        stage("detect")
        catalog=import_catalog(cats,out,cfg.kb,mapping=mapping,ai=ai,ai_budget_usd=budget,config=cfg)
        if not catalog["offers"]:
            raise ValueError("Нет пригодных предложений. Проверьте заголовки и цены.")
        report["catalog"]={k:catalog[k] for k in ("rows","offers","rejected","duplicates","ai","currency","merge")}
        stage("catalog")
        history_inputs=[]
        for p,f in sorted(files,key=lambda item:item[1]["role"]=="metrika_hits"):
            if f["role"] in {"catalog","categories","stock","prices"}:
                sources=[s for k,s in catalog["sources"].items() if k==str(p) or k.startswith(str(p)+"/")]
                matched=sum(catalog["merge"]["matched"].get(k,0) for k in catalog["sources"] if k==str(p) or k.startswith(str(p)+"/"))
                f["accepted"]=matched+sum(s.get("offers",0)+s.get("references",0) for s in sources)
                f["skipped"]=matched+sum(s.get("rows",0)+s.get("reference_rows",0) for s in sources)-f["accepted"]
            elif f["role"] not in {"unknown","documentation"}:
                history_inputs.append((p,f))
        # B owns ordering and deduplication across visits, hits, the store log and aggregates.
        history_files=dict(history_inputs)
        ordered=history.ordered_files(history_files)
        # Logs API uses camelCase. Older history readers split these names into words.
        aliases={"ym:s:searchPhrase":"q","ym:s:bounceRate":"bounce"}
        from .source_index import install
        def open_search(config,journal=None):
            reuse_knowledge_vectors(config)
            result=Engine.open(config,llm=search_client("fast"),journal=journal)
            install(result.catalog)
            return result

        large_logs=[p for p,f in history_inputs if f["role"]=="history" and p.stat().st_size>=2_000_000]
        overlap=bool(large_logs and cfg.embed!="off")
        engine=open_search(replace(cfg,embed="off") if overlap else cfg)
        report["cards"]=len(engine.catalog.cards)
        stage("legacy_index" if overlap else "index")
        # B's legacy import consumes names, lexical matches and observed events.
        # Build the public dense search engine while the legacy journal is ingested.
        with TemporaryDirectory(dir=out) as tmp, ThreadPoolExecutor(max_workers=1) as executor:
            index_start=monotonic()
            def open_index():
                result=open_search(cfg,engine.journal)
                return result,round(monotonic()-index_start,3)
            index=executor.submit(open_index) if overlap else None
            hist_map=Path(tmp)/"history.yaml"
            hist_map.write_text(yaml.safe_dump(aliases))
            try:
                stats_list=history.ingest_files(engine,ordered,mapping=hist_map)
                for path,stats in zip(ordered,stats_list,strict=True):
                    history_files[path].update(history=stats,accepted=stats["rows_accepted"],skipped=stats["skipped"])
                if large_logs:
                    with engine.journal.transaction() as db:
                        db.execute("CREATE INDEX IF NOT EXISTS day_events_type ON events(type,search_id,card_id,position)")
                        db.execute("CREATE INDEX IF NOT EXISTS day_history_visit ON searches(session_id,q_raw,ts) WHERE source='history'")
                        db.execute("ANALYZE")
                stage("history")
            finally:
                if index:
                    full,report["index_seconds"]=index.result()
                    engine.close()
                    engine=full
                    stage("index_wait")
        if "cfg" in signature(replay.run).parameters:
            report["replay"] = replay.run(engine, mode="fast", limit=replay_limit, cfg=cfg)
        else:
            # Compatibility with the B3 module present before the joint merge.
            report["replay"]=replay.run(engine,mode="fast",limit=replay_limit)
        stage("replay")
        with ThreadPoolExecutor(max_workers=1) as executor:
            def checks():
                start=monotonic()
                result=selfcheck(cfg,n,"fast",7,engine=engine)
                return result,round(monotonic()-start,3)
            check=executor.submit(checks)
            report["agent"]=insights.discover(engine)
            report["agent"]["items"]=[{k:item[k] for k in ("id","type","title","status")} for item in insights.listing(engine.journal)]
            stage("agent")
            report["coverage"]=coverage(engine,cfg)
            stage("coverage")
            report["selfcheck"],report["selfcheck_seconds"]=check.result()
            stage("selfcheck_wait")
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
