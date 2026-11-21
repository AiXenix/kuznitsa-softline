"""Сохранённые отчёты сбрасываются в той же транзакции, что и их источники."""
import json
from .store import dump


def cached(j,key,build):
    found=j.rows("SELECT body FROM analytics_reports WHERE key=?",(key,))
    if found:
        return json.loads(found[0]["body"])
    # Между чтением и публикацией мог завершиться другой импорт.
    rev=j.rows("SELECT revision FROM analytics_revision")[0]["revision"]
    result=build()
    with j.transaction() as db:
        db.execute("""INSERT OR REPLACE INTO analytics_reports SELECT ?,? WHERE
                   (SELECT revision FROM analytics_revision)=?""",(key,dump(result),rev))
    return result


def live_cached(j, key, build):
    """Короткие сводки по всем источникам, включая записи других соединений."""
    with j.lock:
        if j.db.in_transaction:
            return build()
        stamp = (j.db.total_changes, j.db.execute("PRAGMA data_version").fetchone()[0],
                 j.db.execute("PRAGMA schema_version").fetchone()[0])
        if not hasattr(j, "_live_reports"):
            j._live_reports = {}
        entry = j._live_reports.get(key)
        if entry is None or entry[0] != stamp:
            entry = stamp, build()
            j._live_reports[key] = entry
        return entry[1]
