"""Load a year of NYC parking tickets into a partitioned PostgreSQL table and measure the operations a DBA cares about.

    ./run.sh     # starts the project's private PostgreSQL (socket only), then runs this file

Benchmarks (results/benchmarks.json):
  bulk load    COPY vs single-row INSERTs for the same 200,000 rows
  pruning      one day's tickets: partitioned table (one partition read) vs one big unpartitioned table
  BRIN/B-tree  index size, build time and a one-week query on the unpartitioned table
  retention    removing a month: DELETE from the big table vs DETACH PARTITION
  parallelism  a full-year aggregate with 0, 2 and 4 parallel workers
  summary      a dashboard query on the base table vs the materialized daily summary
"""
import csv
import json
import os
import re
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).parent
BIN = Path(os.environ.get("PG", Path.home() / "micromamba" / "envs" / "analyst" / "bin"))
CONN = ["-h", str(HERE / "data"), "-p", "5434", "-U", "postgres"]
OUT = HERE / "results"


def psql(sql=None, file=None, db="parking", tuples=False):
    args = [str(BIN / "psql"), *CONN, "-d", db, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else [])
    args += ["-f", file] if file else ["-f", "-"]
    r = subprocess.run(args, input=None if file else sql, cwd=HERE, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return r.stdout


def ms(sql):
    """Server-side time of the statements in `sql`, summed from psql's \\timing output."""
    out = psql("\\timing on\n" + sql)
    return sum(float(x) for x in re.findall(r"Time: ([\d.]+) ms", out))


def explain(sql, runs=3, settings=""):
    times, plan = [], None
    for _ in range(runs):
        j = json.loads(psql(f"{settings}\nEXPLAIN (ANALYZE, FORMAT JSON) {sql};", tuples=True))[0]
        times.append(j["Execution Time"])
        plan = j["Plan"]
    nodes = list(walk(plan))
    scanned = sorted({n.get("Relation Name") for n in nodes if n.get("Relation Name")})
    workers = max((n.get("Workers Launched", 0) for n in nodes), default=0)
    return {"ms": sorted(times)[runs // 2], "relations_scanned": scanned, "workers": workers,
            "scan_types": sorted({n["Node Type"] for n in nodes if "Scan" in n["Node Type"]})}


def walk(n):
    yield n
    for c in n.get("Plans", []):
        yield from walk(c)


def blocks(path):
    text = (HERE / path).read_text()
    return [(m.group(1).strip(), m.group(2).strip().rstrip(";")) for m in re.finditer(r"-- name: ([^\n]+)\n(.*?)(?=\n-- name:|\Z)", text, re.S)]


def size(rel):
    return int(psql(f"SELECT pg_total_relation_size('{rel}');", tuples=True))


def main():
    OUT.mkdir(exist_ok=True)
    psql("DROP DATABASE IF EXISTS parking;", db="postgres")
    psql("CREATE DATABASE parking;", db="postgres")
    psql(file="sql/01_schema.sql")
    psql(file="sql/02_stage.sql")
    bench, loads = {}, []
    files = sorted((HERE / "data" / "raw").glob("tickets_*.csv"))
    for f in files:
        rows = sum(1 for _ in f.open()) - 1
        t = ms(f"\\copy stage.ticket_raw FROM '{f.relative_to(HERE)}' WITH (FORMAT csv, HEADER true)")
        loads.append({"file": f.name, "rows": rows, "copy_seconds": round(t / 1000, 1)})
    total_rows = sum(x["rows"] for x in loads)
    bench["copy"] = {"rows": total_rows, "seconds": round(sum(x["copy_seconds"] for x in loads), 1),
                     "rows_per_second": round(total_rows / sum(x["copy_seconds"] for x in loads))}

    sample = list(csv.reader((HERE / "data" / "raw" / "tickets_2025-08.csv").open()))[1:200001]
    with (HERE / "data" / "sample.csv").open("w", newline="") as fh:
        csv.writer(fh).writerows(sample)
    psql("CREATE TABLE stage.insert_test (LIKE stage.ticket_raw); CREATE TABLE stage.copy_test (LIKE stage.ticket_raw);")
    q = lambda v: "'" + v.replace("'", "''") + "'"
    inserts = "BEGIN;\n" + "".join(f"INSERT INTO stage.insert_test VALUES ({', '.join(q(v) for v in r)});\n" for r in sample) + "COMMIT;"
    t0 = time.time()
    psql(inserts)
    t_insert = time.time() - t0
    t0 = time.time()
    psql("\\copy stage.copy_test FROM 'data/sample.csv' WITH (FORMAT csv)")
    t_copy = time.time() - t0
    bench["insert_vs_copy_200k_rows"] = {"insert_seconds": round(t_insert, 2), "copy_seconds": round(t_copy, 2),
                                        "copy_times_faster": round(t_insert / t_copy, 1)}

    t = ms(open(HERE / "sql" / "03_transform.sql").read())
    bench["transform_seconds"] = round(t / 1000, 1)
    t = ms(open(HERE / "sql" / "04_indexes.sql").read())
    bench["index_build_seconds"] = round(t / 1000, 1)

    day = "SELECT violation_code, count(*) FROM nyc.ticket WHERE issue_date = DATE '2026-03-16' GROUP BY 1"
    psql("CREATE SCHEMA bench; CREATE TABLE bench.ticket_flat AS SELECT * FROM nyc.ticket ORDER BY issue_date; VACUUM ANALYZE bench.ticket_flat;")
    flat_day = day.replace("nyc.ticket", "bench.ticket_flat")
    bench["pruning"] = {"partitioned": explain(day), "unpartitioned_no_index": explain(flat_day)}

    week = "SELECT count(*) FROM bench.ticket_flat WHERE issue_date BETWEEN DATE '2026-03-09' AND DATE '2026-03-15'"
    out = {"no_index": explain(week)}
    out["btree_build_ms"] = ms("CREATE INDEX flat_btree ON bench.ticket_flat (issue_date); ANALYZE bench.ticket_flat;")
    out["btree_mb"] = round(size("bench.flat_btree") / 1e6, 1)
    out["btree"] = explain(week)
    psql("DROP INDEX bench.flat_btree;")
    out["brin_build_ms"] = ms("CREATE INDEX flat_brin ON bench.ticket_flat USING brin (issue_date); ANALYZE bench.ticket_flat;")
    out["brin_mb"] = round(size("bench.flat_brin") / 1e6, 3)
    out["brin"] = explain(week)
    bench["brin_vs_btree"] = out

    flat_before = size("bench.ticket_flat")
    del_ms = ms("DELETE FROM bench.ticket_flat WHERE issue_date < DATE '2025-08-01';")
    dead = int(psql("SELECT n_dead_tup FROM pg_stat_user_tables WHERE relid = 'bench.ticket_flat'::regclass;", tuples=True) or 0)
    vac_ms = ms("VACUUM bench.ticket_flat;")
    detach_ms = ms("ALTER TABLE nyc.ticket DETACH PARTITION nyc.ticket_2025_07;")
    attach_ms = ms("ALTER TABLE nyc.ticket ATTACH PARTITION nyc.ticket_2025_07 FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');")
    bench["retention_one_month"] = {"delete_ms": round(del_ms), "dead_rows_left_by_delete": dead, "vacuum_ms": round(vac_ms),
                                    "table_mb_before": round(flat_before / 1e6), "table_mb_after_delete_and_vacuum": round(size("bench.ticket_flat") / 1e6),
                                    "detach_partition_ms": round(detach_ms, 1), "reattach_partition_ms": round(attach_ms, 1)}

    year2 = "SELECT borough, count(*) FROM nyc.ticket GROUP BY 1"
    bench["parallel"] = {f"{w}_workers": explain(year2, settings=f"SET max_parallel_workers_per_gather = {w};") for w in (0, 2, 4)}

    psql(file="sql/05_views_roles.sql")
    dash_base = ("SELECT date_trunc('month', t.issue_date) AS m, t.borough, count(*), sum(c.fine_elsewhere) FROM nyc.ticket t "
                 "LEFT JOIN nyc.violation_code c ON c.code = t.violation_code GROUP BY 1, 2")
    dash_mv = "SELECT date_trunc('month', issue_date) AS m, borough, sum(tickets), sum(fines_low) FROM nyc.mv_daily GROUP BY 1, 2"
    bench["dashboard"] = {"base_table": explain(dash_base, runs=1), "materialized_view": explain(dash_mv),
                          "refresh_concurrently_ms": round(ms("REFRESH MATERIALIZED VIEW CONCURRENTLY nyc.mv_daily;"))}

    for name, sql in blocks("sql/06_insights.sql"):
        psql(f"\\copy ({' '.join(sql.split())}) TO 'results/{name}.csv' WITH (FORMAT csv, HEADER true)")

    sizes = psql("SELECT c.relname, pg_total_relation_size(c.oid), (SELECT count(*) FROM nyc.ticket) FROM pg_inherits i "
                 "JOIN pg_class c ON c.oid = i.inhrelid WHERE i.inhparent = 'nyc.ticket'::regclass ORDER BY 1;", tuples=True)
    parts = []
    for line in sizes.strip().splitlines():
        name, b, _ = line.split("|")
        n = int(psql(f"SELECT count(*) FROM nyc.{name};", tuples=True))
        parts.append({"partition": name, "rows": n, "mb": round(int(b) / 1e6)})
    issues = psql("SELECT column_name, coalesce(bad_value, ''), rows, action FROM nyc.load_issue ORDER BY rows DESC;", tuples=True)
    counts = json.loads(psql("SELECT json_build_object('staged', (SELECT count(*) FROM stage.ticket_raw), 'loaded', (SELECT count(*) FROM nyc.ticket),"
                             " 'quarantined', (SELECT count(*) FROM nyc.ticket_quarantine), 'database_mb', pg_database_size('parking') / 1000000);", tuples=True))
    (OUT / "benchmarks.json").write_text(json.dumps(bench, indent=2) + "\n")
    (OUT / "partitions.json").write_text(json.dumps(parts, indent=2) + "\n")
    (OUT / "load.json").write_text(json.dumps({"files": loads, "counts": counts}, indent=2) + "\n")
    (OUT / "load_issues.csv").write_text("column,value,rows,action\n" + "".join(
        ",".join(f'"{x}"' if "," in x else x for x in line.split("|")) + "\n" for line in issues.strip().splitlines()))
    print(json.dumps({"counts": counts, **bench}, indent=1))


if __name__ == "__main__":
    main()
