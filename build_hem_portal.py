"""
Build hospitals_hem.csv in the user-specified 37-column format
=============================================================

Columns (exact order, exactly as specified by user):
  Hospital Name, Hospital ID (UUID), Accreditation, Address, Emergency Numbers,
  Ambulance Phone No, Bloodbank Phone No, Emergency Services, Facilities,
  Foreign Pcare, Helpline, Hospital Care Type, Hospital Category, Hospital Fax,
  Hospital Primary Email, Hospital Secondary Email, Latitude, Longitude,
  Location, Miscellaneous Facilities, Mobile Number, Nodal Person Email,
  Nodal Person Info, Nodal Person Tele, Number of Beds (Eco Weaker Sec),
  Doctors Available, Private Wards, Pincode, Website, State, Subdistrict,
  Town, Village, Timezone, Insurance Companies, Specialty, Sub -Specialty

Reads:
  - hem_raw.json         (output of scrape_hem_portal.py: dict[hospitalId] -> HEM row)
  - hem_specialities.json (HEM speciality list, id -> name)
  - hem_states.json      (state list + district list per state)

Writes:
  - hospitals_hem.csv     (37 columns, 36k rows)
  - hospitals_hem.json    (same)
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
HEM_RAW = BASE_DIR / "hem_raw.json"
HEM_SPECS = BASE_DIR / "hem_specialities.json"
HEM_STATES = BASE_DIR / "hem_states.json"
CSV_OUT = BASE_DIR / "hospitals_hem.csv"
JSON_OUT = BASE_DIR / "hospitals_hem.json"

COLUMNS = [
    "Hospital Name", "Hospital ID (UUID)", "Accreditation", "Address",
    "Emergency Numbers", "Ambulance Phone No", "Bloodbank Phone No",
    "Emergency Services", "Facilities", "Foreign Pcare", "Helpline",
    "Hospital Care Type", "Hospital Category", "Hospital Fax",
    "Hospital Primary Email", "Hospital Secondary Email", "Latitude", "Longitude",
    "Location", "Miscellaneous Facilities", "Mobile Number",
    "Nodal Person Email", "Nodal Person Info", "Nodal Person Tele",
    "Number of Beds (Eco Weaker Sec)", "Doctors Available", "Private Wards",
    "Pincode", "Website", "State", "Subdistrict", "Town", "Village",
    "Timezone", "Insurance Companies", "Specialty", "Sub -Specialty",
]

# hospTypeCode -> Hospital Care Type
TYPE_NAME_MAP = {
    "G": "Public",
    "P": "Private (For Profit)",
    "N": "NABH Accredited",
    "D": "De-Empaneled",
}


def clean(v):
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("none", "null", "na", "-na-"):
        return ""
    return s


def load_lookups():
    specs = json.loads(HEM_SPECS.read_text(encoding="utf-8")) if HEM_SPECS.exists() else []
    spec_by_id: dict[str, str] = {}
    for s in specs:
        sid = clean(s.get("specialityid"))
        sname = clean(s.get("specialityname"))
        if sid and sname:
            spec_by_id[sid] = sname

    states_data = json.loads(HEM_STATES.read_text(encoding="utf-8")) if HEM_STATES.exists() else {}
    states = states_data.get("states", {})
    districts_by_state = states_data.get("districts", {})
    return spec_by_id, states, districts_by_state


def hem_to_row(h: dict, spec_by_id: dict[str, str]) -> dict[str, str]:
    """Map a single HEM row to the 37-column output schema."""
    spec_codes_raw = clean(h.get("specialityCode"))
    spec_names: list[str] = []
    if spec_codes_raw:
        for code in spec_codes_raw.split(","):
            code = code.strip()
            if not code:
                continue
            name = spec_by_id.get(code, "")
            spec_names.append(name if name else code)

    tcode = clean(h.get("hospTypeCode"))
    city = clean(h.get("hospCity"))
    addr = clean(h.get("hospAddress"))
    full_address = ", ".join(p for p in [addr, city] if p)

    row = {c: "" for c in COLUMNS}
    row["Hospital Name"] = clean(h.get("hospName"))
    row["Hospital ID (UUID)"] = clean(h.get("facilityId")) or clean(h.get("hospitalId"))
    # Accreditation
    acc = clean(h.get("accredited"))
    if acc:
        row["Accreditation"] = "NABH Accredited" if acc.upper() == "Y" else "Not Accredited"
    row["Address"] = full_address
    # Emergency Numbers / Ambulance Phone No / Bloodbank Phone No / Emergency Services /
    # Facilities / Foreign Pcare / Hospital Fax / Hospital Secondary Email /
    # Miscellaneous Facilities / Number of Beds / Doctors Available / Private Wards
    # — HEM does not expose these; left empty.
    row["Helpline"] = clean(h.get("hospContactNumber"))
    row["Hospital Care Type"] = TYPE_NAME_MAP.get(tcode, tcode)
    if tcode == "G":
        row["Hospital Category"] = "Government"
    elif tcode in ("P", "N"):
        row["Hospital Category"] = "Private"
    row["Hospital Primary Email"] = clean(h.get("hospEmailId"))
    row["Latitude"] = clean(h.get("hospLatitude"))
    row["Longitude"] = clean(h.get("hospLongitude"))
    row["Location"] = clean(h.get("hospAddress"))
    row["Mobile Number"] = clean(h.get("hospMobileNumber"))
    # Nodal Person Email
    np_email = clean(h.get("nodalOfficerEmailId")) or clean(h.get("nodalOfficerEmail"))
    row["Nodal Person Email"] = np_email
    row["Nodal Person Info"] = clean(h.get("nodalOfficerName"))
    row["Nodal Person Tele"] = clean(h.get("nodalOfficerNumber"))
    pin = clean(h.get("hospPin"))
    row["Pincode"] = pin
    row["Website"] = clean(h.get("hospWebsite"))
    row["State"] = clean(h.get("_stateName"))
    row["Subdistrict"] = clean(h.get("_districtName"))
    row["Town"] = city
    row["Village"] = ""
    row["Timezone"] = "Asia/Kolkata"
    row["Insurance Companies"] = clean(h.get("schemeCode"))
    row["Specialty"] = ", ".join(spec_names)
    row["Sub -Specialty"] = ""
    return row


def main():
    if not HEM_RAW.exists():
        print(f"Missing {HEM_RAW} — run scrape_hem_portal.py first")
        return

    print(f"Loading HEM raw data from {HEM_RAW.name} ...")
    hem = json.loads(HEM_RAW.read_text(encoding="utf-8"))
    print(f"  {len(hem)} HEM hospitals")

    spec_by_id, states, districts_by_state = load_lookups()
    print(f"  {len(spec_by_id)} speciality names, {len(states)} states, "
          f"{sum(len(d) for d in districts_by_state.values())} districts")

    rows: list[dict[str, str]] = []
    for hid, h in hem.items():
        rows.append(hem_to_row(h, spec_by_id))

    print(f"  total: {len(rows)} rows")

    with CSV_OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r.get(c, "") for c in COLUMNS])
    print(f"Wrote {CSV_OUT.name}")

    JSON_OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {JSON_OUT.name}")

    total = len(rows)
    print("\n--- Field coverage (37-column HEM CSV) ---")
    for col in COLUMNS:
        filled_n = sum(1 for r in rows if (r.get(col) or "").strip())
        print(f"  {col:35s} {filled_n:6d}/{total} ({100*filled_n/total:5.1f}%)")

    by_state: dict[str, int] = {}
    missing_state = 0
    missing_district = 0
    for r in rows:
        s = r.get("State", "") or "?"
        d = r.get("Subdistrict", "") or "?"
        by_state[s] = by_state.get(s, 0) + 1
        if not s or s == "?":
            missing_state += 1
        if not d or d == "?":
            missing_district += 1
    print(f"\nMissing state name: {missing_state}/{total}")
    print(f"Missing district name: {missing_district}/{total}")
    print("\n--- By state (top 10) ---")
    for s, n in sorted(by_state.items(), key=lambda x: -x[1])[:10]:
        print(f"  {s:40s} {n}")


if __name__ == "__main__":
    main()
