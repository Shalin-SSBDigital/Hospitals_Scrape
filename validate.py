"""
PMJAY Hospital Data Validator
=============================
Applies 19 strict validation rules to hospitals.csv and produces:
  - hospitals.csv / hospitals.json : clean version (invalid rows removed)
  - hospitals_rejected.csv         : rejected rows with Reason column
  - validation_report.txt          : human-readable report
  - validation_summary.json        : machine-readable summary
"""

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "hospitals.csv"
JSON_FILE = BASE_DIR / "hospitals.json"
SPEC_LOOKUP = BASE_DIR / "specialities_lookup.csv"
SUBSPEC_LOOKUP = BASE_DIR / "sub_specialties_lookup.csv"
REPORT_TXT = BASE_DIR / "validation_report.txt"
REPORT_JSON = BASE_DIR / "validation_summary.json"
REJECTED_CSV = BASE_DIR / "hospitals_rejected.csv"

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

EXPECTED_HEADER = COLUMNS

KNOWN_STATES = {
    "ANDAMAN AND NICOBAR ISLANDS", "ANDHRA PRADESH", "ARUNACHAL PRADESH", "ASSAM",
    "BIHAR", "CHANDIGARH", "CHHATTISGARH", "DADRA AND NAGAR HAVELI", "DAMAN AND DIU",
    "GOA", "GUJARAT", "HARYANA", "HIMACHAL PRADESH", "JAMMU AND KASHMIR", "JHARKHAND",
    "KARNATAKA", "KERALA", "LADAKH", "LAKSHADWEEP", "MADHYA PRADESH", "MAHARASHTRA",
    "MANIPUR", "MEGHALAYA", "MIZORAM", "NAGALAND", "NCT OF Delhi", "NHCP", "ODISHA",
    "PSU", "PUDUCHERRY", "PUNJAB", "RAJASTHAN", "SIKKIM", "TAMIL NADU", "TELANGANA",
    "TRIPURA", "UTTARAKHAND", "UTTAR PRADESH", "WEST BENGAL",
}

KNOWN_HOSPITAL_TYPES = {"Public", "Private(Not For Profit)", "Private(For Profit)"}

KNOWN_CATEGORIES = {
    "PMJAY", "PMJAY and CGHS", "PMJAY and CAPF", "Only CGHS", "Only CAPF", "CMHIS", "KASS"
}

# Indian state postal code region (first 2 digits) -> set of state names
PIN_REGION = {
    "11": {"NCT OF Delhi"},
    "12": {"HARYANA"},
    "13": {"HARYANA"},
    "14": {"PUNJAB"},
    "15": {"PUNJAB"},
    "16": {"CHANDIGARH", "PUNJAB", "HARYANA"},
    "17": {"HIMACHAL PRADESH"},
    "18": {"JAMMU AND KASHMIR", "LADAKH"},
    "19": {"JAMMU AND KASHMIR", "LADAKH"},
    "20": {"UTTAR PRADESH"},
    "21": {"UTTAR PRADESH"},
    "22": {"UTTAR PRADESH"},
    "23": {"UTTAR PRADESH"},
    "24": {"UTTAR PRADESH", "UTTARAKHAND", "GUJARAT"},
    "25": {"UTTAR PRADESH"},
    "26": {"UTTAR PRADESH", "UTTARAKHAND"},
    "27": {"UTTAR PRADESH"},
    "28": {"UTTAR PRADESH"},
    "30": {"RAJASTHAN"},
    "31": {"RAJASTHAN"},
    "32": {"RAJASTHAN"},
    "33": {"RAJASTHAN"},
    "34": {"RAJASTHAN"},
    "36": {"GUJARAT", "DADRA AND NAGAR HAVELI", "DAMAN AND DIU"},
    "37": {"GUJARAT"},
    "38": {"GUJARAT"},
    "39": {"GUJARAT"},
    "40": {"MAHARASHTRA", "GOA"},
    "41": {"MAHARASHTRA"},
    "42": {"MAHARASHTRA"},
    "43": {"MAHARASHTRA"},
    "44": {"MAHARASHTRA", "GUJARAT"},
    "45": {"MADHYA PRADESH"},
    "46": {"MADHYA PRADESH"},
    "47": {"MADHYA PRADESH"},
    "48": {"MADHYA PRADESH"},
    "49": {"MADHYA PRADESH", "CHHATTISGARH"},
    "50": {"TELANGANA"},
    "51": {"TELANGANA", "ANDHRA PRADESH"},
    "52": {"ANDHRA PRADESH", "TELANGANA"},
    "53": {"ANDHRA PRADESH"},
    "56": {"KARNATAKA"},
    "57": {"KARNATAKA"},
    "58": {"KARNATAKA"},
    "59": {"KARNATAKA"},
    "60": {"TAMIL NADU", "PUDUCHERRY"},
    "61": {"TAMIL NADU"},
    "62": {"TAMIL NADU"},
    "63": {"TAMIL NADU"},
    "64": {"TAMIL NADU", "PUDUCHERRY"},
    "67": {"KERALA", "TAMIL NADU", "PUDUCHERRY"},
    "68": {"KERALA", "LAKSHADWEEP"},
    "69": {"KERALA"},
    "70": {"WEST BENGAL"},
    "71": {"WEST BENGAL"},
    "72": {"WEST BENGAL"},
    "73": {"WEST BENGAL", "SIKKIM"},
    "74": {"WEST BENGAL", "ODISHA", "ANDAMAN AND NICOBAR ISLANDS"},
    "75": {"ODISHA"},
    "76": {"ODISHA"},
    "77": {"ODISHA"},
    "78": {"ASSAM", "MEGHALAYA"},
    "79": {"ASSAM", "ARUNACHAL PRADESH", "NAGALAND", "MANIPUR", "MIZORAM", "TRIPURA", "MEGHALAYA"},
    "80": {"BIHAR", "JHARKHAND"},
    "81": {"JHARKHAND"},
    "82": {"BIHAR"},
    "83": {"BIHAR", "JHARKHAND"},
    "84": {"BIHAR"},
    "85": {"BIHAR"},
    "90": {"ARUNACHAL PRADESH", "ASSAM", "NAGALAND", "MANIPUR", "MIZORAM", "TRIPURA", "MEGHALAYA"},
}

# HOSP ID prefix -> state code (2 digits) -> state name
# 2-digit state codes used by hospitals.pmjay.gov.in (from STATES table in scrape_hem.py)
STATE_CODE_TO_NAME = {
    "35": "ANDAMAN AND NICOBAR ISLANDS",
    "28": "ANDHRA PRADESH",
    "12": "ARUNACHAL PRADESH",
    "18": "ASSAM",
    "10": "BIHAR",
    "4":  "CHANDIGARH",
    "22": "CHHATTISGARH",
    "26": "DADRA AND NAGAR HAVELI",
    "25": "DAMAN AND DIU",
    "30": "GOA",
    "24": "GUJARAT",
    "6":  "HARYANA",
    "2":  "HIMACHAL PRADESH",
    "1":  "JAMMU AND KASHMIR",
    "20": "JHARKHAND",
    "29": "KARNATAKA",
    "32": "KERALA",
    "37": "LADAKH",
    "31": "LAKSHADWEEP",
    "23": "MADHYA PRADESH",
    "27": "MAHARASHTRA",
    "14": "MANIPUR",
    "17": "MEGHALAYA",
    "15": "MIZORAM",
    "13": "NAGALAND",
    "7":  "NCT OF Delhi",
    "21": "ODISHA",
    "34": "PUDUCHERRY",
    "3":  "PUNJAB",
    "8":  "RAJASTHAN",
    "11": "SIKKIM",
    "33": "TAMIL NADU",
    "36": "TELANGANA",
    "16": "TRIPURA",
    "5":  "UTTARAKHAND",
    "9":  "UTTAR PRADESH",
    "19": "WEST BENGAL",
    "99": "NHCP",
    "98": "PSU",
}

# (Approximate) state capital lat/lon for the Lat/Lon vs State sanity check.
STATE_CENTROID = {
    "ANDAMAN AND NICOBAR ISLANDS": (11.62, 92.73),
    "ANDHRA PRADESH": (15.91, 79.74),
    "ARUNACHAL PRADESH": (28.22, 94.73),
    "ASSAM": (26.20, 92.94),
    "BIHAR": (25.79, 85.32),
    "CHANDIGARH": (30.73, 76.78),
    "CHHATTISGARH": (21.27, 81.86),
    "DADRA AND NAGAR HAVELI": (20.27, 73.01),
    "DAMAN AND DIU": (20.43, 72.84),
    "GOA": (15.30, 74.12),
    "GUJARAT": (22.26, 71.19),
    "HARYANA": (29.06, 76.09),
    "HIMACHAL PRADESH": (31.10, 77.17),
    "JAMMU AND KASHMIR": (33.78, 76.58),
    "JHARKHAND": (23.62, 85.32),
    "KARNATAKA": (14.52, 75.71),
    "KERALA": (10.16, 76.21),
    "LADAKH": (34.30, 78.30),
    "LAKSHADWEEP": (10.56, 72.64),
    "MADHYA PRADESH": (23.47, 77.95),
    "MAHARASHTRA": (19.41, 75.66),
    "MANIPUR": (24.66, 93.90),
    "MEGHALAYA": (25.50, 91.25),
    "MIZORAM": (23.16, 92.94),
    "NAGALAND": (26.16, 94.65),
    "NCT OF Delhi": (28.64, 77.22),
    "ODISHA": (20.27, 84.81),
    "PUDUCHERRY": (11.93, 79.83),
    "PUNJAB": (30.85, 75.86),
    "RAJASTHAN": (26.45, 74.69),
    "SIKKIM": (27.33, 88.51),
    "TAMIL NADU": (10.79, 78.69),
    "TELANGANA": (17.85, 79.10),
    "TRIPURA": (23.74, 91.74),
    "UTTARAKHAND": (30.07, 79.32),
    "UTTAR PRADESH": (27.10, 80.85),
    "WEST BENGAL": (24.00, 87.95),
    "NHCP": (28.64, 77.22),
    "PSU": (28.64, 77.22),
}

# Regex patterns
RE_UUID = re.compile(r"^(HOSP\d{1,2}[A-Z]+\d+|\d{6,})$")  # HOSP format OR legacy numeric (NHCP/PSU)
RE_PIN = re.compile(r"^\d{6}$")
RE_MOBILE = re.compile(r"^\+?91?\d{10}$|^\d{10}$")
RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Load specialities lookup
SPEC_CODES: set[str] = set()
if SPEC_LOOKUP.exists():
    with SPEC_LOOKUP.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("Code", "").strip()
            if code and code != "Code":
                SPEC_CODES.add(code)

SUBSPEC_CODES: set[str] = set()
if SUBSPEC_LOOKUP.exists():
    with SUBSPEC_LOOKUP.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("Code", "").strip()
            if code and code != "Code":
                SUBSPEC_CODES.add(code)


def parse_float(s: str) -> float | None:
    if not s or s in ("NA", "-NA-"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def is_valid_coord(lat: float, lon: float) -> bool:
    return 6.5 <= lat <= 37.5 and 68.0 <= lon <= 97.5


def is_phone(s: str) -> bool:
    if not s or s in ("NA", "-NA-"):
        return False
    digits = re.sub(r"\D", "", s)
    return 10 <= len(digits) <= 13


def is_email(s: str) -> bool:
    if not s or s in ("NA", "-NA-"):
        return False
    return bool(RE_EMAIL.match(s.strip()))


def get_codes(value: str) -> list[str]:
    if not value or value in ("NA", "-NA-"):
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def check_row(row: dict, idx: int) -> list[str]:
    """Return a list of human-readable reason codes for why this row fails."""
    reasons: list[str] = []

    hid = (row.get("Hospital ID (UUID)") or "").strip()
    if not hid:
        reasons.append("missing_hospital_id")
    elif not RE_UUID.match(hid):
        reasons.append("invalid_hospital_id_format")

    name = (row.get("Hospital Name") or "").strip()
    if len(name) < 3 or len(name) > 200:
        reasons.append("invalid_hospital_name_length")
    if RE_CONTROL.search(name):
        reasons.append("control_chars_in_name")

    state = (row.get("State") or "").strip()
    if state and state not in KNOWN_STATES:
        reasons.append("unknown_state")

    # HOSP ID prefix must match state
    if hid and state:
        m = re.match(r"^HOSP(\d{2})[A-Z]", hid)
        if m:
            sc = m.group(1)
            expected = STATE_CODE_TO_NAME.get(sc)
            if expected and expected != state:
                reasons.append(f"hid_state_mismatch({sc}->{expected!r},got{state!r})")

    care_type = (row.get("Hospital Care Type") or "").strip()
    if care_type and care_type not in KNOWN_HOSPITAL_TYPES:
        reasons.append("unknown_care_type")

    category = (row.get("Hospital Category") or "").strip()
    if category and category not in KNOWN_CATEGORIES:
        reasons.append("unknown_category")

    pin = (row.get("Pincode") or "").strip()
    if pin and pin not in ("NA", "-NA-"):
        if not RE_PIN.match(pin):
            reasons.append("invalid_pincode_format")
        else:
            region = pin[:2]
            valid_states_for_pin = PIN_REGION.get(region)
            if valid_states_for_pin and state and state not in valid_states_for_pin:
                reasons.append(f"pincode_state_mismatch(pin{region},state{state!r})")

    lat = parse_float(row.get("Latitude"))
    lon = parse_float(row.get("Longitude"))
    if lat is not None and lon is not None:
        if not is_valid_coord(lat, lon):
            reasons.append(f"latlon_out_of_india({lat},{lon})")
        else:
            # Coarse check: lat/lon within ~5 degrees of state centroid
            centroid = STATE_CENTROID.get(state)
            if centroid:
                dlat = abs(lat - centroid[0])
                dlon = abs(lon - centroid[1])
                if dlat > 5.0 or dlon > 5.0:
                    reasons.append(f"latlon_too_far_from_state({dlat:.1f},{dlon:.1f})")
    elif lat is not None and lon is None:
        reasons.append("missing_longitude")
    elif lon is not None and lat is None:
        reasons.append("missing_latitude")

    mobile = (row.get("Mobile Number") or "").strip()
    if mobile and mobile not in ("NA", "-NA-"):
        if not is_phone(mobile):
            reasons.append("invalid_mobile")

    helpline = (row.get("Helpline") or "").strip()
    if helpline and helpline not in ("NA", "-NA-"):
        if not is_phone(helpline):
            reasons.append("invalid_helpline")

    email = (row.get("Hospital Primary Email") or "").strip()
    if email and email not in ("NA", "-NA-"):
        if not is_email(email):
            reasons.append("invalid_email")

    nemail = (row.get("Nodal Person Email") or "").strip()
    if nemail and nemail not in ("NA", "-NA-"):
        if not is_email(nemail):
            reasons.append("invalid_nodal_email")

    # Specialities codes must all be in lookup
    # Note: Specialities column has full forms like "M1-General Medicine"
    # Extract the short code prefix (before the first '-') and only check
    # if it looks like a real short code (1-4 letters + 0-2 digits, no spaces).
    if SPEC_CODES:
        for entry in get_codes(row.get("Specialities", "")):
            short = entry.split("-", 1)[0].strip()
            if not short or not re.match(r"^[A-Z]+\d*(\.\d+)?$", short):
                continue  # not a short code, treat as free text
            if short not in SPEC_CODES:
                reasons.append(f"unknown_speciality_code({short})")
                break  # one reason is enough
    # Sub -Specialty codes are FREE TEXT in the public export (Upgraded Specialities
    # column). Don't reject rows just because the sub-specialty isn't in our curated
    # list - only flag if it looks like a real short code that's clearly missing.
    # Skip this check entirely - sub-specialty validation is too noisy on free text.

    tz = (row.get("Timezone") or "").strip()
    if tz and tz != "Asia/Kolkata":
        reasons.append("wrong_timezone")

    return reasons


def main():
    print("Loading rows...", flush=True)
    with CSV_FILE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        rows = list(reader)
    print(f"Loaded {len(rows)} rows, header columns: {len(header) if header else 0}", flush=True)

    if header != EXPECTED_HEADER:
        print(f"WARNING: header mismatch", flush=True)

    # Duplicate detection
    seen_hids: set[str] = set()
    seen_npt: set[tuple[str, str, str]] = set()
    valid_rows: list[dict] = []
    rejected_rows: list[dict] = []
    reason_counter: Counter = Counter()
    all_rejected_details: list[tuple[int, str, list[str]]] = []

    for i, row in enumerate(rows, start=1):
        reasons = check_row(row, i)
        hid = (row.get("Hospital ID (UUID)") or "").strip()
        name = (row.get("Hospital Name") or "").strip()
        town = (row.get("Town") or "").strip()
        pin = (row.get("Pincode") or "").strip()

        if hid in seen_hids:
            reasons.append("duplicate_hospital_id")
        else:
            seen_hids.add(hid)

        key = (name.lower(), town.lower(), pin)
        if key[0] and key in seen_npt:
            reasons.append("duplicate_name_town_pin")
        else:
            seen_npt.add(key)

        if reasons:
            reason_counter.update(reasons)
            rr = dict(row)
            rr["__reasons__"] = "; ".join(reasons)
            rejected_rows.append(rr)
            all_rejected_details.append((i, hid, reasons))
        else:
            valid_rows.append(row)

    # Re-number valid rows
    for j, r in enumerate(valid_rows, start=1):
        r["Sr No"] = str(j)

    # Write clean CSV
    tmp_csv = CSV_FILE.with_suffix(".csv.tmp")
    with tmp_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(EXPECTED_HEADER)
        for r in valid_rows:
            w.writerow([r.get(c, "") for c in EXPECTED_HEADER])
    tmp_csv.replace(CSV_FILE)

    # Write clean JSON
    tmp_json = JSON_FILE.with_suffix(".json.tmp")
    tmp_json.write_text(json.dumps(valid_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_json.replace(JSON_FILE)

    # Write rejected CSV
    rej_columns = EXPECTED_HEADER + ["__reasons__"]
    with REJECTED_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(rej_columns)
        for r in rejected_rows:
            w.writerow([r.get(c, "") for c in rej_columns])

    # Write summary JSON
    summary = {
        "input_rows": len(rows),
        "valid_rows": len(valid_rows),
        "rejected_rows": len(rejected_rows),
        "rejection_rate": round(len(rejected_rows) / max(1, len(rows)) * 100, 2),
        "reasons": dict(reason_counter.most_common()),
        "by_state": dict(Counter(r.get("State", "") for r in valid_rows).most_common()),
    }
    REPORT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write human report
    lines = []
    lines.append("PMJAY Hospital Data Validation Report")
    lines.append("=" * 60)
    lines.append(f"Input rows:      {len(rows):>8,}")
    lines.append(f"Valid rows:      {len(valid_rows):>8,}")
    lines.append(f"Rejected rows:   {len(rejected_rows):>8,}")
    lines.append(f"Rejection rate:  {summary['rejection_rate']}%")
    lines.append("")
    lines.append("Top rejection reasons:")
    for reason, count in reason_counter.most_common(20):
        lines.append(f"  {count:>6,}  {reason}")
    lines.append("")
    lines.append("Valid rows by state (top 15):")
    for state, count in list(summary["by_state"].items())[:15]:
        lines.append(f"  {count:>6,}  {state}")
    lines.append("")
    lines.append("First 50 rejected rows:")
    lines.append("-" * 60)
    for orig_idx, hid, reasons in all_rejected_details[:50]:
        lines.append(f"  row {orig_idx:>6}  HID={hid!r}  reasons={reasons}")
    REPORT_TXT.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nDone.", flush=True)
    print(f"  Valid:     {len(valid_rows):>8,}", flush=True)
    print(f"  Rejected:  {len(rejected_rows):>8,}", flush=True)
    print(f"  Report:    {REPORT_TXT.name}", flush=True)
    print(f"  Summary:   {REPORT_JSON.name}", flush=True)
    print(f"  Rejected:  {REJECTED_CSV.name}", flush=True)


if __name__ == "__main__":
    main()
