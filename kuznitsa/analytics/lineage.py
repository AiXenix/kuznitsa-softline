"""Связь деможурнала, файла целей и метода парного сравнения."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import time

from kuznitsa.config import ROOT
from .store import dump

HISTORY_KEY="settings:mock_build"
STALE_HISTORY="Сборки журнала, каталога и разметки не совпадают или их версия неизвестна. Пересоберите историю и выполните парный прогон."
STALE_REPLAY="Парный прогон относится к другой сборке данных или версии сравнения. Выполните replay для текущего журнала."


@lru_cache(32)
def _sha(path,signature):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def sha(path):
    try:
        stat=path.stat()
        return _sha(path,(stat.st_dev,stat.st_ino,stat.st_ctime_ns,stat.st_size))
    except FileNotFoundError:
        return None


def code_stamp(paths):
    return hashlib.sha256(dump([sha(ROOT/p) for p in paths]).encode()).hexdigest()


def generator_stamp(model=None):
    paths=("kuznitsa/mock/querylog_gen.py","kuznitsa/plans/naive.py","kuznitsa/text.py")
    if model=="feed":
        paths+=("kuznitsa/analytics/feed_history.py",)
    return code_stamp(paths)


def save_mock(db,directory,truth,seed,day,model=None):
    path=directory/"mock_truth.jsonl"
    with NamedTemporaryFile(dir=directory,delete=False) as stream:
        stream.write(("\n".join(truth)+"\n").encode())
    Path(stream.name).replace(path)
    receipt=dict(generator=generator_stamp(model),truth=sha(path),catalog=sha(directory/"catalog.jsonl"),
                 rows=len(truth),seed=seed,day=str(day))
    if model:
        receipt["model"]=model
    db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",(HISTORY_KEY,dump(receipt),time()))


def snapshot(j):
    """Без меток товаров. Полные файлы хешируются только при изменении на диске."""
    directory=Path(j.path).parent
    kv={r["key"]:r for r in j.rows("SELECT * FROM kv WHERE key IN (?,?)",(HISTORY_KEY,"settings:history_source"))}
    source=kv.get("settings:history_source",{})
    kind=source.get("value")
    mock=kind=="mock" or (not kind and ((directory/"mock_truth.jsonl").is_file() or
               bool(j.rows("SELECT 1 FROM searches WHERE search_id GLOB 's_mock_*' LIMIT 1"))))
    catalog=sha(directory/"catalog.jsonl")
    stamp=dict(mode="mock" if mock else kind or "journal",catalog=catalog,
               method=code_stamp(("kuznitsa/analytics/replay.py","kuznitsa/analytics/rollup.py","kuznitsa/engine.py")))
    if mock:
        try:
            receipt=json.loads(kv.get(HISTORY_KEY,{}).get("value","null"))
        except (TypeError,ValueError):
            return None,STALE_HISTORY
        if not isinstance(receipt,dict) or receipt.get("generator")!=generator_stamp(receipt.get("model")) or receipt.get("catalog")!=catalog or not receipt.get("truth") or receipt["truth"]!=sha(directory/"mock_truth.jsonl"):
            return None,STALE_HISTORY
        stamp["history"]=receipt
    else:
        stamp["history"]=source.get("updated")
    return stamp,None


def warning(j,ident=None):
    current,note=snapshot(j)
    if note:
        return note
    if ident is None:
        active=j.rows("SELECT id FROM active_replay")
        if not active:
            return None
        ident=active[0]["id"]
    receipt=j.rows("SELECT value FROM kv WHERE key=?",("settings:paired_build:"+ident,))
    try:
        stored=json.loads(receipt[0]["value"]) if receipt else None
    except (TypeError,ValueError):
        stored = None
    if current == stored:
        return None
    if not j.rows("SELECT 1 FROM active_history LIMIT 1"):
        return ("В активном журнале нет поисков магазина. Проверьте источник снимка при выкладке "
                "и KZ_DATA_DIR службы. Для сравнения нужен снимок с историей и завершённым replay.")
    if not isinstance(stored, dict):
        return STALE_REPLAY + " В журнале нет читаемой записи о сборке этого прогона."
    fields = {"mode": "источник истории", "history": "сборка истории",
              "catalog": "содержимое каталога", "method": "код метода сравнения"}
    changed = [name for key, name in fields.items() if stored.get(key) != current.get(key)]
    return STALE_REPLAY + (" Расхождение — " + ", ".join(changed) + "." if changed else "")
