-- Step 5: what a year of tickets says (run.py writes each block to results/<name>.csv).

-- name: by_month
SELECT date_trunc('month', issue_date)::date AS month, sum(tickets) AS tickets,
       sum(tickets) FILTER (WHERE camera) AS camera_tickets
  FROM nyc.mv_daily GROUP BY 1 ORDER BY 1;

-- name: top_violations
SELECT d.violation_code, c.definition, c.camera, sum(d.tickets) AS tickets,
       round(100.0 * sum(d.tickets) / (SELECT sum(tickets) FROM nyc.mv_daily), 1) AS pct,
       c.fine_elsewhere, c.fine_manhattan_below_96
  FROM nyc.mv_daily d JOIN nyc.violation_code c ON c.code = d.violation_code
 GROUP BY 1, 2, 3, 6, 7 ORDER BY 4 DESC LIMIT 12;

-- name: by_borough
SELECT borough, sum(tickets) AS tickets, round(100.0 * sum(tickets) FILTER (WHERE camera) / sum(tickets), 1) AS camera_pct,
       round(sum(fines_low) / 1e6, 1) AS fines_low_musd, round(sum(fines_high) / 1e6, 1) AS fines_high_musd
  FROM nyc.mv_daily GROUP BY 1 ORDER BY 2 DESC;

-- name: by_hour
SELECT extract(hour FROM t.issued_at)::int AS hour, count(*) FILTER (WHERE c.camera) AS camera,
       count(*) FILTER (WHERE NOT c.camera) AS officer
  FROM nyc.ticket t JOIN nyc.violation_code c ON c.code = t.violation_code
 WHERE t.issued_at IS NOT NULL GROUP BY 1 ORDER BY 1;

-- name: by_weekday
SELECT extract(isodow FROM issue_date)::int AS weekday, sum(tickets) FILTER (WHERE camera) AS camera,
       sum(tickets) FILTER (WHERE NOT camera) AS officer
  FROM nyc.mv_daily GROUP BY 1 ORDER BY 1;

-- name: plate_states
SELECT registration_state, count(*) AS tickets, round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
  FROM nyc.ticket GROUP BY 1 ORDER BY 2 DESC LIMIT 10;

-- name: quarantine_reasons
SELECT reason, count(*) AS tickets FROM nyc.ticket_quarantine GROUP BY 1 ORDER BY 2 DESC;

-- name: quarantine_years
SELECT left(issue_date_raw, 4) AS year_written, count(*) AS tickets FROM nyc.ticket_quarantine GROUP BY 1 ORDER BY 1;

-- name: totals
SELECT sum(tickets) AS tickets, sum(tickets) FILTER (WHERE camera) AS camera_tickets,
       round(sum(fines_low) / 1e6, 1) AS fines_low_musd, round(sum(fines_high) / 1e6, 1) AS fines_high_musd
  FROM nyc.mv_daily;
