import ast
from functools import lru_cache
import json
from pathlib import Path
import re

from kuznitsa.understand.intent import TITLES


ROOT = Path(__file__).resolve().parents[1]
PATHS = {"suggest", "spec_file", "voice", "widget", "okved", "kit_parent", "naive", "smart"}


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
    assert len(pipeline) == len(data["pipeline"]) == 15
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
            assert node.get("step") in pipeline | {None}
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
    assert set(stats) == set(TITLES)
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
            assert all(set(v["steps"]) == steps for v in measured["by_dataset"].values())
            assert set(measured["steps"]) == steps
            for pair in [measured["total"], *measured["steps"].values()]:
                assert 0 <= pair["p50"] <= pair["p95"]
    for mode in ("fast", "smart"):
        for source, expected in timings["datasets"].items():
            assert sum(m[mode]["datasets"].get(source, 0) for m in stats.values()) == expected


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
        assert len({r["q"] for r in rows}) >= 3
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
