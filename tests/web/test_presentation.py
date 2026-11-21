import json
from urllib.parse import parse_qs, urlsplit
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from kuznitsa.app import create_app
from kuznitsa.schema import Client

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"


def test_show_steps_use_catalog_profiles(cfg, tmp_path):
    shutil.copy(cfg.data / "catalog.jsonl", tmp_path)
    profiles = yaml.safe_load((ROOT / "mock/spec/profiles.yaml").read_text())["profiles"]
    clients = [Client(client_id=p["id"], title=p["title"], segment=p["segment"] or "smb", demo=True) for p in profiles]
    (tmp_path / "clients.jsonl").write_text("\n".join(c.model_dump_json() for c in clients))
    with TestClient(create_app(cfg=replace(cfg, data=tmp_path))) as api:
        meta = api.get("/api/meta").json()
        steps = api.get("/web/demo/steps.json").json()
    assert {s["route"] for s in steps} == {"short", "long", "priority"}
    assert len({s["id"] for s in steps}) == len(steps)
    final = [s for s in steps if s["route"] == "long"]
    assert [s["mode"] for s in final if s["q"] == "каспер для хоума"] == ["fast", "smart"]
    for route in ("long", "priority"):
        prefix = route + "-backup-"
        scene = [s for s in steps if s["id"].startswith(prefix)]
        assert [s["id"][len(prefix):] for s in scene] == ["enable", "preview", "guest", "gov_clinic", "disable"]
        assert [s["page"] for s in scene if s["action"] == "open"] == [
            "/admin#settings?section=priorities&scene=backup&phase=" + phase for phase in ("enable", "preview", "disable")]
        assert [(s["q"], s["profile"], s["mode"]) for s in scene if s["action"] == "search"] == [
            ("резервное копирование", profile, "fast") for profile in ("guest", "gov_clinic")]
    assert any(s["action"] == "upload" for s in final) and final[-1]["page"] == "/docs"
    for step in steps:
        assert step["profile"] in {p["id"] for p in meta["profiles"]}
        assert step["mode"] in meta["modes"]
        assert step["action"] in {"search", "suggest", "compare_modes", "compare_profiles", "spec", "upload", "open"}
        assert step["title"] and step["say"]
        assert step["page"].split("?")[0].split("#")[0] in {"/admin", "/embed", "/flows", "/docs"} if step["action"] == "open" else step["q"]


def test_search_button_cannot_wrap():
    css = (WEB / "css/store.css").read_text()
    rules = re.findall(r"\.bar \.primary\s*\{([^}]+)\}", css)
    assert any("white-space:nowrap" in rule and "min-width:" in rule for rule in rules)


def test_address_round_trip(tmp_path):
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        pytest.skip("Нужен локальный Chrome")
    source = (WEB / "js/address.js").read_text()
    # Inline module runs without an HTTP server and exercises the production functions.
    page = tmp_path / "address.html"
    page.write_text("""<body><output></output><script type="module">""" + source + """
      const req={q:'Офис & C++\\nна 30 мест',profile_id:'smb_trade',mode:'fast',category:'security'};
      const path=address(req,'profiles','https://demo.invalid/?show=1');
      const url=new URL(path,'https://demo.invalid');
      const saved=readAddress(url.search);
      if(Object.entries(req).every(([k,v])=>saved[k]===v) && saved.compare==='profiles'
          && url.searchParams.get('show')==='1')document.querySelector('output').textContent='passed';
    </script>""")
    result = subprocess.run([chrome, "--headless", "--no-sandbox", "--disable-gpu",
                             "--disable-background-networking", "--disable-dev-shm-usage",
                             "--user-data-dir=" + str(tmp_path / "chrome"), "--dump-dom", page.as_uri()],
                            capture_output=True, text=True, timeout=20, check=True)
    assert "<output>passed</output>" in result.stdout


def test_show_example_file_and_widget():
    import csv
    with (WEB / "demo/specification.csv").open() as source:
        items = list(csv.DictReader(source, delimiter=";"))
    assert items and all(row["Наименование"] and int(row["Количество"]) > 0 for row in items)
    steps = json.loads((WEB / "demo/steps.json").read_text())
    widget, = [s for s in steps if s["page"].startswith("/embed")]
    params = parse_qs(urlsplit(widget["page"]).query)
    assert params["mode"] == ["fast"] and params["q"][0].strip()
    assert {s["traceStep"] for s in steps if "traceStep" in s} == {"refine"}
