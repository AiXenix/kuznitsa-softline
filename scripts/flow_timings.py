#!/usr/bin/env python3
"""Measure the open dev set, seen kit probes and verified examples on a local demo snapshot."""
import argparse
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.message import Message
from functools import lru_cache
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from time import perf_counter
from uuid import uuid4

import numpy as np
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_scenarios import EXPECTED
from kuznitsa.config import Config
from kuznitsa.engine import Engine
from kuznitsa.evaluation import cards_from, inspect
from kuznitsa.schema import Request

OUT = ROOT / "docs/flows"
GATEWAY = "http://127.0.0.1:8098/decisions"
# Leave headroom for two already submitted rerank batches.
BUDGET = 0.14
EXTRA = {
    "account": ["мои лицензии организации", "что у нас скоро истекает", "покажи мои покупки",
                "история заказов организации", "что куплено для нашей компании", "открыть личный кабинет"],
    "promo": ["скидка на криптопро", "пилот астра линукс", "пробная версия р7 офис",
              "акция на антивирус", "скидки на мойофис", "пилот для компании", "промокод на касперский"],
    "service": ["курсы администрирования astra linux", "обучение работе с ред ос", "курсы по криптопро",
                "техподдержка для сервера", "внедрение мойофис", "курсы по nanocad"],
}


def read_jsonl(path):
    with path.open() as src:
        return [json.loads(line) for line in src if line.strip()]


def write(name, data):
    path = OUT / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def request(engine, row, mode):
    return engine.search(Request(q=row["q"], profile_id=row.get("profile") or "guest",
                                 category=row.get("category_ctx"), source="eval", mode=mode))


def example(row, result, allowed, source):
    intent = result["understood"]["intent"]
    blocks = result["blocks"]
    filled = {b["type"] for b in blocks if
              (len(b["columns"]) >= 2 if b["type"] == "compare" else
               any(s.get("card") for s in b["slots"]) if b["type"] == "kit" else
               any(s.get("card") for s in b["lines"]) if b["type"] == "spec" else
               any(b.get(k) for k in ("items", "text", "options")))}
    if intent not in allowed or not filled.intersection(EXPECTED[intent].split()):
        return None
    cards = cards_from(blocks)
    return dict(q=row["q"], profile=row.get("profile") or "guest", mode="fast",
                intent=intent, first_card=cards[0]["title"] if cards else None,
                blocks=[b["type"] for b in blocks], ms=result["timing_ms"]["total"],
                source=source, category_ctx=row.get("category_ctx"))


def percentiles(values):
    return dict(zip(("p50", "p95"), np.percentile(values, [50, 95]).round(2).tolist()))


def summarize(records):
    steps = defaultdict(list)
    for _, _, _, trace in records:
        for name, ms in trace.items():
            steps[name].append(ms)
    return dict(n=len(records), total=percentiles([r[2] for r in records]),
                steps={s: percentiles(values) for s, values in steps.items()},
                datasets=Counter(r[0] for r in records),
                returned_mode=Counter(r[1] for r in records))


def gateway_config():
    cfg = Config()
    if cfg.jev_url != GATEWAY or os.getenv("OPENROUTER_API_KEY") != "gateway" or os.getenv("KZ_LLM") == "off":
        raise SystemExit("Set KZ_JEV_URL to the local gateway and OPENROUTER_API_KEY=gateway.")
    return cfg


def measure():
    cfg = gateway_config()
    sources = {"dev": read_jsonl(ROOT / "eval/queries.dev.jsonl"),
               "seen": [r for r in read_jsonl(ROOT / "design/proposals/neon4/probes-kits-r3.jsonl") if r["seen"] is True]}
    engine = Engine.open(cfg)
    engine.decisions.run_budget = BUDGET
    buckets = defaultdict(list)
    smart_ids = []
    examples = {i: [] for i in EXPECTED}

    def offer(row, result, allowed, source):
        intent = result["understood"]["intent"]
        rows = examples[intent]
        if len(rows) < 5 and row["q"] not in {x["q"] for x in rows}:
            item = example(row, result, allowed, source)
            if item:
                rows.append(item)

    def sample(row, mode, source):
        result = request(engine, row, mode)
        if mode == "smart":
            smart_ids.append((result["search_id"],))
        steps = {s["step"]: s["ms"] for s in result["trace"]}
        buckets[result["understood"]["intent"], mode].append(
            (source, result["mode"], result["timing_ms"]["total"], steps))
        return result

    try:
        for source, rows in sources.items():
            for row in rows:
                result = sample(row, "fast", source)
                if source == "dev":
                    checks, _, _ = inspect(engine, row, result)
                    if checks and all(checks.values()):
                        allowed = row["assert"].get("intent", [])
                        offer(row, result, [allowed] if isinstance(allowed, str) else allowed, row["id"])
                elif any(e["id"] == row["expect"] and e["type"] == row["kind"] for e in result["understood"]["entities"]):
                    offer(row, result, ["role_kit" if row["kind"] == "role" else "industry"], "seen")
        for intent, phrases in EXTRA.items():
            for q in phrases:
                if len(examples[intent]) >= 5:
                    break
                row = dict(q=q, profile="smb_trade" if intent == "account" else "guest")
                offer(row, request(engine, row, "fast"), [intent], "author")
        missing = {i:len(rows) for i, rows in examples.items() if len(rows) < 5}
        if missing:
            raise ValueError(f"Missing examples: {missing}")
        sources["examples"] = [r for rows in examples.values() for r in rows]
        for row in sources["examples"]:
            result = sample(row, "fast", "examples")
            checked = example(row, result, [row["intent"]], row["source"])
            if checked is None:
                raise RuntimeError(f"Example failed replay: {row['q']}")
            row.update(checked)
        for source, rows in sources.items():
            for row in rows:
                sample(row, "smart", source)
        examples.update(path_examples(engine))
    finally:
        engine.close()  # Include late completions in journal costs.
    with sqlite3.connect(engine.decisions.path) as db:
        db.execute("CREATE TEMP TABLE measured_searches(search_id TEXT PRIMARY KEY)")
        db.executemany("INSERT INTO measured_searches VALUES (?)", smart_ids)
        calls, cached, failed, usd = db.execute("""
            SELECT count(*), coalesce(sum(cached),0), coalesce(sum(1-ok),0),
                   coalesce(sum(cost_usd),0) FROM llm_calls JOIN measured_searches USING(search_id)""").fetchone()
    by_flow = defaultdict(dict)
    for (intent, mode), records in buckets.items():
        stats = summarize(records)
        stats["by_dataset"] = {
            name: summarize([r for r in records if r[0] == name])
            for name in stats["datasets"]
        }
        by_flow[intent][mode] = stats
    write("examples.json", dict(version=1, by_flow=examples))
    write("timings.json", dict(version=1, release=subprocess.check_output(
        ["git","rev-parse","--short","HEAD"],cwd=ROOT,text=True).strip(),
        measured_at=datetime.now(timezone.utc).isoformat(), by_flow=by_flow,
        run_budget_usd=BUDGET, gateway=cfg.jev_url, model=cfg.jev_model,
        datasets={k:len(v) for k,v in sources.items()}, cost=dict(entries=calls,cached=cached,failed=failed,usd=usd),
        snapshot={name:hashlib.sha256((cfg.data/name).read_bytes()).hexdigest()
                  for name in ("catalog.jsonl","clients.jsonl","mock_families.jsonl")}))


def result_example(q, result, profile="guest"):
    cards = cards_from(result["blocks"])
    return dict(q=q, profile=profile, mode=result["mode"], intent=result["understood"]["intent"],
                first_card=cards[0]["title"] if cards else None,
                blocks=[b["type"] for b in result["blocks"]], ms=result["timing_ms"]["total"])


def smart_examples(engine):
    # Dev names acceptable products in the first five. For this exhibit require one at rank one.
    candidates = {"dev-0092", "dev-0147", "dev-0148", "dev-0149", "dev-0158", "dev-0216"}
    rows = []
    for dev in read_jsonl(ROOT / "eval/queries.dev.jsonl"):
        if dev["id"] not in candidates:
            continue
        targets = dev["assert"]["top5_any"]
        top = {"assert": {"top1_any": targets}}
        fast = request(engine, dev, "fast")
        if inspect(engine, top, fast)[0]["top1_any"]:
            continue
        smart = request(engine, dev, "smart")
        cost = smart["cost"]
        if (smart["mode"] != "smart" or cost["pending"] or not (cost["llm_calls"] or cost["cached"])
                or not inspect(engine, top, smart)[0]["top1_any"] or not all(inspect(engine, dev, smart)[0].values())):
            continue
        rows.append(dict(**result_example(dev["q"], smart, dev["profile"]), source=dev["id"],
                         fast_first_card=result_example(dev["q"], fast)["first_card"], expected_top=targets,
                         cost_usd=cost["usd"], cached=cost["cached"], calls=cost["llm_calls"],
                         saved_rub=cost["saved_rub"]))
        if len(rows) == 3:
            return rows
    raise ValueError(f"Only {len(rows)} verified smart corrections")


def file_examples(client):
    rows = []
    for filename, count in [("request.csv", 2), ("request.txt", 3), ("request-1c.xlsx", 2)]:
        path = ROOT / "docs/quote_examples" / filename
        data = path.read_bytes()
        start = perf_counter()
        uploaded = client.post("/api/spec/upload", params={"name": filename}, content=data)
        uploaded.raise_for_status()
        result = uploaded.json()
        lines = next(b["lines"] for b in result["blocks"] if b["type"] == "spec")
        matched = sum(bool(line["card"]) for line in lines)
        quote = client.get(f'/api/export/{result["search_id"]}', params={"format": "xlsx"})
        quote.raise_for_status()
        elapsed = round(1000 * (perf_counter() - start), 2)
        name = Message()
        name["Content-Disposition"] = quote.headers["Content-Disposition"]
        workbook = load_workbook(BytesIO(quote.content), read_only=True)
        try:
            assert "Коммерческое предложение" in workbook.sheetnames and "Не найдено" in workbook.sheetnames
        finally:
            workbook.close()
        assert len(lines) == count and matched > 0 and name.get_filename().endswith(".xlsx")
        row = result_example(filename, result)
        row.update(file=filename, positions=len(lines), matched=matched, ms=elapsed, quote_filename=name.get_filename())
        rows.append(row)
    return rows


def path_examples(engine):
    from fastapi.testclient import TestClient
    from kuznitsa.app import create_app

    paths = defaultdict(list)
    with TestClient(create_app(engine=engine)) as client:
        for q in ("касп", "крипто", "астр"):
            resp = client.get("/api/suggest", params={"q": q})
            resp.raise_for_status()
            result = resp.json()
            groups = result["groups"]
            suggestions = [item["text"] for group in groups for item in group["items"]][:3]
            assert suggestions
            paths["suggest"].append(dict(q=q, suggestions=suggestions, profile="guest", mode="fast", intent=None,
                                         first_card=None, blocks=[g["type"] for g in groups], ms=result["ms"]))
        paths["spec_file"] = file_examples(client)
        for q in ("КриптоПро CSP", "KL4867RAQFR", "Microsoft Windows 11 Pro"):
            for mode in ("fast", "smart"):
                resp = client.post("/api/search", json=dict(q=q, mode=mode, profile_id="guest",
                                                           source="ui", session_id=uuid4().hex))
                resp.raise_for_status()
                row = result_example(q, resp.json())
                assert row["mode"] == mode and "products" in row["blocks"] and row["first_card"]
                paths["widget"].append(dict(**row, source="ui", endpoint="/api/search"))
    for q, quantity in [("антивирус на тридцать компьютеров", 30), ("Р7 офис на двадцать пять мест", 25),
                        ("КриптоПро CSP на пять рабочих мест", 5)]:
        result = request(engine, {"q": q}, "fast")
        got = result["understood"]["qty"]
        assert got["value"] == quantity and "products" in [b["type"] for b in result["blocks"]]
        paths["voice"].append(dict(**result_example(q, result), quantity=got["value"], metric=got["metric"]))
    for code in ("86.23", "62.01", "49.41"):
        q = "оквэд " + code
        result = request(engine, {"q": q}, "fast")
        kit = next(b for b in result["blocks"] if b["type"] == "kit")
        assert result["understood"]["intent"] == "industry" and kit["role"] == engine.kb.rows["okved"][code]["industry"]
        paths["okved"].append(dict(**result_example(q, result), industry_id=kit["role"], industry_title=kit["title"]))
    for q, role in [("софт для учителя школы", "school_teacher"), ("софт для преподавателя вуза", "university_professor"),
                    ("софт для регистратора клиники", "clinic_registrar")]:
        result = request(engine, {"q": q}, "fast")
        kit = next(b for b in result["blocks"] if b["type"] == "kit")
        roles = engine.kb.rows["roles"]
        assert kit["role"] == role and kit["parent"]["id"] == roles[role]["parent"]
        assert kit["parent"]["q"] == roles[kit["parent"]["id"]]["title"]
        paths["kit_parent"].append(dict(**result_example(q, result), child_id=role, child_title=kit["title"], parent=kit["parent"]))
    for q in ("антивирус на 30 пк", "КриптоПро CSP", "rfcgthcrbq"):
        naive = request(engine, {"q": q}, "naive")
        fast = request(engine, {"q": q}, "fast")
        offers = next(b["total"] for b in naive["blocks"] if b["type"] == "products")
        cards = next(b["total"] for b in fast["blocks"] if b["type"] == "products")
        assert naive["mode"] == "naive" and fast["mode"] == "fast" and cards > 0
        paths["naive"].append(dict(**result_example(q, naive), offers=offers, fast_cards=cards))
    paths["smart"] = smart_examples(engine)
    return paths


def update_paths():
    payload = json.loads((OUT / "examples.json").read_text())
    engine = Engine.open(gateway_config())
    engine.decisions.run_budget = 0.007
    try:
        payload["by_flow"].update(path_examples(engine))
    finally:
        engine.close()
    write("examples.json", payload)


def path_caption(ident, r):
    if ident == "suggest":
        return " · ".join(r["suggestions"])
    if ident == "spec_file":
        return f'Найдено {r["matched"]} из {r["positions"]} позиций. КП {r["quote_filename"]}. Загрузка и экспорт заняли {r["ms"]} мс.'
    if ident == "voice":
        return f'Распознано количество {r["quantity"]}. Первая карточка — {r["first_card"]}.'
    if ident == "widget":
        return f'{r["mode"]} · {r["first_card"]}'
    if ident == "okved":
        return r["industry_title"]
    if ident == "kit_parent":
        return f'{r["child_title"]} → {r["parent"]["title"]}'
    if ident == "naive":
        return f'Обычный поиск — {r["offers"]} предложений, быстрый — {r["fast_cards"]} сгруппированных карточек.'
    if ident == "smart":
        return f'{r["fast_first_card"]} → {r["first_card"]}. Расход ${r["cost_usd"]:.8f}, решений из кэша — {r["cached"]}.'
    raise KeyError(ident)


def diagram(nodes, edges):
    lines = ["```mermaid", "flowchart TD"]
    for n in nodes:
        title = n["title"].replace('"', "#quot;")
        label = '{"' + title + '"}' if n.get("type") == "decision" else '["' + title + '"]'
        lines.append(f'    n_{n["id"]}{label}')
    for e in edges:
        label = "|" + e["label"] + "|" if e["label"] else ""
        lines.append(f'    n_{e["from"]} -->{label} n_{e["to"]}')
    return "\n".join(lines + ["```"])


@lru_cache(None)
def link(code):
    path, symbol = code.split(":")
    target = f"../{path}"
    if path.endswith(".py"):
        scope = ast.parse((ROOT / path).read_text())
        for name in symbol.split("."):
            scope = next(n for n in scope.body if getattr(n, "name", None) == name)
        target += f"#L{scope.lineno}"
    return f"[`{symbol}`]({target})"


def render():
    flows, timings, examples = [json.loads((OUT / name).read_text()) for name in
                                ("flows.json", "timings.json", "examples.json")]
    pipeline = flows["pipeline"]
    doc = ["# Как работает поиск «Кузница Softline»", "## От запроса до ответа",
           "Покупатель вводит название, задачу или условия закупки. Поиск распознаёт намерение, "
           "выбирает варианты лицензий и собирает ответ для этой задачи. У каждого поиска есть трасса.",
           diagram([dict(id=p["step"], title=p["title"]) for p in pipeline],
                   [{"from":a["step"], "to":b["step"], "label":""} for a,b in zip(pipeline,pipeline[1:])]),
           "\n".join(f'- **{p["title"]}.** {p["what"]} {link(p["code"])}' for p in pipeline),
           "## Как читать трассу",
           "Поле `understood.intent` показывает распознанную цель. В `trace` шаги идут в порядке выполнения. "
           "Статус `ok` означает, что шаг выполнен, `skip` — пропущен, `fallback` — выбран запасной путь. "
           "Причина и параметры находятся в `summary` и `detail`. Список `blocks` описывает результат для покупателя.",
           'В примерах `guest` означает гостевой поиск. Именованный профиль добавляет условия организации и сведения '
           'о её лицензиях. Блоки перечислены в порядке показа: `products` — предложения, `kit` — комплект, '
           '`spec` — расчёт по позициям, `answer` — пояснение, `clarify` — уточнение, `lead` — обращение к менеджеру, '
           '`crosssell` — сопутствующие товары. Время открытия страницы зависит также от браузера и сети.',
           f'Замер {timings["measured_at"][:10]}, версия {timings["release"]}. Один вызов на строку в каждом режиме. '
           f'В выборке {timings["datasets"]["dev"]} строк dev, {timings["datasets"]["seen"]} знакомых проб и '
           f'{timings["datasets"]["examples"]} повторных запросов из примеров. Группировка по фактическому виду и '
           'запрошенному режиму. Время в миллисекундах, без запуска движка, HTTP и отрисовки браузером. '
           'p50 — медиана, p95 — граница для 95% наблюдений. Повторы могут попадать в кэш.',
           'Шаг учитывает интервал с предыдущей отметки. Например, проверка условий и выбор предложения '
           'идут в одном цикле до отметки `filters`. Строка `variants` показывает промежуток до следующей '
           'отметки. Стоимость записи журнала измеряется отдельно. Полное время взято из `timing_ms.total`. '
           'Перцентили разных шагов складывать нельзя. ' + link("kuznitsa/engine.py:Trace.add"),
           "## Цена запроса",
           "Быстрый режим стоит **0 ₽ за внешние модели**. Умный режим берёт расход из журнала "
           "`llm_calls` по `search_id`. Попадание в кэш имеет нулевую стоимость. "
           "Если шлюз не прислал сумму, движок оценивает расход по входным токенам. Пересчёт в рубли использует "
           "настройку `KZ_USD_RUB`. При тайм-ауте окончательная запись может появиться позже ответа. "
           + link("kuznitsa/llm/decisions.py:Decisions.request"),
           f'За прогон журнал зарегистрировал {timings["cost"]["entries"]} решений, в том числе '
           f'{timings["cost"]["cached"]} из кэша и {timings["cost"]["failed"]} неуспешных. '
           'Ответ витрине может уйти по запасному пути до успешного завершения внешнего вызова. '
           f'Расход по журналу — **${timings["cost"]["usd"]:.6f}**.']
    for f in flows["flows"]:
        ident = f["id"]
        for anchor in [*f.get("guide_anchors", []), ident]:
            doc.append(f'<a id="{anchor}"></a>')
        doc.extend([f'## {f["title"]} (`{ident}`)', f["summary"]])
        if f["kind"] == "intent":
            table = ["| Запрос | Профиль | Первая карточка | Блоки ответа |",
                     "|---|---|---|---|"]
            for x in examples["by_flow"][ident]:
                query = x["q"].replace("\n", "<br>").replace("|", "\\|")
                table.append(f'| {query} | {x["profile"]} | {x["first_card"] or "Без карточки"} | {", ".join(x["blocks"])} |')
            doc.append("\n".join(table))
        else:
            if ident == "smart":
                doc.append("Слева — первая карточка быстрого поиска, справа — умного. Для этих запросов "
                           "в dev задан список подходящих продуктов. В каждом примере Jev поднял продукт из этого "
                           "списка на первое место, а ответ smart прошёл все проверки строки dev.")
            table = ["| Пример | Проверенный результат |", "|---|---|"]
            for row in examples["by_flow"][ident]:
                query = row["q"]
                if ident == "spec_file":
                    query = f'[{query}](quote_examples/{row["file"]})'
                table.append(f"| {query} | {path_caption(ident, row)} |")
            doc.append("\n".join(table))
        doc.append(diagram(f["nodes"], f["edges"]))
        if ident == "smart":
            doc.append("\n".join(f'- **{n["title"]}.** {n["detail"]} {link(n["code"])}'
                                 for n in f["nodes"] if n["id"] in {"goal", "kit", "recovery", "rerank"}))
        if f["llm"]:
            llm = f["llm"]
            doc.append(f'**Категоризатор.** Движок задаёт вопрос «{llm["question"]}» {llm["when"][0].lower() + llm["when"][1:]}.\n\nДопустимые варианты — '
                       + ", ".join(llm["options"]) + '. Минимальная вероятность выбора — ' + str(llm["threshold"]).replace(".", ",") + '. '
                       + llm["fallback"])
        if f["kind"] == "intent":
            stats = timings["by_flow"][ident]
            doc.append(f'**Время шагов, мс.** Быстрых запросов — {stats["fast"]["n"]}, '
                       f'умных — {stats["smart"]["n"]}, из них с возвратом к быстрому режиму — '
                       f'{stats["smart"]["returned_mode"].get("fast", 0)}.')
            table = ["| Шаг | fast p50 | fast p95 | smart p50 | smart p95 |","|---|---:|---:|---:|---:|"]
            for step in [*pipeline,dict(step="total",title="Весь запрос")]:
                cells = []
                for mode in ("fast","smart"):
                    record = stats[mode]
                    ms = record["total"] if step["step"] == "total" else record["steps"][step["step"]]
                    cells.extend(f'{ms[key]:.2f}' for key in ("p50","p95"))
                table.append("| " + " | ".join([step["title"], *cells]) + " |")
            doc.append("\n".join(table))
        refs = f["speed_code"]
        doc.extend(["**За счёт чего быстро.** " + " ".join(f["speed"]) + " " + " · ".join(map(link,refs)),
                    "**Что получает бизнес.** " + " ".join(f["business"])])
    (ROOT / "docs/FLOWS.md").write_text("\n\n".join(doc) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--paths-only", action="store_true", help="Verify path examples and rebuild Markdown")
    commands.add_argument("--render-only", action="store_true", help="Rebuild Markdown from existing JSON")
    args = parser.parse_args()
    if args.paths_only:
        update_paths()
    elif not args.render_only:
        measure()
    render()
