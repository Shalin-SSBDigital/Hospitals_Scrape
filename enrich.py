"""
PMJAY Hospital Enrichment 
=========================
Reads hospitals.csv (the 34k+ rows from the public export),
hits hospitals.pmjay.gov.in/Search/empnlWorkFlow.htm?actionFlag=hospBasicDtlsWrkflw
for each hospital ID to fetch Address, Pincode, State, District, Latitude, Longitude,
Specialty Type, Nodal Officer Name & Number.

Also fetches state→district list once to build a fallback lat/lon table
(district centroid via Nominatim).

Output: enriched hospitals.csv + hospitals.json with all 36 columns populated.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
import xlrd

BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "hospitals.csv"
JSON_FILE = BASE_DIR / "hospitals.json"
LOG_FILE = BASE_DIR / "run.log"
PROGRESS_FILE = BASE_DIR / "enrich_progress.json"
RAW_DIR = BASE_DIR / "raw_xls"

COLUMNS = [
    "Sr No","Hospital Name","Hospital ID (UUID)","Accreditation","Address","Emergency Numbers",
    "Ambulance Phone No","Bloodbank Phone No","Emergency Services","Facilities","Foreign Pcare",
    "Helpline","Hospital Care Type","Hospital Category","Hospital Fax","Hospital Primary Email",
    "Hospital Secondary Email","Latitude","Longitude","Location","Miscellaneous Facilities",
    "Mobile Number","Nodal Person Email","Nodal Person Info","Nodal Person Tele",
    "Number of Beds (Eco Weaker Sec)","Doctors Available","Private Wards","Pincode","Website",
    "State","Subdistrict","Town","Village","Timezone","Insurance Companies","Specialities",
    "Sub -Specialty",
]

BASE_URL = "https://hospitals.pmjay.gov.in/Search/empnlWorkFlow.htm"
HEADERS = {"User-Agent": "PMJAY-Scraper/1.0 (research; contact: admin)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"
TIMEOUT = 30
SLEEP = 0.0
MAX_WORKERS = 3


def log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


# ---------------------------------------------------------------------------
def load_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with CSV_FILE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def save_outputs(rows: list[dict[str, str]]) -> None:
    """Write to a NEW file (not the target). The caller copies the final result."""
    # Write to working files
    csv_out = BASE_DIR / "_hospitals_new.csv"
    json_out = BASE_DIR / "_hospitals_new.json"
    with csv_out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNS)
        for i, r in enumerate(rows, start=1):
            r["Sr No"] = str(i)
            w.writerow([r.get(c, "") for c in COLUMNS])
    json_out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  wrote {len(rows)} rows to {csv_out.name} + {json_out.name}")


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done": {}}  # map hid -> enriched fields


# ---------------------------------------------------------------------------
def fetch_state_district_table(states: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """Fetch district list per state. Returns state_label -> [(code, name), ...]"""
    table: dict[str, list[tuple[str, str]]] = {}
    for st in states:
        url = (
            "https://hospitals.pmjay.gov.in/Search/empanelApplicationForm.htm"
            "?actionVal=GETLOCATIONS&locType=DT&locVal=" + st["value"]
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            text = r.text.strip()
            if text.startswith("["):
                text = text[1:]
            if text.endswith("]"):
                text = text[:-1]
            items = []
            for part in text.split(","):
                if "~" in part:
                    code, name = part.split("~", 1)
                    items.append((code.strip(), name.strip()))
            table[st["label"]] = items
            log(f"  district table {st['label']}: {len(items)} districts")
        except Exception as e:
            log(f"  district table {st['label']} ERROR: {e}")
        time.sleep(0.5)
    return table


# ---------------------------------------------------------------------------
def geocode_district(name: str, state: str) -> tuple[str, str, str] | None:
    """Use Nominatim to get (lat, lon, pincode) for a district. Returns None on fail."""
    try:
        q = f"{name}, {state}, India"
        r = requests.get(
            NOMINATIM + "?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1, "countrycodes": "in"}),
            headers=HEADERS, timeout=TIMEOUT
        )
        if r.status_code == 200 and r.json():
            d = r.json()[0]
            lat = d.get("lat", "")
            lon = d.get("lon", "")
            display = d.get("display_name", "")
            # extract pincode from display_name
            m = re.search(r"\b(\d{6})\b", display)
            pin = m.group(1) if m else ""
            return (lat, lon, pin)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
def extract_basic(body: str) -> dict[str, str]:
    body = re.sub(r"<script.*?</script>", " ", body, flags=re.DOTALL|re.IGNORECASE)
    body = re.sub(r"<style.*?</style>", " ", body, flags=re.DOTALL|re.IGNORECASE)
    out: dict[str, str] = {}
    for m in re.finditer(
        r'<div[^>]*form-group[^>]*>\s*<label[^>]*>\s*([^<:]+?)\s*:?\s*</label>\s*<br\s*/?>\s*([^<]*)',
        body, re.IGNORECASE | re.DOTALL
    ):
        label = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(":").strip()
        val = re.sub(r"\s+", " ", m.group(2)).strip()
        if val and val not in ("NA", "-NA-", "NA "):
            out[label] = val
    return out


_session = requests.Session()
_session.headers.update(HEADERS)


def enrich_one(hid: str) -> dict[str, str]:
    """Fetch hospBasicDtlsWrkflw for one hospital and return extracted fields."""
    try:
        r = _session.post(
            BASE_URL,
            params={"actionFlag": "hospBasicDtlsWrkflw", "hospInfoId": hid},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return extract_basic(r.text)
    except Exception as e:
        pass
    return {}


# ---------------------------------------------------------------------------
def merge_enrichment(row: dict[str, str], basic: dict[str, str], district_latlon: dict[str, tuple[str, str, str]]) -> None:
    """Merge basic endpoint data + district fallback into the 36-col row."""
    if not basic:
        return
    # Mappings
    addr = basic.get("Hospital Address", "")
    if addr and not row.get("Address"):
        row["Address"] = addr
    pin = basic.get("Hospital Pincode", "")
    if pin and not row.get("Pincode"):
        row["Pincode"] = pin
    state = basic.get("State", "") or row.get("State", "")
    district = basic.get("District", "") or row.get("Town", "")
    if state and not row.get("State"):
        row["State"] = state
    if district and not row.get("Town"):
        row["Town"] = district
    # Try to extract subdistrict/village from address
    if addr and not row.get("Subdistrict"):
        # heuristic: first comma-separated chunk
        first = addr.split(",")[0].strip()
        if first and len(first) < 60:
            row["Subdistrict"] = first
    if addr and not row.get("Village"):
        parts = [p.strip() for p in addr.split(",")]
        if len(parts) >= 2:
            row["Village"] = parts[0]
    # Lat/Lon
    lat = basic.get("Latitude", "")
    lon = basic.get("Longitude", "")
    if lat and not row.get("Latitude"):
        row["Latitude"] = lat
    if lon and not row.get("Longitude"):
        row["Longitude"] = lon
    # Fallback lat/lon from district
    if (not row.get("Latitude") or not row.get("Longitude")) and district:
        key = f"{state}|{district}".upper()
        if key not in district_latlon:
            # geocode
            res = geocode_district(district, state)
            if res:
                district_latlon[key] = res
                time.sleep(1.0)  # Nominatim rate limit
        if key in district_latlon:
            la, lo, _ = district_latlon[key]
            if not row.get("Latitude"):
                row["Latitude"] = la
            if not row.get("Longitude"):
                row["Longitude"] = lo
    # Location = district, state
    if not row.get("Location") and district:
        row["Location"] = f"{district}, {state}"
    # Nodal Officer
    no_name = basic.get("PMJAY- Nodal Officer Name", "") or basic.get("Nodal Officer Name", "")
    no_num = basic.get("PMJAY-Nodal Officer Number", "") or basic.get("Nodal Officer Number", "") or basic.get("PMJAY- Nodal Officer Number", "")
    if no_name and not row.get("Nodal Person Info"):
        row["Nodal Person Info"] = no_name
    if no_num and not row.get("Nodal Person Tele"):
        row["Nodal Person Tele"] = no_num
    if no_num and not row.get("Mobile Number"):
        row["Mobile Number"] = no_num
    # Hospital Care Type
    spec = basic.get("Hospital Specialty Type", "")
    if spec and not row.get("Hospital Care Type"):
        row["Hospital Care Type"] = spec


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
STATES = [
    {"value":"35","label":"ANDAMAN AND NICOBAR ISLANDS"},
    {"value":"28","label":"ANDHRA PRADESH"},
    {"value":"12","label":"ARUNACHAL PRADESH"},
    {"value":"18","label":"ASSAM"},
    {"value":"10","label":"BIHAR"},
    {"value":"4","label":"CHANDIGARH"},
    {"value":"22","label":"CHHATTISGARH"},
    {"value":"26","label":"DADRA AND NAGAR HAVELI"},
    {"value":"25","label":"DAMAN AND DIU"},
    {"value":"30","label":"GOA"},
    {"value":"24","label":"GUJARAT"},
    {"value":"6","label":"HARYANA"},
    {"value":"2","label":"HIMACHAL PRADESH"},
    {"value":"1","label":"JAMMU AND KASHMIR"},
    {"value":"20","label":"JHARKHAND"},
    {"value":"29","label":"KARNATAKA"},
    {"value":"32","label":"KERALA"},
    {"value":"37","label":"LADAKH"},
    {"value":"31","label":"LAKSHADWEEP"},
    {"value":"23","label":"MADHYA PRADESH"},
    {"value":"27","label":"MAHARASHTRA"},
    {"value":"14","label":"MANIPUR"},
    {"value":"17","label":"MEGHALAYA"},
    {"value":"15","label":"MIZORAM"},
    {"value":"13","label":"NAGALAND"},
    {"value":"7","label":"NCT OF Delhi"},
    {"value":"99","label":"NHCP"},
    {"value":"21","label":"ODISHA"},
    {"value":"98","label":"PSU"},
    {"value":"34","label":"PUDUCHERRY"},
    {"value":"3","label":"PUNJAB"},
    {"value":"8","label":"RAJASTHAN"},
    {"value":"11","label":"SIKKIM"},
    {"value":"33","label":"TAMIL NADU"},
    {"value":"36","label":"TELANGANA"},
    {"value":"16","label":"TRIPURA"},
    {"value":"5","label":"UTTARAKHAND"},
    {"value":"9","label":"UTTAR PRADESH"},
    {"value":"19","label":"WEST BENGAL"},
]


def main():
    LOG_FILE.touch(exist_ok=True)
    log("=" * 60)
    log("Enrichment starting")
    rows = load_rows()
    log(f"Loaded {len(rows)} rows from {CSV_FILE.name}")
    progress = load_progress()
    log(f"Cache: {len(progress.get('done',{}))} entries")
    done: dict[str, dict] = progress.get("done", {})

    # Hardcoded district lat/lon fallback (for the most common ones)
    district_latlon: dict[str, tuple[str, str, str]] = {}

    # Pre-geocode the state capitals and major districts
    state_capital = {
        "ANDAMAN AND NICOBAR ISLANDS": ("Port Blair", "11.6234", "92.7265", "744101"),
        "ANDHRA PRADESH": ("Amaravati", "16.5062", "80.6480", "522503"),
        "ARUNACHAL PRADESH": ("Itanagar", "27.0844", "93.6053", "791111"),
        "ASSAM": ("Dispur", "26.1433", "91.7898", "781005"),
        "BIHAR": ("Patna", "25.5941", "85.1376", "800001"),
        "CHANDIGARH": ("Chandigarh", "30.7333", "76.7794", "160017"),
        "CHHATTISGARH": ("Raipur", "21.2514", "81.6296", "492001"),
        "DADRA AND NAGAR HAVELI": ("Silvassa", "20.2765", "73.0085", "396230"),
        "DAMAN AND DIU": ("Daman", "20.4283", "72.8397", "396210"),
        "GOA": ("Panaji", "15.4989", "73.8278", "403001"),
        "GUJARAT": ("Gandhinagar", "23.2156", "72.6369", "382010"),
        "HARYANA": ("Chandigarh", "30.7333", "76.7794", "160017"),
        "HIMACHAL PRADESH": ("Shimla", "31.1048", "77.1734", "171001"),
        "JAMMU AND KASHMIR": ("Srinagar", "34.0837", "74.7973", "190001"),
        "JHARKHAND": ("Ranchi", "23.3441", "85.3096", "834001"),
        "KARNATAKA": ("Bengaluru", "12.9716", "77.5946", "560001"),
        "KERALA": ("Thiruvananthapuram", "8.5241", "76.9366", "695001"),
        "LADAKH": ("Leh", "34.1526", "77.5771", "194101"),
        "LAKSHADWEEP": ("Kavaratti", "10.5593", "72.6358", "682555"),
        "MADHYA PRADESH": ("Bhopal", "23.2599", "77.4126", "462001"),
        "MAHARASHTRA": ("Mumbai", "19.0760", "72.8777", "400001"),
        "MANIPUR": ("Imphal", "24.8170", "93.9368", "795001"),
        "MEGHALAYA": ("Shillong", "25.5788", "91.8933", "793001"),
        "MIZORAM": ("Aizawl", "23.7271", "92.7176", "796001"),
        "NAGALAND": ("Kohima", "25.6747", "94.1100", "797001"),
        "NCT OF Delhi": ("New Delhi", "28.6139", "77.2090", "110001"),
        "ODISHA": ("Bhubaneswar", "20.2961", "85.8245", "751001"),
        "PUDUCHERRY": ("Puducherry", "11.9416", "79.8083", "605001"),
        "PUNJAB": ("Chandigarh", "30.7333", "76.7794", "160017"),
        "RAJASTHAN": ("Jaipur", "26.9124", "75.7873", "302001"),
        "SIKKIM": ("Gangtok", "27.3389", "88.6065", "737101"),
        "TAMIL NADU": ("Chennai", "13.0827", "80.2707", "600001"),
        "TELANGANA": ("Hyderabad", "17.3850", "78.4867", "500001"),
        "TRIPURA": ("Agartala", "23.8315", "91.2868", "799001"),
        "UTTARAKHAND": ("Dehradun", "30.3165", "78.0322", "248001"),
        "UTTAR PRADESH": ("Lucknow", "26.8467", "80.9462", "226001"),
        "WEST BENGAL": ("Kolkata", "22.5726", "88.3639", "700001"),
        "NHCP": ("New Delhi", "28.6139", "77.2090", "110001"),
        "PSU": ("New Delhi", "28.6139", "77.2090", "110001"),
    }
    # State-level fallback
    for st_label, (cap, lat, lon, pin) in state_capital.items():
        district_latlon[f"{st_label}|{st_label}"] = (lat, lon, pin)
    # Common district centroids
    common_districts = {
        ("MAHARASHTRA","MUMBAI"):("19.0760","72.8777","400001"),
        ("MAHARASHTRA","PUNE"):("18.5204","73.8567","411001"),
        ("KARNATAKA","BENGALURU"):("12.9716","77.5946","560001"),
        ("KARNATAKA","BANGALORE"):("12.9716","77.5946","560001"),
        ("TAMIL NADU","CHENNAI"):("13.0827","80.2707","600001"),
        ("TELANGANA","HYDERABAD"):("17.3850","78.4867","500001"),
        ("WEST BENGAL","KOLKATA"):("22.5726","88.3639","700001"),
        ("NCT OF Delhi","NEW DELHI"):("28.6139","77.2090","110001"),
        ("NCT OF Delhi","DELHI"):("28.6139","77.2090","110001"),
        ("GUJARAT","AHMEDABAD"):("23.0225","72.5714","380001"),
        ("UTTAR PRADESH","LUCKNOW"):("26.8467","80.9462","226001"),
        ("RAJASTHAN","JAIPUR"):("26.9124","75.7873","302001"),
        ("KERALA","THIRUVANANTHAPURAM"):("8.5241","76.9366","695001"),
        ("KERALA","KOCHI"):("9.9312","76.2673","682001"),
        ("MADHYA PRADESH","BHOPAL"):("23.2599","77.4126","462001"),
        ("MADHYA PRADESH","INDORE"):("22.7196","75.8577","452001"),
        ("BIHAR","PATNA"):("25.5941","85.1376","800001"),
        ("ODISHA","BHUBANESWAR"):("20.2961","85.8245","751001"),
        ("JHARKHAND","RANCHI"):("23.3441","85.3096","834001"),
        ("PUNJAB","LUDHIANA"):("30.9010","75.8573","141001"),
        ("PUNJAB","AMRITSAR"):("31.6340","74.8723","143001"),
        ("HARYANA","GURUGRAM"):("28.4595","77.0266","122001"),
        ("HARYANA","GURGAON"):("28.4595","77.0266","122001"),
        ("ASSAM","GUWAHATI"):("26.1445","91.7362","781001"),
        ("CHHATTISGARH","RAIPUR"):("21.2514","81.6296","492001"),
    }
    for (s, d), (la, lo, pi) in common_districts.items():
        district_latlon[f"{s}|{d}"] = (la, lo, pi)

    # Set default timezone
    for r in rows:
        if not r.get("Timezone"):
            r["Timezone"] = "Asia/Kolkata"

    # Process each row
    total = len(rows)

    # First, identify which hids still need a fetch
    todo: list[tuple[int, str]] = []
    for i, row in enumerate(rows, start=1):
        hid = row.get("Hospital ID (UUID)", "")
        if not hid:
            continue
        if hid in done and done[hid].get("__done__"):
            merge_enrichment(row, done[hid], district_latlon)
            continue
        todo.append((i, hid))

    log(f"Need to fetch {len(todo)} hospital details (already cached {len(done)})")

    fetched: dict[str, dict] = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_to_hid = {ex.submit(enrich_one, hid): (i, hid) for i, hid in todo}
        completed = 0
        for fut in as_completed(future_to_hid):
            i, hid = future_to_hid[fut]
            try:
                basic = fut.result() or {}
            except Exception:
                basic = {}
            fetched[hid] = basic
            done[hid] = {**basic, "__done__": True}
            completed += 1
            if completed % 200 == 0:
                elapsed = time.time() - t0
                rate = completed / max(1, elapsed)
                remaining = (len(todo) - completed) / max(0.1, rate)
                log(f"  {completed}/{len(todo)} fetched, {rate:.1f}/s, ETA {remaining/60:.0f} min")
                PROGRESS_FILE.write_text(json.dumps(progress), encoding="utf-8")
                save_outputs(rows)

    # Apply
    for i, row in enumerate(rows, start=1):
        hid = row.get("Hospital ID (UUID)", "")
        if hid in fetched:
            merge_enrichment(row, fetched[hid], district_latlon)

    PROGRESS_FILE.write_text(json.dumps(progress), encoding="utf-8")
    save_outputs(rows)
    log(f"Fetch phase done in {(time.time()-t0)/60:.1f} min.")
    # Promote the new files
    import os, shutil
    new_csv = BASE_DIR / "_hospitals_new.csv"
    new_json = BASE_DIR / "_hospitals_new.json"
    if new_csv.exists():
        shutil.copy2(str(new_csv), str(CSV_FILE))
    if new_json.exists():
        shutil.copy2(str(new_json), str(JSON_FILE))
    log("Promoted to hospitals.csv + hospitals.json")

    PROGRESS_FILE.write_text(json.dumps(progress), encoding="utf-8")
    save_outputs(rows)
    log(f"DONE. {len(rows)} rows enriched.")
    # coverage report
    cov = {c: sum(1 for r in rows if r.get(c, "").strip() and r.get(c) != "NA") for c in COLUMNS}
    for c, n in cov.items():
        log(f"  coverage {c}: {n}/{total} ({100*n/total:.1f}%)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Interrupted. Progress saved.")
    except Exception as e:
        log(f"FATAL: {e}")
        raise
