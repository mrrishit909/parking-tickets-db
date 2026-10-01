"""Step 1: NYC parking tickets issued in fiscal year 2026 (July 2025 - June 2026), plus the violation-code fine table.

    ./venv/bin/python download.py

Sources: NYC Department of Finance via NYC Open Data, "Parking Violations Issued - Fiscal Year 2026" (9mwx-gamw) and
"DOF Parking Violation Codes" (ncbg-6agr). One file per issue month, three months at a time, plus one file for tickets
whose issue date falls outside the fiscal year. Plate numbers are never downloaded. Saved to
data/raw/ (not committed).
"""
import ssl
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAW = Path(__file__).parent / "data" / "raw"
API = "https://data.cityofnewyork.us/resource/{}.csv?"
COLS = ("summons_number,registration_state,plate_type,issue_date,violation_code,vehicle_body_type,vehicle_make,"
        "issuing_agency,violation_precinct,violation_time,violation_county,street_name,vehicle_year")
CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
MONTHS = [f"{y}-{m:02d}-01" for y, m in [(2025, m) for m in range(7, 13)] + [(2026, m) for m in range(1, 8)]]


def fetch(name, where):
    out = RAW / f"tickets_{name}.csv"
    if out.exists():
        return name, "already there"
    q = urllib.parse.urlencode({"$select": COLS, "$where": where, "$limit": 5000000})
    tmp = out.with_suffix(".part")
    with urllib.request.urlopen(API.format("9mwx-gamw") + q, context=CTX, timeout=3600) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(out)
    return name, f"{out.stat().st_size / 1e6:.0f} MB"


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "violation_codes.csv").write_bytes(urllib.request.urlopen(API.format("ncbg-6agr") + "$limit=1000", context=CTX).read())
    jobs = [(a[:7], f"issue_date >= '{a}' AND issue_date < '{b}'") for a, b in zip(MONTHS, MONTHS[1:])]
    jobs.append(("outside_fy", "issue_date < '2025-07-01' OR issue_date >= '2026-07-01'"))
    with ThreadPoolExecutor(3) as pool:
        for name, msg in pool.map(lambda j: fetch(*j), jobs):
            print(name, msg, flush=True)
