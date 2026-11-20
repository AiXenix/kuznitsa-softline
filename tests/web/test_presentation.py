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
    assert {s["route"] for s in steps} == {"short", "long"}
    assert len({s["id"] for s in steps}) == len(steps)
    for step in steps:
        assert step["profile"] in {p["id"] for p in meta["profiles"]}
        assert step["mode"] in meta["modes"]
        assert step["action"] in {"search", "suggest", "compare_modes", "compare_profiles", "spec", "open"}
        assert step["title"] and step["say"]
        assert step["page"].startswith("/admin#") if step["action"] == "open" else step["q"]


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
