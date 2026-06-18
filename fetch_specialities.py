"""
Fetch current specialities for ALL hospitals from the PMJAY website.
Hits spclityServicesDetails for each hospital ID, parses checked checkboxes,
and updates the Specialities column in hospitals.csv + hospitals.json.

Resume-safe via specialities_fetch_progress.json cache.
"""
from __future__ import annotations

import csv
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

import requests

BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "hospitals.csv"
JSON_FILE = BASE_DIR / "hospitals.json"
SPEC_LOOKUP = BASE_DIR / "specialities_lookup.csv"
PROGRESS_FILE = BASE_DIR / "specialities_fetch_progress.json"
LOG_FILE = BASE_DIR / "run.log"

COLUMNS = [
    "Sr No", "Hospital Name", "Hospital ID (UUID)", "Accreditation", "Address",
    "Emergency Numbers", "Ambulance Phone No", "Bloodbank Phone No",
    "Emergency Services", "Facilities", "Foreign Pcare", "Helpline",
    "Hospital Care Type", "Hospital Category", "Hospital Fax",
    "Hospital Primary Email", "Hospital Secondary Email", "Latitude", "Longitude",
    "Location", "Miscellaneous Facilities", "Mobile Number",
    "Nodal Person Email", "Nodal Person Info", "Nodal Person Tele",
    "Number of Beds (Eco Weaker Sec)", "Doctors Available", "Private Wards",
    "Pincode", "Website", "State", "Subdistrict", "Town", "Village",
    "Timezone", "Insurance Companies", "Specialities", "Sub -Specialty",
]

BASE_URL = "https://hospitals.pmjay.gov.in/Search/empnlWorkFlow.htm"
HEADERS = {"User-Agent": "PMJAY-Speciality-Fetcher/1.0 (research)"}
TIMEOUT = 20
SLEEP = 0.3
MAX_WORKERS = 3
BATCH_SIZE = 200


def log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def load_lookup() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    with SPEC_LOOKUP.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row["Code"].strip()
            full = row["FullForm"].strip()
            if code:
                mapping[code] = full if full else code
    mapping["US"] = "US-Unspecified Surgical Package"
    mapping["S18"] = "S18-Not Available"
    mapping["M1"] = "M1-General Medicine"
    mapping["M2"] = "M2-Paediatric medical management"
    mapping["M3"] = "M3-Neo-natal"
    mapping["M4"] = "M4-Paediatric cancer"
    mapping["M5"] = "M5-Medical Oncology"
    mapping["M6"] = "M6-Radiation Oncology"
    mapping["M7"] = "M7-Emergency Room Packages (Care requiring less than 12 hrs stay)"
    mapping["M8"] = "M8-Mental Disorders Packages"
    mapping["M10"] = "M10-OPD Diagnostic"
    mapping["S1"] = "S1-General Surgery"
    mapping["S2"] = "S2-Otorhinolaryngology"
    mapping["S3"] = "S3-Opthalmology"
    mapping["S4"] = "S4-Obstetrics & Gynaecology"
    mapping["S5"] = "S5-Orthopaedics"
    mapping["S6"] = "S6-Polytrauma"
    mapping["S7"] = "S7-Urology"
    mapping["S8"] = "S8-Neurosurgery"
    mapping["S9"] = "S9-Interventional Neuroradiology"
    mapping["S10"] = "S10-Plastic & reconstructive"
    mapping["S11"] = "S11-Burns management"
    mapping["S12"] = "S12-Cardiology"
    mapping["S13"] = "S13-Cardio-thoracic & Vascular surgery"
    mapping["S14"] = "S14-Paediatric surgery"
    mapping["S15"] = "S15-Surgical Oncology"
    mapping["S16"] = "S16-Oral and Maxillofacial Surgery"
    mapping["S18"] = "S18-Not Available"
    return mapping


def load_rows() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with CSV_FILE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def load_progress() -> Dict[str, List[str]]:
    if PROGRESS_FILE.exists():
        try:
            data: Dict[str, List[str]] = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            return data
        except Exception:
            pass
    return {}


def save_progress(progress: Dict[str, List[str]]) -> None:
    tmp = PROGRESS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PROGRESS_FILE)


_session = requests.Session()
_session.headers.update(HEADERS)


def fetch_specialities(hid: str) -> Tuple[str, List[str], List[str], List[str]]:
    """Fetch specialities for a single hospital from the website.
    Returns (hid, hosp_applied, empanelled, upgraded) code lists.
    """
    hosp_applied: List[str] = []
    empanelled: List[str] = []
    upgraded: List[str] = []
    try:
        r = _session.post(
            BASE_URL,
            params={"actionFlag": "spclityServicesDetails", "hospInfoId": hid, "appReadOnly": "Y"},
            timeout=TIMEOUT,
        )
        if r.status_code == 200 and len(r.text) > 5000:
            hosp_applied = re.findall(r'<input[^>]*id="hosp(\w+)"[^>]*checked', r.text)
            empanelled = re.findall(r'<input[^>]*id="emp(\w+)"[^>]*checked', r.text)
            upgraded = re.findall(r'<input[^>]*id="upEmp(\w+)"[^>]*checked', r.text)
    except Exception:
        pass
    return (hid, hosp_applied, empanelled, upgraded)


def expand_codes(codes: List[str], mapping: Dict[str, str]) -> str:
    if not codes:
        return ""
    unique = sorted(set(c for c in codes if c))
    expanded = []
    for code in unique:
        full = mapping.get(code, f"{code}-{code}")
        expanded.append(full)
    return ", ".join(expanded)


def main() -> None:
    log("=" * 60)
    log("Specialities fetch starting")
    spec_map = load_lookup()
    log(f"Loaded {len(spec_map)} speciality codes")

    rows = load_rows()
    log(f"Loaded {len(rows)} rows from {CSV_FILE.name}")

    progress = load_progress()
    cached_count = len(progress)
    log(f"Cache: {cached_count} entries")

    empty_before = sum(1 for r in rows if not r.get("Specialities", "").strip())
    filled_before = sum(1 for r in rows if r.get("Specialities", "").strip())
    log(f"Before: {filled_before} with specialities, {empty_before} empty")

    todo: List[Tuple[int, str]] = []
    for i, row in enumerate(rows):
        hid = row.get("Hospital ID (UUID)", "")
        if not hid:
            continue
        if hid not in progress:
            todo.append((i, hid))

    log(f"Need to fetch {len(todo)} hospital specialities (already cached {cached_count})")

    fetched: Dict[str, List[str]] = {}
    t0 = time.time()
    completed = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_to_idx = {ex.submit(fetch_specialities, hid): (i, hid) for i, hid in todo}
        for fut in as_completed(future_to_idx):
            i, hid = future_to_idx[fut]
            try:
                _, hosp, emp, upg = fut.result()
                all_codes = sorted(set(hosp + emp + upg))
                fetched[hid] = all_codes
                progress[hid] = all_codes
            except Exception:
                errors += 1
                progress[hid] = []

            completed += 1
            if completed % BATCH_SIZE == 0:
                elapsed = time.time() - t0
                rate = completed / max(1, elapsed)
                remaining = (len(todo) - completed) / max(0.1, rate)
                log(f"  {completed}/{len(todo)} fetched, {rate:.1f}/s, ETA {remaining / 60:.0f}min, {errors} errors")
                save_progress(progress)

    save_progress(progress)
    elapsed = time.time() - t0
    log(f"Fetch phase done in {elapsed / 60:.1f}min. {completed} fetched, {errors} errors")

    applied = 0
    updated = 0
    recovered = 0

    for row in rows:
        hid = row.get("Hospital ID (UUID)", "")
        if hid not in progress:
            continue
        codes = progress[hid]
        if not codes:
            continue
        new_spec = expand_codes(codes, spec_map)
        if not new_spec:
            continue
        old_spec = row.get("Specialities", "").strip()
        if new_spec != old_spec:
            row["Specialities"] = new_spec
            applied += 1
            if not old_spec:
                recovered += 1
            else:
                updated += 1

    log(f"Applied {applied} rows ({recovered} recovered from empty, {updated} updated with newer data)")

    for i, r in enumerate(rows, start=1):
        r["Sr No"] = str(i)

    tmp_csv = CSV_FILE.with_suffix(".csv.tmp")
    with tmp_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r.get(c, "") for c in COLUMNS])
    tmp_csv.replace(CSV_FILE)
    log(f"Wrote {CSV_FILE.name}")

    tmp_json = JSON_FILE.with_suffix(".json.tmp")
    tmp_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_json.replace(JSON_FILE)
    log(f"Wrote {JSON_FILE.name}")

    empty_after = sum(1 for r in rows if not r.get("Specialities", "").strip())
    filled_after = sum(1 for r in rows if r.get("Specialities", "").strip())
    log(f"After:  {filled_after} with specialities, {empty_after} empty")
    log(f"Recovered {recovered} previously-empty rows, updated {updated} with newer data")
    log(f"Specialities coverage: {100 * filled_after / len(rows):.1f}%")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Interrupted. Progress saved.")
    except Exception as e:
        log(f"FATAL: {e}")
        raise