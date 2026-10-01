-- Step 2c: from staging text to typed, partitioned rows. Bad values are counted in nyc.load_issue first.
INSERT INTO nyc.load_issue
SELECT 'issue_date', NULL, count(*), 'outside fiscal year 2026: moved to ticket_quarantine with a reason' FROM stage.ticket_raw
 WHERE issue_date::date NOT BETWEEN DATE '2025-07-01' AND DATE '2026-06-30'
UNION ALL
SELECT 'violation_code', violation_code, count(*), 'not in the DOF code table: set to NULL' FROM stage.ticket_raw
 WHERE violation_code NOT IN (SELECT code::text FROM nyc.violation_code) GROUP BY violation_code
UNION ALL
SELECT 'violation_county', coalesce(violation_county, '(blank)'), count(*), 'unknown borough: set to NULL' FROM stage.ticket_raw
 WHERE violation_county IS NULL OR violation_county NOT IN (SELECT alias FROM nyc.borough_alias) GROUP BY violation_county
UNION ALL
SELECT 'violation_time', NULL, count(*), 'not hhmm + A/P: set to NULL' FROM stage.ticket_raw
 WHERE nyc.parse_violation_time(violation_time) IS NULL
UNION ALL
SELECT 'vehicle_year', NULL, count(*), 'outside 1900-2027 (mostly 0): set to NULL' FROM stage.ticket_raw
 WHERE vehicle_year IS NOT NULL AND vehicle_year::int NOT BETWEEN 1900 AND 2027
UNION ALL
SELECT 'violation_precinct', NULL, count(*), 'outside 1-123 (mostly 0, camera tickets): set to NULL' FROM stage.ticket_raw
 WHERE violation_precinct IS NOT NULL AND violation_precinct::int NOT BETWEEN 1 AND 123;

-- Most out-of-year tickets are June 2025: the last month of the previous fiscal year, arriving in this file late.
INSERT INTO nyc.ticket_quarantine
SELECT summons_number::bigint, issue_date, violation_code,
       CASE WHEN issue_date::date BETWEEN DATE '2025-06-01' AND DATE '2025-06-30' THEN 'June 2025: previous fiscal year, arrived late'
            WHEN issue_date::date < DATE '2025-06-01' THEN 'before June 2025'
            WHEN issue_date::date < DATE '2026-10-01' THEN 'after the fiscal year ended'
            ELSE 'in the future: likely a typing error' END
  FROM stage.ticket_raw
 WHERE issue_date::date NOT BETWEEN DATE '2025-07-01' AND DATE '2026-06-30';

INSERT INTO nyc.ticket
SELECT r.summons_number::bigint, r.issue_date::date,
       CASE WHEN r.violation_code IN (SELECT code::text FROM nyc.violation_code) THEN r.violation_code::smallint END,
       nyc.parse_violation_time(r.violation_time), b.borough,
       CASE WHEN r.violation_precinct::int BETWEEN 1 AND 123 THEN r.violation_precinct::smallint END,
       r.issuing_agency, left(r.registration_state, 2), left(r.plate_type, 3), r.vehicle_body_type, r.vehicle_make,
       CASE WHEN r.vehicle_year::int BETWEEN 1900 AND 2027 THEN r.vehicle_year::smallint END, r.street_name
  FROM stage.ticket_raw r LEFT JOIN nyc.borough_alias b ON b.alias = r.violation_county
 WHERE r.issue_date::date BETWEEN DATE '2025-07-01' AND DATE '2026-06-30';

-- A code is a camera code if the camera agency (V) issues at least 99% of it. Bus-lane tickets (code 5) are almost all
-- camera-issued, with a handful written by police, so "only V" would be too strict.
UPDATE nyc.violation_code c SET camera = true
  FROM (SELECT violation_code, avg((issuing_agency = 'V')::int) AS share_v FROM nyc.ticket GROUP BY 1) x
 WHERE x.violation_code = c.code AND x.share_v >= 0.99;
VACUUM ANALYZE nyc.ticket;
