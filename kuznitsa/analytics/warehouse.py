"""Сжатая витрина массовой загрузки. Вес строки — число одинаковых наблюдений."""
from collections import Counter
from itertools import combinations, groupby
from .store import dump

AXES=("day","engine","segment","category","intent")


def build(j,db,fields):
    from .kpi import FACT_SQL,loss_by_session
    from .failures import NOISE
    import json
    db.execute("DROP TABLE IF EXISTS analytics_detail")
    dataset=db.execute("SELECT value FROM kv WHERE key='settings:history_source'").fetchone()
    selector={"mock":" AND s.search_id GLOB 's_mock_*'", "import":" AND s.search_id IN (SELECT id FROM analytics_import_ids)"}.get(dataset[0] if dataset else None,"")
    sql=FACT_SQL.replace("active_history s","searches s NOT INDEXED").replace("GROUP BY s.search_id",
        "WHERE s.source='history'"+selector+" GROUP BY s.rowid")
    db.execute("CREATE TABLE analytics_detail AS "+sql)
    db.execute("CREATE INDEX IF NOT EXISTS analytics_detail_session ON analytics_detail(session_id,ts)")
    db.execute("CREATE INDEX IF NOT EXISTS analytics_detail_q ON analytics_detail(q)")
    db.execute("DROP TABLE IF EXISTS analytics_loss")
    db.execute("CREATE TEMP TABLE analytics_loss(id TEXT PRIMARY KEY,base REAL,low REAL)")
    if db.execute("SELECT 1 FROM analytics_detail WHERE revenue>0 LIMIT 1").fetchone():
        session_rows=db.execute("SELECT * FROM analytics_detail ORDER BY session_id,ts")
        losses,_=loss_by_session((list(g) for _,g in groupby(session_rows,key=lambda r:r["session_id"])))
        db.executemany("INSERT INTO analytics_loss VALUES (?,?,?)",((k,*v) for k,v in losses.items()))
    db.execute("DROP TABLE IF EXISTS analytics_peers")
    db.execute("CREATE TEMP TABLE analytics_peers(q TEXT PRIMARY KEY,empty INTEGER)")
    db.execute("DROP TABLE IF EXISTS analytics_hits")
    db.execute("CREATE TEMP TABLE analytics_hits(id TEXT PRIMARY KEY,first_hit INTEGER,second_hit INTEGER)")
    for row in db.execute("SELECT q,result FROM replay_results WHERE run_id=(SELECT id FROM active_replay)"):
        peer=json.loads(row["result"])
        db.execute("INSERT INTO analytics_peers VALUES (?,?)",(row["q"],bool(peer["after_zero"])))
        db.executemany("INSERT INTO analytics_hits VALUES (?,?,?)",((i,*v) for i,v in peer["cases"].items()))
    cols={k:"d."+k for k in fields}
    cols.update(day="date(d.ts,'unixepoch','+3 hours')",failed="d.zero OR (NOT d.clicks AND (d.exits OR d.reformulations))",
                noise="coalesce(reason IN ("+",".join("?" for _ in NOISE)+"),0)",
                base="coalesce(l.base,0)",low="coalesce(l.low,0)",assortment="coalesce(reason IN ('not_in_catalog_known','not_in_catalog_unknown','vendor_left'),0)",
                paired="p.q IS NOT NULL",peer_zero="coalesce(p.empty,0)",hit_before="h.first_hit",hit_after="h.second_hit")
    for k in ("orders","revenue","clicks"):
        cols[k+"_known"]="coalesce(o."+k+",1)"
    db.execute("DROP TABLE IF EXISTS analytics_fact")
    db.execute("CREATE TABLE analytics_fact AS SELECT "+",".join(f"{expr} AS {k}" for k,expr in cols.items())+"""
        FROM analytics_detail d LEFT JOIN analytics_observation o ON o.id=d.search_id
        LEFT JOIN analytics_loss l ON l.id=d.search_id LEFT JOIN analytics_peers p ON p.q=d.q
        LEFT JOIN analytics_hits h ON h.id=d.search_id""",tuple(NOISE))
    db.execute("DROP TABLE IF EXISTS analytics_pack")
    packed=[k for k in fields if k not in ("ts","session_id","search_id")]
    selected=" WHERE paired=1" if db.execute("SELECT 1 FROM active_replay").fetchone() else ""
    db.execute("CREATE TABLE analytics_pack AS SELECT "+",".join(packed)+",count(*) w,min(ts) start_ts,max(ts) end_ts FROM analytics_fact"+selected+" GROUP BY "+",".join(packed))
    for col in AXES:
        db.execute(f"CREATE INDEX analytics_pack_{col} ON analytics_pack({col})")
    # Уникальные визиты нельзя суммировать по дням или категориям. Сначала
    # группируем визиты с одинаковыми наборами координат, затем считаем их вклад.
    db.execute("DROP TABLE IF EXISTS analytics_dims")
    db.execute("CREATE TEMP TABLE analytics_dims AS SELECT DISTINCT "+",".join(AXES)+",noise FROM analytics_fact"+selected)
    db.execute("CREATE UNIQUE INDEX analytics_dim_lookup ON analytics_dims("+",".join(AXES)+",noise)")
    dims={r[0]:tuple(r[1:]) for r in db.execute("SELECT rowid,* FROM analytics_dims")}
    join=" AND ".join("d."+k+" IS f."+k for k in (*AXES,"noise"))
    patterns=db.execute("""SELECT signature,count(*) n FROM (SELECT group_concat(DISTINCT d.rowid) signature
        FROM analytics_fact f JOIN analytics_dims d ON """+join+selected+" GROUP BY f.session_id) GROUP BY signature")
    cells=Counter()
    noisy=Counter()
    subsets=[key for n in range(len(AXES)+1) for key in combinations(range(len(AXES)),n)]
    for signature,n in patterns:
        coords=[dims[int(i)] for i in signature.split(",")]
        for subset in subsets:
            keys={tuple((AXES[i],coord[i]) for i in subset) for coord in coords}
            cells.update({key:n for key in keys})
            if any(c[-1] for c in coords):
                keys={tuple((AXES[i],coord[i]) for i in subset) for coord in coords if coord[-1]}
                noisy.update({key:n for key in keys})
    db.execute("DROP TABLE IF EXISTS analytics_cells")
    db.execute("CREATE TABLE analytics_cells(scope TEXT PRIMARY KEY,sessions INTEGER,excluded INTEGER)")
    db.executemany("INSERT INTO analytics_cells VALUES (?,?,?)",((dump(dict(key)),value,noisy[key]) for key,value in cells.items()))
    db.execute("INSERT INTO analytics_reports VALUES ('packed','true')")


def sessions(j,filters):
    key=dump({k:filters[k] for k in AXES if k in filters})
    rows=j.rows("SELECT sessions,excluded FROM analytics_cells WHERE scope=?",(key,))
    return tuple(rows[0].values()) if rows else (0,0)


def aggregate(sql):
    """Преобразует агрегаты витрины в точные взвешенные суммы и средние."""
    import re
    sql=sql.replace("count(distinct session_id)","0").replace("count(*)","sum(1)")
    pattern=r"\b(avg|sum)\("
    pos=0
    parts=[]
    for m in re.finditer(pattern,sql):
        if m.start()<pos:
            continue
        depth=1
        end=m.end()
        while depth:
            depth+=(sql[end]=="(")-(sql[end]==")")
            end+=1
        expr=sql[m.end():end-1]
        weighted=f"sum(w*({expr}))"
        if m[1]=="avg":
            weighted=f"(1.0*{weighted}/nullif(sum(CASE WHEN ({expr}) IS NOT NULL THEN w ELSE 0 END),0))"
        parts.extend([sql[pos:m.start()],weighted])
        pos=end
    return "".join(parts)+sql[pos:]
