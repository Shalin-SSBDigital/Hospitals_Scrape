"""
PMJAY Public Hospital Scraper (no auth, no CAPTCHA)
====================================================

Data source: https://hospitals.pmjay.gov.in (public Find Hospital)
  - Listing endpoint: /Search/empanelApplicationForm.htm?actionVal=GETHOSPNAMESLIST&...
    (returns hospital id+name list for a state+type filter)
  - Excel export endpoint: /Search/empnlWorkFlow.htm?actionFlag=ViewRegisteredHosptlsNew&...&export=E
    (returns a .xls file with 15+ columns for a state+type filter)

State IDs and their values are read from the public search form's HTML.
Hospital types: Public, PrivateNP, PrivateP
Empanelment types: PMJAY, "PMJAY and CGHS", "PMJAY and CAPF", "Only CGHS", "Only CAPF", CMHIS, KASS
"""

from __future__ import annotations

import csv
import json
import os
import random
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import xlrd
import requests

# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "run.log"
PROGRESS_FILE = BASE_DIR / "hospitals_progress.json"
CSV_FILE = BASE_DIR / "hospitals.csv"
JSON_FILE = BASE_DIR / "hospitals.json"
RAW_DIR = BASE_DIR / "raw_xls"
RAW_DIR.mkdir(exist_ok=True)

BASE_URL = "https://hospitals.pmjay.gov.in/Search"
LISTING_URL = f"{BASE_URL}/empanelApplicationForm.htm"
EXPORT_URL = f"{BASE_URL}/empnlWorkFlow.htm"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# 36 columns, in the exact order of the user's header row
COLUMNS: list[str] = [
    "Sr No",
    "Hospital Name",
    "Hospital ID (UUID)",
    "Accreditation",
    "Address",
    "Emergency Numbers",
    "Ambulance Phone No",
    "Bloodbank Phone No",
    "Emergency Services",
    "Facilities",
    "Foreign Pcare",
    "Helpline",
    "Hospital Care Type",
    "Hospital Category",
    "Hospital Fax",
    "Hospital Primary Email",
    "Hospital Secondary Email",
    "Latitude",
    "Longitude",
    "Location",
    "Miscellaneous Facilities",
    "Mobile Number",
    "Nodal Person Email",
    "Nodal Person Info",
    "Nodal Person Tele",
    "Number of Beds (Eco Weaker Sec)",
    "Doctors Available",
    "Private Wards",
    "Pincode",
    "Website",
    "State",
    "Subdistrict",
    "Town",
    "Village",
    "Timezone",
    "Insurance Companies",
    "Specialities",
    "Sub -Specialty",
]

# States pulled from the public search form HTML
STATES: list[dict[str, str]] = [
    {"value": "35", "label": "ANDAMAN AND NICOBAR ISLANDS"},
    {"value": "28", "label": "ANDHRA PRADESH"},
    {"value": "12", "label": "ARUNACHAL PRADESH"},
    {"value": "18", "label": "ASSAM"},
    {"value": "10", "label": "BIHAR"},
    {"value": "4",  "label": "CHANDIGARH"},
    {"value": "22", "label": "CHHATTISGARH"},
    {"value": "26", "label": "DADRA AND NAGAR HAVELI"},
    {"value": "25", "label": "DAMAN AND DIU"},
    {"value": "30", "label": "GOA"},
    {"value": "24", "label": "GUJARAT"},
    {"value": "6",  "label": "HARYANA"},
    {"value": "2",  "label": "HIMACHAL PRADESH"},
    {"value": "1",  "label": "JAMMU AND KASHMIR"},
    {"value": "20", "label": "JHARKHAND"},
    {"value": "29", "label": "KARNATAKA"},
    {"value": "32", "label": "KERALA"},
    {"value": "37", "label": "LADAKH"},
    {"value": "31", "label": "LAKSHADWEEP"},
    {"value": "23", "label": "MADHYA PRADESH"},
    {"value": "27", "label": "MAHARASHTRA"},
    {"value": "14", "label": "MANIPUR"},
    {"value": "17", "label": "MEGHALAYA"},
    {"value": "15", "label": "MIZORAM"},
    {"value": "13", "label": "NAGALAND"},
    {"value": "7",  "label": "NCT OF Delhi"},
    {"value": "99", "label": "NHCP"},
    {"value": "21", "label": "ODISHA"},
    {"value": "98", "label": "PSU"},
    {"value": "34", "label": "PUDUCHERRY"},
    {"value": "3",  "label": "PUNJAB"},
    {"value": "8",  "label": "RAJASTHAN"},
    {"value": "11", "label": "SIKKIM"},
    {"value": "33", "label": "TAMIL NADU"},
    {"value": "36", "label": "TELANGANA"},
    {"value": "16", "label": "TRIPURA"},
    {"value": "5",  "label": "UTTARAKHAND"},
    {"value": "9",  "label": "UTTAR PRADESH"},
    {"value": "19", "label": "WEST BENGAL"},
]

# Hospital type values exactly as the public form expects
HOSPITAL_TYPES = [
    ("Public", "Public"),
    ("PrivateNP", "Private (Not For Profit)"),
    ("PrivateP", "Private (For Profit)"),
]

# Throttling
SLEEP_BETWEEN = 2.0      # seconds between exports
SLEEP_BETWEEN_TYPES = 3.0
MAX_RETRIES = 4
TIMEOUT = 120


# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


# ---------------------------------------------------------------------------
def load_progress() -> dict[str, Any]:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"Progress unreadable, restarting: {e}")
    return {
        "done": [],   # list of "stateId|hospType" already exported+parsed
        "rows": [],   # list of dicts in the user's 36-column schema
    }


def save_progress(p: dict[str, Any]) -> None:
    PROGRESS_FILE.write_text(
        json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
def export_xls(state_id: str, hosp_type: str, dest: Path) -> str:
    """Hit the public export endpoint and save the .xls to disk.
    Returns 'ok' if xls saved, 'empty' if server returned HTML (no hospitals), 'fail' on error."""
    params = {
        "actionFlag": "ViewRegisteredHosptlsNew",
        "search": "Y",
        "applSearch": "N",
        "appReadOnly": "Y",
        "draftMenu": "N",
        "invalidMenu": "N",
        "export": "E",
        "searchState": state_id,
        "searchHospType": hosp_type,
    }
    url = EXPORT_URL + "?" + urllib.parse.urlencode(params)
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(url, headers=HEADERS, data=b"", timeout=TIMEOUT)
            ct = r.headers.get("Content-Type", "")
            body = r.content
            if r.status_code == 200:
                if b"<!DOCTYPE" in body[:200] or b"<html" in body[:200].lower():
                    return "empty"
                if "excel" in ct or "spreadsheet" in ct or len(body) > 5000:
                    dest.write_bytes(body)
                    return "ok"
            log(f"  attempt {attempt+1}: status={r.status_code} ct={ct} size={len(body)}")
        except Exception as e:
            log(f"  attempt {attempt+1} exception: {e}")
        time.sleep(3 + attempt * 2)
    return "fail"


def parse_xls(path: Path, state_label: str, hosp_type: str) -> list[dict[str, str]]:
    """Parse the public export xls into the 36-column schema. Empty cells for fields not in the export."""
    wb = xlrd.open_workbook(str(path))
    ws = wb.sheet_by_index(0)
    # first row is header
    headers: list[str] = []
    for c in range(ws.ncols):
        headers.append(str(ws.cell_value(0, c)).strip())
    rows: list[dict[str, str]] = []
    for r in range(1, ws.nrows):
        raw: dict[str, str] = {}
        for c in range(ws.ncols):
            v = ws.cell_value(r, c)
            s = "" if v is None else str(v).strip()
            if c < len(headers):
                raw[headers[c]] = s
        # Map raw columns -> 36 columns
        row = {col: "" for col in COLUMNS}
        row["Sr No"] = str(len(rows) + 1)
        row["Hospital Name"] = raw.get("Hospital Name", "")
        row["Hospital ID (UUID)"] = raw.get("Hospital Id", "")
        row["State"] = raw.get("State", state_label)
        row["Subdistrict"] = ""  # not in public export
        row["Town"] = raw.get("District", "")
        row["Village"] = ""
        row["Pincode"] = ""
        # Hospital Contact often appears as "NA" or a number
        contact = raw.get("Hospital Contact", "")
        row["Mobile Number"] = contact
        row["Helpline"] = contact
        row["Specialities"] = raw.get("Specialities Selected", "") or raw.get("Current Specialities", "")
        row["Sub -Specialty"] = raw.get("Upgraded Specialities", "")
        row["Hospital Care Type"] = raw.get("Hospital Type", hosp_type)
        row["Hospital Category"] = raw.get("Empanelment Type", "")
        # rest stay empty
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
def main() -> None:
    LOG_FILE.touch(exist_ok=True)
    log("=" * 60)
    log("PMJAY Public Hospital Scraper starting")
    progress = load_progress()
    log(f"Resuming: {len(progress.get('done', []))} combos done, {len(progress.get('rows', []))} rows.")

    for st in STATES:
        for type_code, type_label in HOSPITAL_TYPES:
            key = f"{st['value']}|{type_code}"
            if key in progress["done"]:
                log(f"Skip {st['label']} / {type_label} (done)")
                continue
            xls_path = RAW_DIR / f"state{st['value']}_{type_code}.xls"
            log(f"=== {st['label']} / {type_label} ===")
            status = export_xls(st["value"], type_code, xls_path)
            if status == "empty":
                log(f"  0 hospitals (server returned HTML)")
                progress["done"].append(key)
                save_progress(progress)
                time.sleep(SLEEP_BETWEEN)
                continue
            if status != "ok":
                log(f"  FAILED export for {st['label']} / {type_label}")
                time.sleep(SLEEP_BETWEEN_TYPES)
                continue
            try:
                rows = parse_xls(xls_path, st["label"], type_label)
            except Exception as e:
                log(f"  parse error: {e}")
                time.sleep(SLEEP_BETWEEN_TYPES)
                continue
            log(f"  parsed {len(rows)} rows")
            progress["rows"].extend(rows)
            progress["done"].append(key)
            save_progress(progress)
            write_outputs(progress)
            time.sleep(SLEEP_BETWEEN_TYPES if type_code == "PrivateP" else SLEEP_BETWEEN)

    write_outputs(progress)
    log(f"DONE. Total rows: {len(progress['rows'])}")
    log(f"CSV:  {CSV_FILE}")
    log(f"JSON: {JSON_FILE}")


def write_outputs(progress: dict[str, Any]) -> None:
    rows = progress["rows"]
    # Re-number Sr No globally
    for i, r in enumerate(rows, start=1):
        r["Sr No"] = str(i)
    # CSV
    with CSV_FILE.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r.get(c, "") for c in COLUMNS])
    # JSON
    JSON_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  wrote {len(rows)} rows to {CSV_FILE.name} + {JSON_FILE.name}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Interrupted. Progress saved.")
    except Exception as e:
        log(f"FATAL: {e}")
        raise
