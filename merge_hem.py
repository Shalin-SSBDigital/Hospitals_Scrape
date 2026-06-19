"""
Merge HEM raw hospital data into hospitals.csv
==============================================

Reads:
  - hem_raw.json         (output of scrape_hem2.py: dict[hospitalId] -> HEM row)
  - hem_specialities.json (list of HEM speciality dicts)
  - hem_states.json      (state list + state-wise counts)
  - hospitals.csv         (existing 38-column PMJAY data)

Writes:
  - hospitals.csv         (updated, same 38 columns)
  - hospitals.json        (same)
  - hem_only.csv          (HEM hospitals that were NEW, not in PMJAY export)

The merge key is `Hospital ID (UUID)` (PMJAY) == `hospitalId` (HEM, numeric).
For matching rows: HEM data fills empty PMJAY cells.
For new rows: a fresh 38-column row is added with the HEM data mapped in.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
HEM_RAW = BASE_DIR / "hem_raw.json"
HEM_SPECS = BASE_DIR / "hem_specialities.json"
HEM_STATES = BASE_DIR / "hem_states.json"
CSV_IN = BASE_DIR / "hospitals.csv"
CSV_OUT = BASE_DIR / "hospitals.csv"
JSON_OUT = BASE_DIR / "hospitals.json"
HEM_ONLY = BASE_DIR / "hem_only.csv"

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

TYPE_CODE_MAP = {
    "G": "Public",
    "P": "Private (For Profit)",
    "N": "NABH Accredited",
    "D": "De-Empaneled",
}

ACCRED_MAP = {
    "Y": "NABH Accredited",
    "N": "Not Accredited",
}


def load_lookups():
    specs = json.loads(HEM_SPECS.read_text(encoding="utf-8")) if HEM_SPECS.exists() else []
    spec_by_id = {str(s.get("specialityid", "")).strip(): s.get("specialityname", "").strip()
                  for s in specs if s.get("specialityid")}

    states_data = json.loads(HEM_STATES.read_text(encoding="utf-8")) if HEM_STATES.exists() else {}
    state_map = states_data.get("states", {})  # name -> code
    code_to_name = {str(v): k for k, v in state_map.items()}  # code -> name

    return spec_by_id, code_to_name


def hem_to_csv_row(h: dict, spec_by_id: dict[str, str], code_to_name: dict[str, str]) -> dict[str, str]:
    row = {c: "" for c in COLUMNS}
    fid = h.get("facilityId") or str(h.get("hospitalId", ""))
    row["Hospital ID (UUID)"] = str(fid).strip()
    row["Hospital Name"] = (h.get("hospName") or "").strip()
    addr = (h.get("hospAddress") or "").strip()
    city = (h.get("hospCity") or "").strip()
    row["Address"] = ", ".join(p for p in [addr, city] if p)
    row["Pincode"] = str(h.get("hospPin") or "").strip()
    row["State"] = code_to_name.get(str(h.get("stateCode") or "").strip(), h.get("_stateName", ""))
    row["Town"] = city
    row["Latitude"] = str(h.get("hospLatitude") or "").strip()
    row["Longitude"] = str(h.get("hospLongitude") or "").strip()
    row["Mobile Number"] = str(h.get("hospMobileNumber") or "").strip()
    row["Hospital Primary Email"] = (h.get("hospEmailId") or "").strip()
    row["Website"] = (h.get("hospWebsite") or "").strip()
    row["Helpline"] = str(h.get("hospContactNumber") or "").strip()
    row["Nodal Person Info"] = (h.get("nodalOfficerName") or "").strip()
    row["Nodal Person Tele"] = str(h.get("nodalOfficerNumber") or "").strip()
    row["Accreditation"] = ACCRED_MAP.get(h.get("accredited"), str(h.get("accredited") or ""))
    tcode = h.get("hospTypeCode") or ""
    row["Hospital Care Type"] = TYPE_CODE_MAP.get(tcode, tcode)
    if tcode == "G":
        row["Hospital Category"] = "Government"
    elif tcode in ("P", "N"):
        row["Hospital Category"] = "Private"
    row["Specialities"] = (h.get("type") or "").strip()  # generic "Hospital"/"Diagnostic Centre"
    sp_codes = (h.get("specialityCode") or "").strip()
    if sp_codes:
        names = [spec_by_id.get(c.strip(), c.strip()) for c in sp_codes.split(",") if c.strip()]
        names = [n for n in names if n]
        if names:
            row["Specialities"] = ", ".join(names)
    sch = (h.get("schemeCode") or "").strip()
    if sch:
        row["Insurance Companies"] = sch
    row["Timezone"] = "Asia/Kolkata"
    return row


def main():
    if not HEM_RAW.exists():
        print(f"Missing {HEM_RAW} — run scrape_hem2.py first")
        return

    print(f"Loading HEM raw data from {HEM_RAW.name} ...")
    hem = json.loads(HEM_RAW.read_text(encoding="utf-8"))
    print(f"  {len(hem)} HEM hospitals")

    spec_by_id, code_to_name = load_lookups()
    print(f"  {len(spec_by_id)} specialities, {len(code_to_name)} state names")

    print(f"Loading existing {CSV_IN.name} ...")
    existing: list[dict[str, str]] = []
    with CSV_IN.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            existing.append(r)
    print(f"  {len(existing)} existing rows")

    # Index existing by UUID (PMJAY 'Hospital ID (UUID)' == HEM 'facilityId')
    by_uuid: dict[str, dict[str, str]] = {}
    for r in existing:
        uid = (r.get("Hospital ID (UUID)") or "").strip()
        if uid:
            by_uuid[uid] = r

    matched = 0
    filled = 0
    new_rows: list[dict[str, str]] = []
    for hid, h in hem.items():
        # Merge key: HEM's facilityId (e.g. HOSP27G25121970) == PMJAY's Hospital ID (UUID)
        merge_key = (h.get("facilityId") or "").strip() or str(hid)
        if merge_key in by_uuid:
            matched += 1
            # Fill empty cells from HEM — build the full HEM row once, then copy empties
            hem_row = hem_to_csv_row(h, spec_by_id, code_to_name)
            target = by_uuid[merge_key]
            for c in COLUMNS:
                cur = (target.get(c) or "").strip()
                if cur:
                    continue
                src = (hem_row.get(c) or "").strip()
                if src:
                    target[c] = src
                    filled += 1
        else:
            new_rows.append(hem_to_csv_row(h, spec_by_id, code_to_name))

    print(f"  matched {matched} existing rows; filled {filled} empty cells")
    print(f"  adding {len(new_rows)} new rows from HEM")

    # Re-number
    combined = existing + new_rows
    for i, r in enumerate(combined, start=1):
        r["Sr No"] = str(i)

    print(f"  total: {len(combined)} rows")

    with CSV_OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNS)
        for r in combined:
            w.writerow([(r.get(c) or "") for c in COLUMNS])
    print(f"Wrote {CSV_OUT.name}")

    JSON_OUT.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {JSON_OUT.name}")

    with HEM_ONLY.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNS)
        for r in new_rows:
            w.writerow([(r.get(c) or "") for c in COLUMNS])
    print(f"Wrote {HEM_ONLY.name} ({len(new_rows)} new rows)")

    # Coverage report
    total = len(combined)
    print("\n--- Field coverage after HEM merge ---")
    for col in COLUMNS:
        filled_n = sum(1 for r in combined if (r.get(col) or "").strip())
        print(f"  {col:40s} {filled_n:6d}/{total} ({100*filled_n/total:5.1f}%)")


if __name__ == "__main__":
    main()
