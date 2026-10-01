-- Step 2a: schema for a year of NYC parking tickets (fiscal year 2026: 1 July 2025 - 30 June 2026).
DROP SCHEMA IF EXISTS nyc CASCADE;
CREATE SCHEMA nyc;

CREATE TABLE nyc.violation_code (
  code                     smallint PRIMARY KEY,
  definition               text NOT NULL,
  fine_manhattan_below_96  numeric(7, 2) NOT NULL CHECK (fine_manhattan_below_96 >= 0),
  fine_elsewhere           numeric(7, 2) NOT NULL CHECK (fine_elsewhere >= 0),
  camera                   boolean NOT NULL DEFAULT false     -- set from which agency issues the code (see 03_transform.sql)
);

-- The same borough arrives under many spellings; one lookup maps them all.
CREATE TABLE nyc.borough_alias (alias text PRIMARY KEY, borough text NOT NULL);
INSERT INTO nyc.borough_alias VALUES ('NY','Manhattan'),('MN','Manhattan'),('BK','Brooklyn'),('K','Brooklyn'),('Kings','Brooklyn'),
  ('QN','Queens'),('Q','Queens'),('Qns','Queens'),('BX','Bronx'),('Bronx','Bronx'),('ST','Staten Island'),('R','Staten Island'),
  ('Rich','Staten Island');

-- "0655P" -> 18:55. Anything that is not hhmm + A/P with a real hour and minute becomes NULL.
CREATE FUNCTION nyc.parse_violation_time(t text) RETURNS time LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN t ~ '^(0[0-9]|1[0-2])[0-5][0-9][AP]$' THEN
    make_time((substr(t, 1, 2)::int % 12) + CASE WHEN right(t, 1) = 'P' THEN 12 ELSE 0 END, substr(t, 3, 2)::int, 0) END
$$;

-- One partition per month. The primary key must include the partition column, so it is (summons_number, issue_date).
CREATE TABLE nyc.ticket (
  summons_number     bigint   NOT NULL,
  issue_date         date     NOT NULL,
  violation_code     smallint REFERENCES nyc.violation_code,
  issued_at          time,
  borough            text,
  violation_precinct smallint CHECK (violation_precinct BETWEEN 1 AND 123),
  issuing_agency     text,
  registration_state char(2),
  plate_type         char(3),
  vehicle_body_type  text,
  vehicle_make       text,
  vehicle_year       smallint CHECK (vehicle_year BETWEEN 1900 AND 2027),
  street_name        text,
  PRIMARY KEY (summons_number, issue_date)
) PARTITION BY RANGE (issue_date);

DO $$
DECLARE m date;
BEGIN
  FOR m IN SELECT generate_series(DATE '2025-07-01', DATE '2026-06-01', interval '1 month')::date LOOP
    EXECUTE format('CREATE TABLE nyc.ticket_%s PARTITION OF nyc.ticket FOR VALUES FROM (%L) TO (%L)',
                   to_char(m, 'YYYY_MM'), m, (m + interval '1 month')::date);
  END LOOP;
END $$;

-- Tickets dated outside the fiscal year (the dictionary says dates may be transcribed from handwritten tickets).
CREATE TABLE nyc.ticket_quarantine (summons_number bigint, issue_date_raw text, violation_code text, reason text NOT NULL);

CREATE TABLE nyc.load_issue (column_name text, bad_value text, rows bigint, action text);
