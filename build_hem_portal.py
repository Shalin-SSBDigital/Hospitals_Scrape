"""
Build hospitals_hem.csv with HEM portal's exact 24-column format
================================================================

Columns (exact order, exactly as specified):
  Hospital Id, Facility Id, Hosp Name, Hospital Type Name, Hosp Type Code,
  State Name, State Code, District Name, District Code, Hosp Address,
  Hosp Mobile Number, Hosp Contact Number, Speciality Name, Speciality Code,
  Type, Empaneled Date, Establishment Year, Deempanel Status, Gc Status,
  Enrl Status, Hosp Rating, Hosp Latitude, Hosp Longitude,
  Created Date, Updated Date

Reads:
  - hem_raw.json          (output of scrape_hem_portal.py: dict[hospitalId] -> HEM row)
  - hem_specialities.json (HEM speciality list, id -> name)
  - hem_states.json       (state list + district list per state)

Writes:
  - hospitals_hem.csv     (24 columns, ~36k rows)
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

# EXACT column order
COLUMNS = [
    "Hospital Id", "Facility Id", "Hosp Name", "Hospital Type Name", "Hosp Type Code",
    "State Name", "State Code", "District Name", "District Code", "Hosp Address",
    "Hosp Mobile Number", "Hosp Contact Number", "Speciality Name", "Speciality Code",
    "Type", "Empaneled Date", "Establishment Year", "Deempanel Status", "Gc Status",
    "Enrl Status", "Hosp Rating", "Hosp Latitude", "Hosp Longitude",
    "Created Date", "Updated Date",
]

# hospTypeCode -> Hospital Type Name
TYPE_NAME_MAP = {
    "G": "Public",
    "P": "Private",
    "N": "NABH Accredited",
    "D": "De-Empaneled",
}


def clean(v):
    """Normalize null-like values to empty string."""
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
    """Map a single HEM row to the 24-column output schema."""
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
    row = {
        "Hospital Id": clean(h.get("hospitalId")),
        "Facility Id": clean(h.get("facilityId")),
        "Hosp Name": clean(h.get("hospName")),
        "Hospital Type Name": TYPE_NAME_MAP.get(tcode, tcode),
        "Hosp Type Code": tcode,
        "State Name": clean(h.get("_stateName")) or clean(h.get("stateName")),
        "State Code": clean(h.get("stateCode")),
        "District Name": clean(h.get("_districtName")) or clean(h.get("districtName")),
        "District Code": clean(h.get("districtCode")),
        "Hosp Address": clean(h.get("hospAddress")),
        "Hosp Mobile Number": clean(h.get("hospMobileNumber")),
        "Hosp Contact Number": clean(h.get("hospContactNumber")),
        "Speciality Name": ", ".join(spec_names),
        "Speciality Code": spec_codes_raw,
        "Type": clean(h.get("type")),
        "Empaneled Date": clean(h.get("empaneledDate")),
        "Establishment Year": clean(h.get("establishmentYear")),
        "Deempanel Status": clean(h.get("deempanelStatus")),
        "Gc Status": clean(h.get("gcStatus")),
        "Enrl Status": clean(h.get("enrlStatus")),
        "Hosp Rating": clean(h.get("hospRating")),
        "Hosp Latitude": clean(h.get("hospLatitude")),
        "Hosp Longitude": clean(h.get("hospLongitude")),
        "Created Date": clean(h.get("createdDate")),
        "Updated Date": clean(h.get("updatedDate")),
    }
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
    print("\n--- Field coverage (24-column HEM CSV) ---")
    for col in COLUMNS:
        filled_n = sum(1 for r in rows if (r.get(col) or "").strip())
        print(f"  {col:25s} {filled_n:6d}/{total} ({100*filled_n/total:5.1f}%)")

    by_state: dict[str, int] = {}
    missing_state = 0
    missing_district = 0
    for r in rows:
        s = r.get("State Name", "") or "?"
        d = r.get("District Name", "") or "?"
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
