"""Restore the unfiltered 34,123-row CSV from valid + rejected files."""
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "hospitals.csv"
JSON_FILE = BASE_DIR / "hospitals.json"
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


def main():
    with CSV_FILE.open(encoding="utf-8") as f:
        valid = list(csv.DictReader(f))
    with REJECTED_CSV.open(encoding="utf-8") as f:
        rejected = list(csv.DictReader(f))

    # Drop the __reasons__ column from rejected
    for r in rejected:
        r.pop("__reasons__", None)

    all_rows = valid + rejected
    print(f"Combined: {len(all_rows)} rows (valid={len(valid)}, rejected={len(rejected)})")

    # Re-number
    for i, r in enumerate(all_rows, start=1):
        r["Sr No"] = str(i)

    # Write
    tmp = CSV_FILE.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNS)
        for r in all_rows:
            w.writerow([r.get(c, "") for c in COLUMNS])
    tmp.replace(CSV_FILE)

    import json
    tmp_json = JSON_FILE.with_suffix(".json.tmp")
    tmp_json.write_text(json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_json.replace(JSON_FILE)

    print(f"Restored: {CSV_FILE.name}, {JSON_FILE.name}")


if __name__ == "__main__":
    main()
