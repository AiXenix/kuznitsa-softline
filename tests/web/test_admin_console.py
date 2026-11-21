import base64
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest
from openpyxl import Workbook

from kuznitsa.app import create_app

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs/admin_examples"


def test_console_http_contract(cfg, monkeypatch):
    monkeypatch.setenv("KZ_ADMIN_OPEN", "1")
    with TestClient(create_app(cfg=cfg)) as api:
        assert 'src="/web/embed/widget.js"' in api.get("/embed").text
        paths = api.get("/openapi.json").json()["paths"]
        for method, suffixes in {
            "get": ("kpi", "queries", "failures", "gaps", "insights", "rules", "weights",
                    "replay/{ident}", "search/{search_id}", "cost", "eval", "ingest", "digest"),
            "post": ("preview", "rules", "weights", "insights/refresh", "insights/{ident}/{operation}"),
            "put": ("rules/{ident}",), "delete": ("rules/{ident}",)
        }.items():
            for suffix in suffixes:
                assert method in paths["/api/admin/" + suffix]
        for page in ("/admin", "/inspect/by-query", "/inspect/s_saved", "/card/sample"):
            assert api.get(page).status_code == 200
        search = api.post("/api/search", json={"q": "щит", "mode": "fast", "source": "ui"}).json()
        journal = api.app.state.engine.journal
        with journal.transaction() as db:
            for index, (source, zero) in enumerate([("history", 1), ("history", 0), ("replay", 1)]):
                db.execute("INSERT INTO searches(search_id,source,ts,zero) VALUES(?,?,?,?)",
                           (f"period-{index}", source, 22 * 3600, zero))
        period = "/api/admin/ui/history-days"
        assert api.get(period).json()["items"] == [{"key": "1970-01-02", "searches": 2, "zero_rate": 0.5}]
        lookup = "/api/admin/ui/search-reference"
        assert api.get(lookup, params={"q": "щит"}).json()["search_id"] == search["search_id"]
        assert api.get(lookup, params={"q": "фразы нет в журнале"}).status_code == 404
        monkeypatch.setenv("KZ_ADMIN_OPEN", "0")
        assert api.get(lookup, params={"q": "щит"}).status_code == 403
        assert api.get(period).status_code == 403


@pytest.mark.parametrize("fixture_script", ["admin_render.browser.js", "c3_render.browser.js", "c4_render.browser.js"])
def test_console_renderers_with_journal_examples(tmp_path, fixture_script):
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        pytest.skip("Нужен локальный Chrome")
    data = {path.stem: json.loads(path.read_text()) for path in EXAMPLES.glob("*.json")}
    data["insights"]["items"] = [data["insight-verify"], data["insight-reject"]]
    js = (Path(__file__).parent / fixture_script).read_text()
    js = js.replace("./admin/", (ROOT / "web/js/admin").as_uri() + "/")
    js = js.replace("./store/", (ROOT / "web/js").as_uri() + "/")
    js = js.replace("./embed/", (ROOT / "web/embed").as_uri() + "/")
    if fixture_script == "c3_render.browser.js":
        data = [json.loads(p.read_text()) for p in sorted((ROOT / "docs/api_examples").glob("*.json"))]
    if fixture_script == "c4_render.browser.js":
        book = Workbook()
        book.active.title = "Коммерческое предложение"
        book.active.append(["Наименование", "Количество"])
        book.active.append(["Астра", 50])
        book.create_sheet("Не найдено")
        content = BytesIO()
        book.save(content)
        data = {"xlsx": base64.b64encode(content.getvalue()).decode("ascii")}
    html = tmp_path / "console.html"
    html.write_text('<body><output></output><main></main><script id="fixtures" type="application/json">'
                    + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + '</script><script type="module">'
                    + js + '</script>')
    r = subprocess.run([chrome, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                        "--disable-background-networking", "--allow-file-access-from-files",
                        "--user-data-dir=" + str(tmp_path / "chrome"), "--virtual-time-budget=8000",
                        "--dump-dom", html.as_uri()], capture_output=True, text=True, timeout=30, check=True)
    assert re.search(r"<output>passed</output>", r.stdout), re.search(r"<output>(.*?)</output>", r.stdout, re.S)[1]
