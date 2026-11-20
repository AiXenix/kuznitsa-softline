import json
from pathlib import Path
import re
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from kuznitsa.app import create_app

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs/admin_examples"


def test_console_http_contract(cfg, monkeypatch):
    monkeypatch.setenv("KZ_ADMIN_OPEN", "1")
    with TestClient(create_app(cfg=cfg)) as api:
        paths = api.get("/openapi.json").json()["paths"]
        for method, suffixes in {
            "get": ("kpi", "queries", "failures", "gaps", "insights", "rules", "weights",
                    "replay/{ident}", "search/{search_id}", "cost", "eval", "ingest"),
            "post": ("preview", "rules", "weights", "insights/refresh", "insights/{ident}/{operation}"),
            "put": ("rules/{ident}",), "delete": ("rules/{ident}",)
        }.items():
            for suffix in suffixes:
                assert method in paths["/api/admin/" + suffix]
        for page in ("/admin", "/inspect/by-query", "/inspect/s_saved", "/card/sample"):
            assert api.get(page).status_code == 200
        search = api.post("/api/search", json={"q": "щит", "mode": "fast", "source": "ui"}).json()
        lookup = "/api/admin/ui/search-reference"
        assert api.get(lookup, params={"q": "щит"}).json()["search_id"] == search["search_id"]
        assert api.get(lookup, params={"q": "фразы нет в журнале"}).status_code == 404
        monkeypatch.setenv("KZ_ADMIN_OPEN", "0")
        assert api.get(lookup, params={"q": "щит"}).status_code == 403


def test_console_renderers_with_journal_examples(tmp_path):
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        pytest.skip("Нужен локальный Chrome")
    data = {path.stem: json.loads(path.read_text()) for path in EXAMPLES.glob("*.json")}
    data["insights"]["items"] = [data["insight-verify"], data["insight-reject"]]
    js = (Path(__file__).parent / "admin_render.browser.js").read_text()
    js = js.replace("./admin/", (ROOT / "web/js/admin").as_uri() + "/")
    html = tmp_path / "console.html"
    html.write_text('<body><output></output><main></main><script id="fixtures" type="application/json">'
                    + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + '</script><script type="module">'
                    + js + '</script>')
    r = subprocess.run([chrome, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                        "--disable-background-networking", "--allow-file-access-from-files",
                        "--user-data-dir=" + str(tmp_path / "chrome"), "--virtual-time-budget=8000",
                        "--dump-dom", html.as_uri()], capture_output=True, text=True, timeout=30, check=True)
    assert re.search(r"<output>passed</output>", r.stdout), re.search(r"<output>(.*?)</output>", r.stdout, re.S)[1]
