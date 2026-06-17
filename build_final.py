"""
Build final hospitals.csv + hospitals.json
==========================================
Reads existing hospitals.csv (34k+ rows from PMJAY export + enrichment),
expands Specialities & Sub-Specialty codes to full names,
ensures all 38 columns are present, and writes clean CSV + JSON.
"""
import csv
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CSV_IN = BASE_DIR / "hospitals.csv"
CSV_OUT = BASE_DIR / "hospitals.csv"
JSON_OUT = BASE_DIR / "hospitals.json"
SPEC_LOOKUP = BASE_DIR / "specialities_lookup.csv"
SUBSPEC_LOOKUP = BASE_DIR / "sub_specialties_lookup.csv"

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


def load_lookup(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("Code", "").strip()
            full = row.get("FullForm", "").strip()
            if code:
                mapping[code] = full if full else code
    return mapping


def expand_codes(value: str, mapping: dict[str, str], fallback: dict[str, str] | None = None) -> str:
    if not value or value.strip().upper() in ("NA", "-NA-", ""):
        return ""
    parts = [p.strip() for p in value.replace(",", "|").replace(";", "|").split("|") if p.strip()]
    expanded = []
    for p in parts:
        upper = p.strip().upper()
        if upper in mapping:
            expanded.append(mapping[upper])
        elif p.strip() in mapping:
            expanded.append(mapping[p.strip()])
        elif fallback and upper in fallback:
            expanded.append(fallback[upper])
        elif fallback and p.strip() in fallback:
            expanded.append(fallback[p.strip()])
        else:
            expanded.append(p.strip())
    seen = set()
    deduped = []
    for e in expanded:
        if e not in seen:
            seen.add(e)
            deduped.append(e)
    return ", ".join(deduped) if deduped else ""


def clean_row(row: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for col in COLUMNS:
        val = row.get(col, "")
        if isinstance(val, str):
            val = val.strip()
        if val in ("NA", "-NA-", "None", "none", "null"):
            val = ""
        out[col] = val
    if not out.get("Timezone"):
        out["Timezone"] = "Asia/Kolkata"
    return out


def main():
    spec_map = load_lookup(SPEC_LOOKUP)
    subspec_map = load_lookup(SUBSPEC_LOOKUP)
    print(f"Loaded {len(spec_map)} speciality codes, {len(subspec_map)} sub-specialty codes")

    rows: list[dict[str, str]] = []
    with CSV_IN.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    print(f"Loaded {len(rows)} rows from {CSV_IN.name}")

    sp_expanded = 0
    sub_expanded = 0
    for r in rows:
        old_sp = r.get("Specialities", "")
        new_sp = expand_codes(old_sp, spec_map)
        if new_sp != old_sp:
            r["Specialities"] = new_sp
            sp_expanded += 1
        old_sub = r.get("Sub -Specialty", "")
        new_sub = expand_codes(old_sub, subspec_map, fallback=spec_map)
        if new_sub != old_sub:
            r["Sub -Specialty"] = new_sub
            sub_expanded += 1

    print(f"Expanded {sp_expanded} Specialities, {sub_expanded} Sub-Specialty cells")

    cleaned: list[dict[str, str]] = []
    for i, r in enumerate(rows, start=1):
        r["Sr No"] = str(i)
        c = clean_row(r)
        cleaned.append(c)

    print(f"Cleaned {len(cleaned)} rows")

    with CSV_OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNS)
        for r in cleaned:
            w.writerow([r.get(c, "") for c in COLUMNS])
    print(f"Wrote {CSV_OUT.name}")

    with JSON_OUT.open("w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
    print(f"Wrote {JSON_OUT.name}")

    print("\n--- Field coverage ---")
    total = len(cleaned)
    for col in COLUMNS:
        filled = sum(1 for r in cleaned if r.get(col, "").strip())
        print(f"  {col:40s} {filled:6d}/{total} ({100*filled/total:5.1f}%)")
    print(f"\nTotal hospitals: {total}")


if __name__ == "__main__":
    main()