-- Step 2b: an UNLOGGED staging table (no write-ahead log, so bulk COPY is fast; contents are lost on a crash, which is
-- fine for data that can be reloaded). run.py COPYs each monthly file into it and times each one.
DROP SCHEMA IF EXISTS stage CASCADE;
CREATE SCHEMA stage;
CREATE UNLOGGED TABLE stage.ticket_raw (summons_number text, registration_state text, plate_type text, issue_date text,
  violation_code text, vehicle_body_type text, vehicle_make text, issuing_agency text, violation_precinct text,
  violation_time text, violation_county text, street_name text, vehicle_year text);
CREATE TABLE stage.violation_code (code text, definition text, fine_manhattan_below_96 text, fine_elsewhere text);
\copy stage.violation_code FROM 'data/raw/violation_codes.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO nyc.violation_code (code, definition, fine_manhattan_below_96, fine_elsewhere)
SELECT code::smallint, definition, fine_manhattan_below_96::numeric, fine_elsewhere::numeric FROM stage.violation_code;
