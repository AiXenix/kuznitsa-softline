import json
import re
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from kuznitsa.app import create_app

WEB = Path(__file__).resolve().parents[2] / "web"
FIXTURES = WEB / "fixtures"


@pytest.fixture(scope="module")
def client(cfg):
    with TestClient(create_app(cfg=cfg)) as session:
        yield session


@pytest.mark.parametrize("path", ["/", "/scenarios", "/inspect/s_demo", "/about", "/styleguide", "/admin"])
def test_pages(client, path):
    page = client.get(path)
    assert page.status_code == 200
    assert page.headers["Cache-Control"] == "no-store"
    assert page.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert 'type="module" src="/web/js/store.js"' in page.text
    assert "Демонстрационный стенд хакатона." in page.text


@pytest.mark.parametrize("path", ["js/blocks.js", "css/store.css", "fixtures/products.json"])
def test_static(client, path):
    url = f"/web/{path}"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-cache"
    assert client.get(url, headers={"If-None-Match": response.headers["ETag"]}).status_code == 304


def test_missing_asset(client):
    assert client.get("/web/js/absent.js").status_code == 404


@pytest.mark.parametrize("path", sorted(WEB.rglob("*.js")), ids=lambda p: p.name)
def test_javascript(path):
    subprocess.run(["node", "--check", str(path)], check=True)


def fixture(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())


def test_block_examples(client):
    fields = {
        "products": "total items", "kit": "slots seats total", "analogs": "source items",
        "answer": "text source links", "spec": "lines total unresolved", "compare": "columns rows",
        "not_in_catalog": "reason text", "categories": "items", "vendors": "items",
        "my_licenses": "items", "clarify": "question options", "services": "items",
        "promo": "text items", "lead": "text action", "crosssell": "items", "future_block": "",
    }
    assert set(fixture("index")) == set(fields)
    for name, keys in fields.items():
        response = client.get(f"/web/fixtures/{name}.json")
        block, = response.json()["blocks"]
        assert block["type"] == name and block["title"]
        assert all(block[key] is not None for key in keys.split())
    assert set(fixture("states")) == {"loading", "empty", "error"}


def test_nested_example_contract():
    product = fixture("products")
    card = product["blocks"][0]["items"][0]
    assert {"rel", "pop", "margin", "pers"} == card["score"]["parts"].keys()
    assert card["offer"]["offer_id"] and card["variants"][0]["name"]
    assert card["calc"]["total"] == card["calc"]["qty"] * card["calc"]["unit_price"]
    assert len(product["trace"]) == 15
    assert all({"step", "title", "status", "ms", "summary", "detail"} <= s.keys() for s in product["trace"])
    block = lambda name: fixture(name)["blocks"][0]
    for name in ["vendors", "categories"]:
        assert all({"id", "title", "count"} <= item.keys() for item in block(name)["items"])
    assert {l["status"] for l in block("spec")["lines"]} == {"matched", "ambiguous", "not_found"}
    assert all(len(row["values"]) == len(block("compare")["columns"]) for row in block("compare")["rows"])
    assert block("kit")["slots"][0]["alternatives"][0]["offer"]["offer_id"]
    assert block("analogs")["items"][0]["card"]["calc"]["qty"] is None
    assert block("services")["items"][0]["offer"]["price_on_request"]
    assert block("my_licenses")["items"][0]["renew_offer"]["offer_id"]
    assert all("apply" in o for o in block("clarify")["options"])
    assert block("crosssell")["items"][0]["reason"]


def test_all_module_imports_resolve(client):
    """Syntax checks alone do not catch broken static imports or missing exports."""
    for script in (WEB / "js").rglob("*.js"):
        imports = re.findall(r"import\s*\{([^}]+)\}\s*from\s*'([^']+)'", script.read_text())
        for names, relative in imports:
            target = (script.parent / relative).resolve()
            assert target.is_relative_to(WEB)
            response = client.get("/web/" + target.relative_to(WEB).as_posix())
            assert response.status_code == 200 and "javascript" in response.headers["Content-Type"]
            exports = re.findall(r"export (?:async )?(?:function|const) ([\w$]+)", response.text)
            assert set(name.strip() for name in names.split(",")) <= set(exports)


def test_flow_documents(client, tmp_path, monkeypatch):
    from kuznitsa import pages
    monkeypatch.setattr(pages, "FLOW_DOCS", tmp_path)
    assert client.get("/flows").status_code == 200
    assert client.get("/web-data/flows/flows").json()["sample"]
    (tmp_path / "flows.json").write_text('{"version":1,"flows":[]}')
    assert client.get("/web-data/flows/flows").json()["flows"] == []
    assert client.get("/web-data/flows/examples").status_code == 404
    assert client.get("/web-data/flows/unpublished").status_code == 404
