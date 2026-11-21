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
