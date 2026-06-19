"""
Fast fetcher for the 8 000+ hospitals whose Specialities came back empty in the
first run of fetch_specialities.py.

The first run failed because it never bootstrapped the F5 load-balancer session
cookie (it just hit the endpoint directly and got 403 "Access Forbidden" pages).
This script does a single GET to /Search/ to capture the cookies, then fans out
GET requests to empnlWorkFlow.htm?actionFlag=spclityServicesDetails&hospInfoId=…
in parallel.

Output
------
* Updates `specialities_fetch_progress.json` (re-uses any non-empty cached value)
* Updates `hospitals.csv` and `hospitals.json` in place (writes to a .tmp file
  first then atomically renames)
* Writes a run log to `run.log`

Usage
-----
    python3 fetch_specialities_fast.py            # default 10 workers
    python3 fetch_specialities_fast.py --workers 25
    python3 fetch_specialities_fast.py --limit 200 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
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

# --- the two endpoints we care about ---
BOOTSTRAP_URL = "https://hospitals.pmjay.gov.in/Search"
SPEC_URL = "https://hospitals.pmjay.gov.in/Search/empnlWorkFlow.htm"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://hospitals.pmjay.gov.in/Search/",
    "Connection": "keep-alive",
}

RE_HOSP = re.compile(r'<input[^>]*id="hosp(\w+)"[^>]*checked')
RE_EMP  = re.compile(r'<input[^>]*id="emp(\w+)"[^>]*checked')
RE_UP   = re.compile(r'<input[^>]*id="upEmp(\w+)"[^>]*checked')

# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] [fast-spec] {msg}"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def bootstrap_session() -> requests.Session:
    """Hit /Search/ once to capture the F5 + APP_encrypted cookies.

    The 302 redirect goes to http://, but the server rejects plain http on
    /Search/ with 502. We follow the redirect manually and force https.
    """
    s = requests.Session()
    s.headers.update(HEADERS)
    log("Bootstrapping session cookie from /Search/ …")
    r = s.get(BOOTSTRAP_URL, allow_redirects=False, timeout=30)
    r.raise_for_status()
    # r is the 302; manually GET the https version of the location
    loc = r.headers.get("Location", "")
    if loc.startswith("http://"):
        loc = "https://" + loc[len("http://"):]
    elif not loc:
        loc = "https://hospitals.pmjay.gov.in/Search/"
    r2 = s.get(loc, allow_redirects=True, timeout=30)
    r2.raise_for_status()
    cookies = list(s.cookies)
    log(f"  cookies acquired: {[c.name for c in cookies]}")
    # Sanity check — the spclityServicesDetails endpoint should now return real data
    test = s.get(SPEC_URL, params={"actionFlag": "spclityServicesDetails",
                                    "hospInfoId": "HOSP24P132969",
                                    "appReadOnly": "Y"}, timeout=30)
    log(f"  sanity GET size={len(test.text)} checked-hosp={len(RE_HOSP.findall(test.text))}")
    if len(test.text) < 5000 or "Access Forbidden" in test.text[:500]:
        raise RuntimeError("Bootstrap failed — endpoint still 403. Aborting.")
    return s


def parse_codes(html: str) -> list[str]:
    """Extract all checked speciality codes (applied + empanelled + upgraded)."""
    if "Access Forbidden" in html[:600] or len(html) < 5000:
        return []
    codes = set()
    codes.update(RE_HOSP.findall(html))
    codes.update(RE_EMP.findall(html))
    codes.update(RE_UP.findall(html))
    return sorted(codes)


def fetch_one(session_factory, hid: str) -> tuple[str, list[str], str]:
    """Fetch one hospital. Returns (hid, codes, status) where status is
    'ok' / 'empty' / 'forbidden' / 'error'."""
    try:
        s = session_factory()
        r = s.get(SPEC_URL, params={"actionFlag": "spclityServicesDetails",
                                    "hospInfoId": hid,
                                    "appReadOnly": "Y"}, timeout=30)
        if "Access Forbidden" in r.text[:600]:
            return hid, [], "forbidden"
        codes = parse_codes(r.text)
        if codes:
            return hid, codes, "ok"
        return hid, [], "empty"
    except Exception as e:
        return hid, [], f"error:{type(e).__name__}"


# How many consecutive 403s before re-bootstrapping the session
REBOOTSTRAP_AFTER = 25


# ---------------------------------------------------------------------------
def load_lookup() -> dict[str, str]:
    mapping: dict[str, str] = {}
    with SPEC_LOOKUP.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row["Code"].strip()
            full = row["FullForm"].strip()
            if code:
                mapping[code] = full if full else code
    # keep parity with the original script
    mapping["US"] = "US-Unspecified Surgical Package"
    mapping["S18"] = "S18-Not Available"
    return mapping


def expand_codes(codes: list[str], mapping: dict[str, str]) -> str:
    if not codes:
        return ""
    return ", ".join(mapping.get(c, f"{c}-{c}") for c in sorted(set(codes)))


def load_rows() -> list[dict[str, str]]:
    with CSV_FILE.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_progress() -> dict[str, list[str]]:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_progress(p: dict[str, list[str]]) -> None:
    tmp = PROGRESS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PROGRESS_FILE)


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=10, help="concurrent threads (default 10)")
    ap.add_argument("--batch",   type=int, default=200, help="save every N rows")
    ap.add_argument("--limit",   type=int, default=0,   help="only fetch this many (for testing)")
    ap.add_argument("--dry-run", action="store_true",  help="don't write back to hospitals.csv/json")
    args = ap.parse_args()

    LOG_FILE.touch(exist_ok=True)
    log(f"=== START (workers={args.workers}, batch={args.batch}, limit={args.limit}, dry={args.dry_run}) ===")

    # 1) bootstrap session (master session used to seed the per-thread sessions)
    master = bootstrap_session()

    # 2) Load existing data
    rows = load_rows()
    log(f"Loaded {len(rows)} rows from {CSV_FILE.name}")
    progress = load_progress()
    log(f"Progress cache: {len(progress)} entries "
        f"({sum(1 for v in progress.values() if v)} non-empty)")

    spec_map = load_lookup()
    log(f"Loaded {len(spec_map)} speciality codes")

    # 3) Decide what to fetch — only rows with empty Specialities in CSV
    # AND no successful cache entry.
    todo: list[tuple[int, str]] = []
    for i, row in enumerate(rows):
        hid = (row.get("Hospital ID (UUID)") or "").strip()
        if not hid:
            continue
        if row.get("Specialities", "").strip():
            continue        # already filled in CSV
        cached = progress.get(hid)
        if cached:          # already in cache with values
            continue
        todo.append((i, hid))
    log(f"Hospitals to fetch: {len(todo)}")
    if args.limit:
        todo = todo[:args.limit]
        log(f"  limited to {len(todo)} (--limit)")

    if not todo:
        log("Nothing to do.")
        return

    # 4) Per-thread session factory — each thread clones cookies from master
    def factory():
        s = requests.Session()
        s.headers.update(HEADERS)
        s.cookies.update(master.cookies)
        return s

    # 5) Parallel fetch
    completed = 0
    errors = 0
    forbidden_hits = 0
    consecutive_forbidden = 0
    fetched: dict[str, list[str]] = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_one, factory, hid): (i, hid) for i, hid in todo}
        for fut in as_completed(futs):
            i, hid = futs[fut]
            try:
                _hid, codes, status = fut.result()
            except Exception as e:
                _hid, codes, status = hid, [], f"error:{type(e).__name__}"
            if status == "ok":
                fetched[hid] = codes
                progress[hid] = codes
                consecutive_forbidden = 0
            elif status == "empty":
                progress[hid] = []   # legitimately empty hospital
                consecutive_forbidden = 0
            elif status == "forbidden":
                forbidden_hits += 1
                consecutive_forbidden += 1
                # do NOT cache; we want to retry these next run
                if consecutive_forbidden >= REBOOTSTRAP_AFTER:
                    log(f"  re-bootstrapping session after {consecutive_forbidden} consecutive 403s")
                    master = bootstrap_session()
                    consecutive_forbidden = 0
            else:
                errors += 1
                consecutive_forbidden = 0
                progress[hid] = []

            completed += 1
            if completed % args.batch == 0 or completed == len(todo):
                elapsed = time.time() - t0
                rate = completed / max(1, elapsed)
                remaining = (len(todo) - completed) / max(0.1, rate)
                log(f"  {completed}/{len(todo)} done  "
                    f"ok={len(fetched)} empty={sum(1 for v in progress.values() if not v)} "
                    f"forbidden={forbidden_hits} errors={errors}  "
                    f"{rate:.1f}/s  ETA {remaining/60:.0f} min")
                save_progress(progress)

    save_progress(progress)
    log(f"Fetch phase done in {(time.time()-t0)/60:.1f} min. "
        f"ok={len(fetched)} forbidden={forbidden_hits} errors={errors}")

    if args.dry_run:
        log("Dry-run — not writing hospitals.csv/json.")
        # still show a preview of the first few
        for hid, codes in list(fetched.items())[:5]:
            log(f"  {hid}: {expand_codes(codes, spec_map)}")
        return

    # 6) Apply back to rows
    applied = recovered = updated = 0
    for row in rows:
        hid = (row.get("Hospital ID (UUID)") or "").strip()
        if hid not in fetched:
            continue
        new_spec = expand_codes(fetched[hid], spec_map)
        old_spec = (row.get("Specialities") or "").strip()
        if new_spec and new_spec != old_spec:
            row["Specialities"] = new_spec
            applied += 1
            if not old_spec:
                recovered += 1
            else:
                updated += 1

    for i, r in enumerate(rows, start=1):
        r["Sr No"] = str(i)

    # 7) Atomic write
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
    log(f"After: filled={filled_after}  empty={empty_after}  "
        f"coverage={100*filled_after/len(rows):.1f}%")
    log(f"Applied {applied} rows ({recovered} recovered, {updated} updated).")
    log("=== DONE ===")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Interrupted — progress saved.")
    except Exception as e:
        log(f"FATAL: {e}")
        raise
