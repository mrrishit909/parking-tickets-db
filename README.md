# 15 million NYC parking tickets in a partitioned PostgreSQL database

New York City issued about 15.7 million parking and camera tickets in fiscal year 2026 (July 2025 – June 2026). This
project loads all of them into PostgreSQL 18 and measures, rather than asserts, the database-administration choices
that matter at that scale:
- bulk loading;
- monthly partitions;
- BRIN vs B-tree indexes;
- retention by detaching partitions;
- parallel queries;
- a materialized summary for dashboards;
- a read-only analyst role.

Build log: https://mrrishit909.github.io/projects/parking-tickets-db/

## Data

NYC Department of Finance via NYC Open Data:
- *Parking Violations Issued – Fiscal Year 2026* (`9mwx-gamw`, 15,689,748 rows);
- *DOF Parking Violation Codes* (`ncbg-6agr`, fines).

**Plate numbers are never downloaded**; only plate state and type are kept. Raw files (~1.9 GB) aren't committed.

## Steps

| Step | File | What it does |
|---|---|---|
| 1 | `download.py` | 12 monthly files + out-of-year tickets, 3 at a time; fine table |
| 2 | `sql/01_schema.sql`, `02_stage.sql`, `03_transform.sql` | partitioned schema; UNLOGGED staging; typed transform with logged issues and a quarantine |
| 3 | `sql/04_indexes.sql`, `05_views_roles.sql`, `06_insights.sql` | indexes; materialized daily summary; analyst role; findings |
| 4 | `run.py`, `run.sh` | runs everything on a private local PostgreSQL (socket only) and benchmarks it |
| 5 | `check.py`, `charts.py` | independent checks; charts |

## Design

- **`nyc.ticket` is partitioned by month** (12 partitions). A partitioned table's primary key must include the
  partition column, so the key is `(summons_number, issue_date)`. That can't guarantee a summons number is unique
  across months, so `check.py` verifies it separately; it is.
- **Lookups:** violation codes with both fines, and a `borough_alias` table that maps 13 spellings (NY/MN, K/BK/Kings,
  Q/QN/Qns, BX/Bronx, R/ST/Rich) to 5 boroughs.
- **`parse_violation_time()`** turns "0655P" into 18:55. 7,500 impossible times (such as "7552P") become NULL.
- **Camera tickets are identified from the data, not assumed.** One agency code ("V") issues at least 99% of codes 5
  (bus lane), 7 (red light) and 36 (school-zone speed), so those are marked as camera codes.

## Loading, and what didn't fit

| | Rows |
|---|---:|
| Downloaded | 15,689,748 |
| Loaded into partitions | 15,278,865 |
| Quarantined (issue date outside the fiscal year) | 410,883 |

`COPY` into an UNLOGGED staging table loads all 15.7 million rows in 14.4 seconds (about 1.1 million rows a second).
On the same 200,000 rows, COPY took 0.18 s against 3.8 s for row-by-row INSERTs, **21× faster**.

**The quarantine is mostly late data, not bad data.** 403,351 of the 410,883 out-of-year tickets are dated June 2025,
the last month of the *previous* fiscal year, which reached this year's file late. Only 1,175 have impossible future
dates (up to 2068) and 6,020 earlier ones. The data dictionary notes that issue dates may be transcribed from
handwritten tickets. Other logged issues:
- violation precinct 0 for 6.7 million tickets, mostly camera tickets, which have no precinct;
- vehicle year 0 for 2.9 million;
- blank borough for 398,000;
- unknown violation codes 0, 94 and 95 for 1,423.

## Benchmarks (`results/benchmarks.json`; medians of 3 runs, `EXPLAIN ANALYZE`)

| Question | Slow way | Fast way |
|---|---:|---:|
| Load 200,000 rows | INSERTs 3.8 s | **COPY 0.18 s** |
| One day's tickets | one big table 184 ms | **partitioned 5 ms** (reads only March) |
| One week, big table | no index 186 ms | B-tree 8 ms, BRIN 39 ms |
| Index size on issue date | B-tree 106 MB | **BRIN 0.08 MB** (1,294× smaller) |
| Remove a month (1.46M rows) | DELETE 872 ms | **DETACH PARTITION 4 ms** |
| Full-year count by borough | 0 workers 1,881 ms | **4 parallel workers 432 ms** |
| Monthly fines by borough | base table 2,293 ms | **materialized view 29 ms** |

- **BRIN** stores one summary per block range. It's tiny and works well because tickets arrive in date order; a B-tree
  is faster per query but 1,300× bigger.
- **DELETE leaves debris.** It left 1,464,814 dead rows, and the table stayed 1,656 MB even after VACUUM; the space is
  reused, not returned. Detaching a partition is a metadata change; re-attaching took 158 ms, because PostgreSQL scans
  to validate the bounds.
- **The materialized view** refreshes concurrently (2.8 s) without blocking readers. That needs a unique index on it.

## Findings

- **15.28 million tickets**, $1.20–1.23 billion in fines at face value: issued, not collected, and before penalties. The
  range exists because the data doesn't say whether a Manhattan ticket was south of 96th Street, where some fines are higher.
- **35% were camera tickets** (5.39 million). The single most common ticket is the **school-zone speed camera**
  (3.84 million, 25%), ahead of street cleaning (1.77 million) and unpaid meters (1.23 million).
- **Cameras ticket around the clock and at weekends.** Camera tickets peak on Saturdays and Sundays, while officers write
  fewest on Sundays and most between 8 and 10 a.m.
- **Boroughs differ in who writes the ticket:**
  - Manhattan has the most tickets (4.53 million), and only 12% are from cameras;
  - Staten Island's tickets are 78% camera.
- **Out-of-state plates:** 70% of tickets went to New York plates, 11% to New Jersey and 4% to Pennsylvania.

## Run it

```
python3 -m venv venv && ./venv/bin/pip install pandas matplotlib openpyxl
./venv/bin/python download.py
./run.sh                     # PostgreSQL 18 in ~/micromamba/envs/analyst/bin, or set PG=/path/to/bin
./venv/bin/python check.py && ./venv/bin/python charts.py
```

## Not done

- Payments and dismissals are in a different dataset (*Open Parking and Camera Violations*), so this shows tickets
  issued, not money collected.
- No streaming/daily load; a production design would add each new month as a partition and detach the oldest.
- Partitions are by month only; a sub-partition by borough wasn't needed at this size.
