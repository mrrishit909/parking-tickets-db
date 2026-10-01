"""The project's check: run after ./run.sh. Fails loudly if rows go missing, a partition holds the wrong month, or a
benchmark's claim stops holding.

    ./venv/bin/python check.py

1. every downloaded row is either loaded or quarantined; an independent pandas pass over the raw files agrees
2. every partition holds only its own month; summons numbers are unique across the whole year (the primary key alone
   can't promise that, because it has to include the partition column)
3. the time parser handles the edge cases; fines in the summary equal fines recomputed from the base table
4. the plans really prune, use BRIN, run in parallel; DETACH beats DELETE; the analyst can't read the raw table
"""
import json
from pathlib import Path

import pandas as pd

import run

HERE = Path(__file__).parent
R = HERE / "results"


def q(sql):
    return run.psql(sql, tuples=True).strip()


def denied(sql):
    try:
        run.psql(f"SET ROLE finance_analyst; {sql};")
    except RuntimeError as e:
        return "permission denied" in str(e)
    return False


def main():
    load = json.loads((R / "load.json").read_text())
    c = load["counts"]
    assert c["staged"] == sum(f["rows"] for f in load["files"]) == c["loaded"] + c["quarantined"]

    raw = pd.concat([pd.read_csv(f, usecols=["issue_date", "violation_code"], dtype=str)
                     for f in sorted((HERE / "data" / "raw").glob("tickets_*.csv"))])
    day = raw["issue_date"].str[:10]
    outside = ~day.between("2025-07-01", "2026-06-30")
    assert outside.sum() == c["quarantined"], (outside.sum(), c["quarantined"])
    codes = pd.read_csv(HERE / "data" / "raw" / "violation_codes.csv", dtype=str)["code"]
    unknown = (~raw["violation_code"].isin(codes) & raw["violation_code"].notna()).sum()
    issues = pd.read_csv(R / "load_issues.csv", dtype={"value": str})
    assert issues.loc[issues["column"] == "violation_code", "rows"].sum() == unknown

    parts = json.loads((R / "partitions.json").read_text())
    for p in parts:
        lo, hi = q(f"SELECT min(issue_date), max(issue_date) FROM nyc.{p['partition']}").split("|")
        assert lo[:7] == hi[:7] == p["partition"][-7:].replace("_", "-"), p
    assert sum(p["rows"] for p in parts) == c["loaded"]
    assert q("SELECT count(*) - count(DISTINCT summons_number) FROM nyc.ticket") == "0"

    t = q("SELECT nyc.parse_violation_time('0655P'), nyc.parse_violation_time('1205A'), nyc.parse_violation_time('1200P'),"
          " nyc.parse_violation_time('1260P') IS NULL, nyc.parse_violation_time('0550') IS NULL")
    assert t == "18:55:00|00:05:00|12:00:00|t|t", t
    base = q("SELECT sum(c.fine_elsewhere) FROM nyc.ticket t JOIN nyc.violation_code c ON c.code = t.violation_code")
    assert float(base) == float(q("SELECT sum(fines_low) FROM nyc.mv_daily"))

    b = json.loads((R / "benchmarks.json").read_text())
    assert b["pruning"]["partitioned"]["relations_scanned"] == ["ticket_2026_03"]
    assert b["pruning"]["unpartitioned_no_index"]["relations_scanned"] == ["ticket_flat"]
    assert b["brin_vs_btree"]["brin_mb"] * 100 < b["brin_vs_btree"]["btree_mb"]
    assert "Bitmap Index Scan" in b["brin_vs_btree"]["brin"]["scan_types"]
    assert b["retention_one_month"]["detach_partition_ms"] * 100 < b["retention_one_month"]["delete_ms"]
    assert b["parallel"]["0_workers"]["workers"] == 0 and b["parallel"]["4_workers"]["workers"] >= 2
    assert b["insert_vs_copy_200k_rows"]["copy_times_faster"] > 5

    assert q("SET ROLE finance_analyst; SELECT count(*) > 0 FROM nyc.mv_daily") == "t"
    assert q("SET ROLE finance_analyst; SELECT count(*) > 0 FROM nyc.v_ticket") == "t"
    assert denied("SELECT count(*) FROM nyc.ticket") and denied("SELECT count(*) FROM stage.ticket_raw")
    print(f"OK: {c['staged']:,} rows = {c['loaded']:,} loaded + {c['quarantined']:,} quarantined (pandas agrees); 12 partitions hold "
          f"only their month; summons numbers unique; time parser edge cases pass; fines reconcile; pruning, BRIN, parallelism, "
          f"DETACH vs DELETE and COPY vs INSERT claims hold; analyst reads the summary and view but not the raw table")


if __name__ == "__main__":
    main()
