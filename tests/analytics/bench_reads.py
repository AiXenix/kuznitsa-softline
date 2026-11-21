"""Замер одного процесса, с загрузкой готовых сводок из SQLite и получением тела через ASGI."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from time import perf_counter
from fastapi.testclient import TestClient
from kuznitsa.app import create_app
from kuznitsa.config import Config


def measure():
    os.environ["KZ_ADMIN_OPEN"]="1"
    with TestClient(create_app(cfg=Config())) as api:
        j=api.app.state.engine.journal
        paths=["kpi","kpi?view=overview","kpi?engine=legacy","kpi?segment=smb","kpi?segment=guest","kpi?intent=product",
               "kpi?category=accounting","failures","gaps","cost","ingest","rules","weights","insights","insights?view=list",
               "eval","digest?role=head_ecom","digest?role=head"]
        paths.extend("queries?kind="+kind for kind in ("top","zero","low_ctr","rising","reformulated","recent"))
        latest=j.rows("SELECT id FROM active_replay")
        if latest:
            paths.append("replay/"+latest[0]["id"])
        sample=j.rows("SELECT search_id FROM searches WHERE source='replay' LIMIT 1")
        if sample:
            paths.append("search/"+sample[0]["search_id"])

        def get(path):
            start=perf_counter()
            response=api.get("/api/admin/"+path)
            elapsed=(perf_counter()-start)*1000
            assert response.status_code==(422 if path=="digest?role=head" else 200),path
            return dict(path=path,ms=round(elapsed,1),bytes=int(response.headers["content-length"]))

        serial=[get(path) for path in paths for _ in range(3)]
        batches=[]
        for tab,group in [("ecom",["kpi","queries?kind=low_ctr","failures","insights?role=ecom_manager","rules"]),
                          ("product",["kpi","queries?kind=top","queries?kind=rising","gaps","insights?role=product_manager"])]:
            with ThreadPoolExecutor(len(group)) as pool:
                start=perf_counter()
                requests=list(pool.map(get,group))
                batches.append(dict(tab=tab,wall_ms=round((perf_counter()-start)*1000,1),requests=requests))
        return dict(serial=serial,tabs=batches)


if __name__=="__main__":
    print(json.dumps(measure(),indent=2,ensure_ascii=False))
