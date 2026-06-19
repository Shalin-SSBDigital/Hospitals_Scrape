"""
Build hospitals_hem.csv from HEM raw data
=========================================

Reads hem_raw.json (output of scrape_hem2.py) and writes a fresh 38-column CSV
containing ALL 36k+ HEM hospitals — no merge with the existing PMJAY data.

This is a separate output file: hospitals_hem.csv
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
    state_map = states_data.get("states", {})
    code_to_name = {str(v): k for k, v in state_map.items()}

    return spec_by_id, code_to_name


def hem_to_csv_row(h: dict, spec_by_id: dict[str, str], code_to_name: dict[str, str]) -> dict[str, str]:
    row = {c: "" for c in COLUMNS}
    fid = h.get("facilityId") or str(h.get("hospitalId", ""))
    row["Hospital ID (UUID)"] = str(fid).strip()
    row["Hospital Name"] = (h.get("hospName") or "").strip()
    addr = (h.get("hospAddress") or "").strip()
    city = (h.get("hospCity") or "").strip()
    row["Address"] = ", ".join(p for p in [addr, city] if p)
    pin = h.get("hospPin")
    if pin is not None and str(pin).strip() and str(pin).strip().lower() != "none":
        row["Pincode"] = str(pin).strip()
    row["State"] = code_to_name.get(str(h.get("stateCode") or "").strip(), h.get("_stateName", ""))
    row["Town"] = city
    lat = h.get("hospLatitude")
    if lat is not None and str(lat).strip() and str(lat).strip().lower() != "none":
        row["Latitude"] = str(lat).strip()
    lon = h.get("hospLongitude")
    if lon is not None and str(lon).strip() and str(lon).strip().lower() != "none":
        row["Longitude"] = str(lon).strip()
    mob = h.get("hospMobileNumber")
    if mob is not None and str(mob).strip() and str(mob).strip().lower() != "none":
        row["Mobile Number"] = str(mob).strip()
    email = h.get("hospEmailId")
    if email and str(email).strip().lower() != "none":
        row["Hospital Primary Email"] = str(email).strip()
    web = h.get("hospWebsite")
    if web and str(web).strip().lower() != "none":
        row["Website"] = str(web).strip()
    contact = h.get("hospContactNumber")
    if contact is not None and str(contact).strip() and str(contact).strip().lower() != "none":
        row["Helpline"] = str(contact).strip()
    nn = h.get("nodalOfficerName")
    if nn and str(nn).strip().lower() != "none":
        row["Nodal Person Info"] = str(nn).strip()
    nt = h.get("nodalOfficerNumber")
    if nt is not None and str(nt).strip() and str(nt).strip().lower() != "none":
        row["Nodal Person Tele"] = str(nt).strip()
    acc = h.get("accredited")
    if acc and str(acc).strip().lower() != "none":
        row["Accreditation"] = ACCRED_MAP.get(str(acc).strip(), str(acc).strip())
    tcode = h.get("hospTypeCode") or ""
    row["Hospital Care Type"] = TYPE_CODE_MAP.get(tcode, tcode)
    if tcode == "G":
        row["Hospital Category"] = "Government"
    elif tcode in ("P", "N"):
        row["Hospital Category"] = "Private"
    sp_codes = (h.get("specialityCode") or "").strip()
    if sp_codes and sp_codes.lower() != "none":
        names = [spec_by_id.get(c.strip(), c.strip()) for c in sp_codes.split(",") if c.strip()]
        names = [n for n in names if n]
        if names:
            row["Specialities"] = ", ".join(names)
    sch = h.get("schemeCode")
    if sch and str(sch).strip().lower() != "none":
        row["Insurance Companies"] = str(sch).strip()
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

    rows: list[dict[str, str]] = []
    for hid, h in hem.items():
        rows.append(hem_to_csv_row(h, spec_by_id, code_to_name))

    for i, r in enumerate(rows, start=1):
        r["Sr No"] = str(i)

    print(f"  total: {len(rows)} rows")

    with CSV_OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([(r.get(c) or "") for c in COLUMNS])
    print(f"Wrote {CSV_OUT.name}")

    JSON_OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {JSON_OUT.name}")

    total = len(rows)
    print("\n--- Field coverage (HEM-only CSV) ---")
    for col in COLUMNS:
        filled_n = sum(1 for r in rows if (r.get(col) or "").strip())
        print(f"  {col:40s} {filled_n:6d}/{total} ({100*filled_n/total:5.1f}%)")

    # By state
    by_state: dict[str, int] = {}
    for r in rows:
        s = r.get("State", "") or "?"
        by_state[s] = by_state.get(s, 0) + 1
    print("\n--- By state ---")
    for s, n in sorted(by_state.items(), key=lambda x: -x[1]):
        print(f"  {s:40s} {n}")


if __name__ == "__main__":
    main()
