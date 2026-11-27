import json
from pathlib import Path
import re
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from kuznitsa.app import create_app

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def test_n6_facets_fixture_contract(cfg):
    with TestClient(create_app(cfg=cfg)) as client:
        resp = client.get("/web/fixtures/facets.json")
        assert resp.status_code == 200
        data = resp.json()
    keys = [f["key"] for f in data["facets"]]
    assert {"vendor", "category", "price_max"} <= set(keys)
    vendor = next(f for f in data["facets"] if f["key"] == "vendor")
    assert len(vendor["values"]) > 8


def test_n6_mobile_css_rules():
    shop_css = (WEB / "css/shop.css").read_text()
    assert "flex-wrap:nowrap;overflow-x:auto" in shop_css
    assert "overflow-x:hidden" in shop_css


def test_n6_browser_renderers(tmp_path):
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        pytest.skip("Нужен локальный Chrome")
    data = json.loads((WEB / "fixtures/facets.json").read_text())
    js = (ROOT / "tests/web/n6_render.browser.js").read_text()
    js = js.replace("./store/", (WEB / "js").as_uri() + "/")
    html = tmp_path / "n6.html"
    html.write_text(
        '<body><output></output><main></main><script id="fixtures" type="application/json">'
        + json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        + '</script><script type="module">'
        + js
        + "</script>"
    )
    r = subprocess.run(
        [
            chrome,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--allow-file-access-from-files",
            "--user-data-dir=" + str(tmp_path / "chrome"),
            "--virtual-time-budget=8000",
            "--dump-dom",
            html.as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert re.search(r"<output>passed</output>", r.stdout), re.search(r"<output>(.*?)</output>", r.stdout, re.S)[1]
