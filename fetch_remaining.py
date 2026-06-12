"""
Simple sequential fetcher - just for the remaining 6,123 hospitals.
Writes progress every 50.
"""
import csv, json, time, re, sys
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "hospitals.csv"
JSON_FILE = BASE_DIR / "hospitals.json"
PROGRESS_FILE = BASE_DIR / "enrich_progress.json"
NEW_CSV = BASE_DIR / "_hospitals_seq.csv"
NEW_JSON = BASE_DIR / "_hospitals_seq.json"

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

URL = "https://hospitals.pmjay.gov.in/Search/empnlWorkFlow.htm"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def extract(body):
    body = re.sub(r"<script.*?</script>", " ", body, flags=re.DOTALL|re.IGNORECASE)
    body = re.sub(r"<style.*?</style>", " ", body, flags=re.DOTALL|re.IGNORECASE)
    out = {}
    for m in re.finditer(
        r'<div[^>]*form-group[^>]*>\s*<label[^>]*>\s*([^<:]+?)\s*:?\s*</label>\s*<br\s*/?>\s*([^<]*)',
        body, re.IGNORECASE|re.DOTALL
    ):
        label = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(":").strip()
        val = re.sub(r"\s+", " ", m.group(2)).strip()
        if val and val not in ("NA", "-NA-", "NA "):
            out[label] = val
    return out


def main():
    print(f"[{time.strftime('%H:%M:%S')}] Loading cache...", flush=True)
    with PROGRESS_FILE.open(encoding="utf-8") as f:
        p = json.load(f)
    done = p.get("done", {})
    print(f"[{time.strftime('%H:%M:%S')}] Cache: {len(done)} entries", flush=True)

    print(f"[{time.strftime('%H:%M:%S')}] Loading rows...", flush=True)
    with CSV_FILE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"[{time.strftime('%H:%M:%S')}] Rows: {len(rows)}", flush=True)

    # Find uncached hids
    todo = []
    for r in rows:
        hid = r.get("Hospital ID (UUID)", "")
        if hid and hid not in done:
            todo.append(hid)
    print(f"[{time.strftime('%H:%M:%S')}] TODO: {len(todo)}", flush=True)

    s = requests.Session()
    s.headers.update(HEADERS)

    t0 = time.time()
    completed = 0
    for hid in todo:
        for attempt in range(3):
            try:
                r = s.post(URL, params={"actionFlag": "hospBasicDtlsWrkflw", "hospInfoId": hid}, timeout=20)
                if r.status_code == 200:
                    data = extract(r.text)
                    data["__done__"] = True
                    done[hid] = data
                    completed += 1
                    break
            except Exception as e:
                print(f"  {hid} attempt {attempt+1}: {e}", flush=True)
                time.sleep(2)
        if completed % 100 == 0:
            elapsed = time.time() - t0
            rate = completed / max(1, elapsed)
            remaining = (len(todo) - completed) / max(0.1, rate)
            print(f"[{time.strftime('%H:%M:%S')}] {completed}/{len(todo)} done, {rate:.1f}/s, ETA {remaining/60:.0f} min", flush=True)
            p["done"] = done
            PROGRESS_FILE.write_text(json.dumps(p), encoding="utf-8")

    p["done"] = done
    PROGRESS_FILE.write_text(json.dumps(p), encoding="utf-8")
    print(f"[{time.strftime('%H:%M:%S')}] Done. {completed} fetched in {(time.time()-t0)/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
