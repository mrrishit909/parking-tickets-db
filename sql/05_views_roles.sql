-- Step 4: a materialized daily summary for dashboards, a readable view, and read-only access for analysts.
DROP MATERIALIZED VIEW IF EXISTS nyc.mv_daily;
CREATE MATERIALIZED VIEW nyc.mv_daily AS
SELECT t.issue_date, coalesce(t.borough, 'Unknown') AS borough, t.violation_code, coalesce(c.camera, false) AS camera,
       count(*) AS tickets,
       -- face value as issued (not collected, no penalties). The data doesn't say whether a Manhattan ticket was south of
       -- 96th Street, where some fines are higher, so give a range: low = every ticket at the "elsewhere" fine,
       -- high = every Manhattan ticket at the below-96th fine.
       sum(c.fine_elsewhere) AS fines_low,
       sum(CASE WHEN t.borough = 'Manhattan' THEN c.fine_manhattan_below_96 ELSE c.fine_elsewhere END) AS fines_high
  FROM nyc.ticket t LEFT JOIN nyc.violation_code c ON c.code = t.violation_code
 GROUP BY 1, 2, 3, 4;
CREATE UNIQUE INDEX ON nyc.mv_daily (issue_date, borough, violation_code);     -- needed for REFRESH ... CONCURRENTLY

CREATE OR REPLACE VIEW nyc.v_ticket AS
SELECT t.summons_number, t.issue_date, t.issued_at, t.borough, t.violation_precinct, t.violation_code, c.definition,
       c.camera, t.registration_state, t.plate_type, t.vehicle_make, t.vehicle_year
  FROM nyc.ticket t LEFT JOIN nyc.violation_code c ON c.code = t.violation_code;

DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finance_analyst') THEN CREATE ROLE finance_analyst NOLOGIN; END IF;
END $$;
REVOKE ALL ON SCHEMA nyc, stage FROM PUBLIC;
GRANT USAGE ON SCHEMA nyc TO finance_analyst;
-- Not the raw ticket table: a view runs with its owner's rights, so analysts can read v_ticket without reading nyc.ticket.
GRANT SELECT ON nyc.mv_daily, nyc.v_ticket, nyc.violation_code TO finance_analyst;
