from contextlib import closing
import sqlite3

from kuznitsa.analytics.cost import report
from kuznitsa.analytics.store import Journal
from kuznitsa.api.admin import source_counts


def test_live_report_invalidation(tmp_path):
    path = tmp_path / "live.sqlite"
    journal = Journal(path)
    try:
        assert source_counts(journal) == []
        assert "ещё не создана" in report(journal)["note"]
        # DDL через то же соединение не увеличивает total_changes.
        journal.db.execute("CREATE TABLE llm_calls(search_id TEXT, sent INT, cached INT, cost_usd REAL)")
        with closing(sqlite3.connect(path)) as writer, writer:
            writer.execute("INSERT INTO searches(search_id,source,engine,mode,llm_calls) VALUES ('first','ui','kuznitsa','smart',1)")
        assert source_counts(journal) == [dict(source="ui", searches=1, service=0)]
        assert report(journal)["sent"] == 1
        with journal.transaction() as db:
            db.execute("INSERT INTO llm_calls VALUES ('first', 1, 0, .001)")
        assert report(journal)["rub_per_100000"] > 0
        with closing(sqlite3.connect(path)) as writer, writer:
            writer.execute("DELETE FROM searches")
        assert source_counts(journal) == [] and report(journal)["sent"] == 0
    finally:
        journal.db.close()
