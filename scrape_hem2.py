"""
HEM (Hospital Empanelment Module) Hospital Scraper
==================================================

Data source: https://hem.nha.gov.in (NHA Hospital Empanelment Module)
  - Public listing endpoint: POST /hem/external/hospital/list
    Base URL: https://apisprod.nha.gov.in/pmjay/prodhem
    Body: {"facilityName":"","pageNo":1,"size":10,"card":"hosp_state_code","value":"28","pincode":""}
    Returns paginated Spring-style JSON with `content[]` of 42 fields per hospital.
  - Specialities lookup: POST /hem/hbp/get/specialities/list
    Body: {"status":"Active"}  -> 74 active specialities (id, code, name)
  - State list: GET /ump/ump/fetch/statelist  (on prodump host)
  - State-wise hospital counts: GET /hem/external/profile/getHospitalCountByStateWise
  - Per-hospital profile: POST /hem/external/hospital/profile  (body: {"hospInfoId": <id>})

Card values:  G = Government, P = Private, N = NABH Accredited, D = De-Empaneled
Cards:        hosp_type_code, hosp_state_code, hosp_district_code, hosp_speciality_code,
              hosp_scheme_code, hosp_deempanled_code

The output is a raw JSON file (hem_raw.json) keyed by `hospitalId` (numeric).
A separate build step (`merge_hem.py`) folds this into hospitals.csv matching the
existing 38-column schema.
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "run.log"
RAW_OUT = BASE_DIR / "hem_raw.json"
SPEC_OUT = BASE_DIR / "hem_specialities.json"
STATES_OUT = BASE_DIR / "hem_states.json"

API_BASE = "https://apisprod.nha.gov.in/pmjay/prodhem"
UMP_BASE = "https://apisprod.nha.gov.in/pmjay/prodump"

PAGE_SIZE = 30
SLEEP = 0.05
SAVE_EVERY = 20
MAX_RETRIES = 3
TIMEOUT = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://hem.nha.gov.in/",
    "Origin": "https://hem.nha.gov.in",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] [hem] {msg}"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def post_json(session: requests.Session, url: str, payload: dict) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            r = session.post(url, json=payload, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            log(f"  POST {url} -> {r.status_code} attempt {attempt+1}")
        except Exception as e:
            log(f"  POST {url} err: {e} attempt {attempt+1}")
        time.sleep(2 + attempt * 2)
    return None


def get_json(session: requests.Session, url: str) -> Any:
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            log(f"  GET {url} -> {r.status_code} attempt {attempt+1}")
        except Exception as e:
            log(f"  GET {url} err: {e} attempt {attempt+1}")
        time.sleep(2 + attempt * 2)
    return None


def fetch_state_list(session: requests.Session) -> dict[str, str]:
    data = get_json(session, f"{UMP_BASE}/ump/ump/fetch/statelist")
    if not data:
        return {}
    return data.get("StateList", {})


def fetch_specialities(session: requests.Session) -> list[dict]:
    data = post_json(session, f"{API_BASE}/hem/hbp/get/specialities/list", {"status": "Active"})
    return data or []


def fetch_state_counts(session: requests.Session) -> dict[str, dict]:
    return get_json(session, f"{API_BASE}/hem/external/profile/getHospitalCountByStateWise") or {}


def fetch_all_hospitals(session: requests.Session, type_filter: str | None = None,
                         on_page=None) -> list[dict]:
    """HEM's public list endpoint only filters by `hosp_type_code` (G/P) and name/pincode.
    State/district/speciality cards return the full 37k set, so we just paginate the full list.
    type_filter: 'G', 'P', or None for all.
    on_page: callback(page_no, total_pages, total_so_far) called after each page."""
    out: list[dict] = []
    page = 1
    if type_filter:
        payload_base = {
            "facilityName": "", "size": PAGE_SIZE,
            "card": "hosp_type_code", "value": type_filter, "pincode": "",
        }
    else:
        payload_base = {
            "facilityName": "", "size": PAGE_SIZE,
            "card": "", "value": "", "pincode": "",
        }
    total_pages_seen = 0
    while True:
        payload = {**payload_base, "pageNo": page}
        data = post_json(session, f"{API_BASE}/hem/external/hospital/list", payload)
        if not data:
            log(f"  failed at page {page}, stopping")
            break
        content = data.get("content", [])
        out.extend(content)
        if total_pages_seen == 0:
            total_pages_seen = data.get("totalPages", 0)
            total_elements = data.get("totalElements", 0)
            log(f"  starting pagination: {total_elements} hospitals across {total_pages_seen} pages")
        if on_page:
            on_page(page, total_pages_seen, len(out), out)
        if data.get("last") or not content:
            break
        page += 1
        time.sleep(SLEEP)
    return out


def main() -> None:
    LOG_FILE.touch(exist_ok=True)
    log("=" * 60)
    log("HEM hospital scraper starting")

    s = requests.Session()

    log("Fetching state list ...")
    states = fetch_state_list(s)
    log(f"  {len(states)} states (incl. CAPF/CGHS)")

    log("Fetching specialities ...")
    specs = fetch_specialities(s)
    log(f"  {len(specs)} active specialities")
    SPEC_OUT.write_text(json.dumps(specs, ensure_ascii=False, indent=2), encoding="utf-8")

    log("Fetching state-wise counts ...")
    counts = fetch_state_counts(s)
    log(f"  {len(counts)} state counts")

    STATES_OUT.write_text(json.dumps({"states": states, "counts": counts}, ensure_ascii=False, indent=2), encoding="utf-8")

    # The HEM public list endpoint only filters by hosp_type_code (G/P) server-side.
    # State/district filters return the full set, so we paginate once with no filter
    # and label the state from the response itself.
    SKIP = {"CAPF", "CGHS", "ESIC", "PSU", "NHCP", "NHCP - PSU", "PVT", "Pvt"}
    code_to_name = {str(v): k for k, v in states.items()}
    real_state_codes = {
        code for name, code in states.items()
        if name.upper() not in {x.upper() for x in SKIP}
    }
    log(f"Real state codes: {sorted(real_state_codes, key=int)}")

    all_hospitals: dict[str, dict] = {}
    log("Fetching all hospitals (no type filter) ...")
    last_save = [0]

    def on_page(page_no, total_pages, total_so_far, out_rows):
        # Add state labels in real time
        for h in out_rows[last_save[0] * PAGE_SIZE:]:
            sc = str(h.get("stateCode", ""))
            h["_stateName"] = code_to_name.get(sc, "")
        if page_no - last_save[0] >= SAVE_EVERY or page_no == 1 or page_no == total_pages:
            log(f"  page {page_no}/{total_pages}, {total_so_far} so far — saving partial")
            tmp = {str(h.get("hospitalId", "")): h for h in out_rows if h.get("hospitalId")}
            tmp_path = RAW_OUT.with_suffix(".json.partial")
            tmp_path.write_text(json.dumps(tmp, ensure_ascii=False, indent=2), encoding="utf-8")
            last_save[0] = page_no

    rows = fetch_all_hospitals(s, type_filter=None, on_page=on_page)
    log(f"  fetched {len(rows)} total")
    for h in rows:
        hid = str(h.get("hospitalId", ""))
        if not hid:
            continue
        sc = str(h.get("stateCode", ""))
        h["_stateName"] = code_to_name.get(sc, "")
        all_hospitals[hid] = h
    log(f"  unique: {len(all_hospitals)}")

    # Save final
    RAW_OUT.write_text(json.dumps(all_hospitals, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Wrote {RAW_OUT.name} ({len(all_hospitals)} hospitals)")

    # Coverage by state
    by_state: dict[str, int] = {}
    for h in all_hospitals.values():
        sn = h.get("_stateName", "?") or "?"
        by_state[sn] = by_state.get(sn, 0) + 1
    log("By state:")
    for sn, n in sorted(by_state.items(), key=lambda x: -x[1]):
        log(f"  {sn:40s} {n}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Interrupted.")
    except Exception as e:
        log(f"FATAL: {e}")
        raise
