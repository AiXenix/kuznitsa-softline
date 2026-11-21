import ast
from functools import lru_cache
import json
from pathlib import Path
import re

from kuznitsa.understand.intent import TITLES


ROOT = Path(__file__).resolve().parents[1]
PATHS = {"suggest", "spec_file", "voice", "widget", "okved", "kit_parent", "naive", "smart", "priorities", "refine", "not_sold"}


def load(name):
    payload = json.loads((ROOT / "docs/flows" / (name + ".json")).read_text())
    assert payload["version"] == 1
    return payload


@lru_cache(None)
def check_reference(ref):
    filename, symbol = ref.split(":")
    source = (ROOT / filename).read_text()
    if filename.endswith(".js"):
        assert re.search(r"\bfunction\s+" + re.escape(symbol) + r"\s*\(", source), ref
        return
    scope = ast.parse(source)
    for name in symbol.split("."):
        matches = [n for n in scope.body if getattr(n, "name", None) == name]
        assert len(matches) == 1, ref
        scope = matches[0]
    assert isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)), ref


def test_flow_graphs_and_references():
    data = load("flows")
    pipeline = {p["step"] for p in data["pipeline"]}
    assert len(pipeline - {"refine"}) == 15 and len(data["pipeline"]) == len(pipeline)
    for step in data["pipeline"]:
        check_reference(step["code"])
    flows = data["flows"]
    assert len(flows) == len(TITLES) + len(PATHS)
    assert {f["id"] for f in flows if f["kind"] == "intent"} == set(TITLES)
    assert {f["id"] for f in flows if f["kind"] == "path"} == PATHS
    for f in flows:
        for ref in f["speed_code"]:
            check_reference(ref)
        ids = {n["id"] for n in f["nodes"]}
        assert len(ids) == len(f["nodes"])
        for node in f["nodes"]:
            check_reference(node["code"])
            draft_steps = {"refine"} if f.get("draft") and f["id"] == "refine" else set()
            assert node.get("step") in pipeline | draft_steps | {None}
        for edge in f["edges"]:
            assert {edge["from"], edge["to"]} <= ids
        reached = {n["id"] for n in f["nodes"] if n["type"] == "input"}
        for _ in ids:
            reached.update(e["to"] for e in f["edges"] if e["from"] in reached)
        assert reached == ids, f["id"]


def test_verified_examples_and_timing_coverage():
    examples = load("examples")["by_flow"]
    timings = load("timings")
    stats = timings["by_flow"]
    steps = {p["step"] for p in load("flows")["pipeline"]}
    active_contracts = {f["id"] for f in load("flows")["flows"] if f["id"] in ("refine","not_sold") and not f.get("draft")}
    assert set(stats) == set(TITLES) | {"priorities"} | active_contracts
    assert set(examples) == set(TITLES) | PATHS
    for intent in TITLES:
        rows = examples[intent]
        assert len({r["q"] for r in rows}) >= 5
        for r in rows:
            assert r["intent"] == intent and r["blocks"] and r["profile"] and r["ms"] >= 0
            assert r["mode"] in {"fast", "smart"} and "first_card" in r
        assert set(stats[intent]) == {"fast", "smart"}
        for measured in stats[intent].values():
            assert measured["n"] == sum(measured["datasets"].values()) > 0
            assert {k: v["n"] for k, v in measured["by_dataset"].items()} == measured["datasets"]
            assert all(steps - {"refine"} <= set(v["steps"]) for v in measured["by_dataset"].values())
            assert steps - {"refine"} <= set(measured["steps"])
            for pair in [measured["total"], *measured["steps"].values()]:
                assert 0 <= pair["p50"] <= pair["p95"]
    for mode in ("fast", "smart"):
        for source, expected in timings["datasets"].items():
            assert sum(stats[intent][mode]["datasets"].get(source, 0) for intent in TITLES) == expected


def test_document_anchors_and_path_examples():
    flows = load("flows")["flows"]
    doc = (ROOT / "docs/FLOWS.md").read_text()
    examples = load("examples")["by_flow"]
    assert not re.search(r"\bход(?:а|е|у|ом)?\s*\d", doc, re.I)
    for flow in flows:
        ident = flow["id"]
        anchor = f'<a id="{ident}"></a>'
        assert doc.count(anchor) == 1
        assert f'{anchor}\n\n## {flow["title"]} (`{ident}`)' in doc
    for alias, ident in (("spec_file_kp", "spec_file"), ("voice_words", "voice")):
        assert f'<a id="{alias}"></a>\n\n<a id="{ident}"></a>' in doc
    for path in PATHS:
        rows = examples[path]
        if any(f["id"] == path and f.get("draft") for f in flows):
            assert not rows
            continue
        assert len({r["q"] for r in rows}) >= (1 if path in {"refine", "not_sold"} else 3)
        for row in rows:
            assert {"q", "profile", "mode", "intent", "first_card", "blocks", "ms"} <= row.keys()
            assert row["ms"] >= 0
    assert all(r["suggestions"] for r in examples["suggest"])
    for r in examples["spec_file"]:
        assert (ROOT / "docs/quote_examples" / r["file"]).is_file()
        assert 0 < r["matched"] <= r["positions"] and r["quote_filename"].endswith(".xlsx")
    assert all(r["quantity"] > 0 for r in examples["voice"])
    widget = examples["widget"]
    for q in {r["q"] for r in widget}:
        assert {r["mode"] for r in widget if r["q"] == q and r["source"] == "ui"} == {"fast", "smart"}
    assert all(r["industry_id"] and r["intent"] == "industry" for r in examples["okved"])
    assert all(r["child_id"] != r["parent"]["id"] and r["parent"]["q"] for r in examples["kit_parent"])
    assert all(r["offers"] >= 0 and r["fast_cards"] > 0 for r in examples["naive"])
    assert all(r["first_card"] != r["fast_first_card"] and r["cost_usd"] >= 0
               and r["expected_top"] for r in examples["smart"])


def test_priorities_preview_and_draft_contracts():
    examples = load("examples")["by_flow"]["priorities"]
    stats = load("timings")["by_flow"]["priorities"]
    assert set(stats) == {"fast"} and stats["fast"]["n"] == len(examples)
    assert "business" in stats["fast"]["steps"]
    for row in examples:
        assert row["matched"] > 0 and row["baseline_first"] and row["first_card"]
        assert row["rule"]["scope"]["segments"] == ["gov"]
        assert 0 <= row["steps"]["business"] <= row["ms"]
    from scripts.flow_timings import contract_evidence
    result = dict(understood=dict(chips=[], zero_reason="not_in_catalog"), trace=[], blocks=[])
    assert not contract_evidence("refine", result, "smart")
    assert not contract_evidence("not_sold", result, "fast")


def test_verified_contracts_promote_their_own_drafts(tmp_path, monkeypatch):
    from scripts import flow_timings as runner
    import yaml

    out = tmp_path / "docs/flows"
    out.mkdir(parents=True)
    (out / "flows.json").write_text(json.dumps(load("flows")))
    gallery = tmp_path / "docs/scenarios.yaml"
    gallery.write_text((ROOT / "docs/scenarios.yaml").read_text())
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "OUT", out)
    result = dict(understood=dict(refined=dict(audience="home", line=None, source="jev", probability=.8),
                                 chips=[dict(key="refined", removable=True)]),
                  trace=[dict(step="refine")], blocks=[])
    evidence = runner.contract_evidence("refine", result, "smart")
    assert evidence and not runner.contract_evidence("refine", result, "fast")
    runner.update_contracts({"refine": [dict(**evidence, steps={"entities": 1, "refine": 2})], "not_sold": []})
    flows = json.loads((out / "flows.json").read_text())["flows"]
    assert not next(f for f in flows if f["id"] == "refine").get("draft")
    assert next(f for f in flows if f["id"] == "not_sold")["draft"]
    records = {r["id"]: r for r in yaml.safe_load(gallery.read_text())}
    assert not records["audience_from_slang"]["pending"]
    assert records["not_sold_nearest"]["pending"]


def test_not_sold_contract_requires_orderable_replacements_and_faq():
    from scripts.flow_timings import contract_evidence
    card = {"card_id": "sample", "title": "Бизнес-лицензия", "offer": {"available": True}}
    result = {"understood": {"zero_reason": "not_in_catalog"}, "blocks": [
        {"type": "not_in_catalog", "text": "В магазине только корпоративные лицензии."},
        {"type": "analogs", "items": [{"card": card}]},
        {"type": "answer", "source": "faq:home_office"}]}
    assert contract_evidence("not_sold", result, "fast")["alternatives"] == [card["title"]]
    card["offer"]["available"] = False
    assert not contract_evidence("not_sold", result, "fast")
    card["offer"]["available"] = True
    result["blocks"].pop()
    assert not contract_evidence("not_sold", result, "fast")


def test_gallery_skips_pending_and_checks_active_contract(tmp_path, monkeypatch):
    import yaml
    from scripts import check_scenarios

    case = dict(id="audience_from_slang", contract="refine", intent="vendor", surface="search",
                demo={"q": "каспер для хоума"})
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "scenarios.yaml").write_text(yaml.safe_dump([{"pending": True}, case]))
    monkeypatch.setattr(check_scenarios, "ROOT", tmp_path)

    class LocalEngine:
        refined = {}

        def search(self, req):
            return dict(understood=dict(intent="vendor", chips=[dict(key="refined", removable=True)],
                                        refined=self.refined), blocks=[{"type": "products", "items": ["item"]}],
                        mode=req.mode, timing_ms={"total": 1}, trace=[])

    engine = LocalEngine()
    [(record, _)] = check_scenarios.gallery(engine, "fast")
    assert not record["ok"]
    engine.refined = dict(audience="home", source="dict")
    [(record, _)] = check_scenarios.gallery(engine, "fast")
    assert record["ok"] and record["contract"] == "refine"
