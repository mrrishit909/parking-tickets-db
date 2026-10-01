-- Step 3: indexes on the partitioned table. An index created on the parent is created on every partition.
CREATE INDEX ticket_code_idx     ON nyc.ticket (violation_code);
CREATE INDEX ticket_precinct_idx ON nyc.ticket (violation_precinct) WHERE violation_precinct IS NOT NULL;
CREATE INDEX ticket_borough_idx  ON nyc.ticket (borough, issue_date);
ANALYZE nyc.ticket;
