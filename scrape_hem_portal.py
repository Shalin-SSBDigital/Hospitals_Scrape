"""
HEM Portal (Hospital Empanelment Module) Hospital Scraper
=========================================================

Data source: https://hem.nha.gov.in (NHA Hospital Empanelment Module)
API:        https://apisprod.nha.gov.in/pmjay/prodhem

Per-state pagination (using `stateCode` in body — the only filter that works):
  POST /hem/external/hospital/list
  body: {"stateCode": "<code>", "facilityName": "", "pageNo": 1, "size": 30,
         "card": "", "value": "", "pincode": ""}

District name lookup:
  POST https://apisprod.nha.gov.in/pmjay/prodump/ump/ump/state/getDistrictCodeList
  body: {"stateCode": "<code>"}  ->  {"DISTRICT NAME": <code>, ...}

State list:
  GET  https://apisprod.nha.gov.in/pmjay/prodump/ump/ump/fetch/statelist
  ->   {"StateList": {"NAME": "<code>", ...}}

Specialities (HEM IDs):
  POST /hem/hbp/get/specialities/list
  body: {"status": "Active"}  ->  74 active specialities

Output: hem_raw.json keyed by hospitalId (numeric). State and district names
are added client-side from the lookups above.

Run time: ~30 minutes for all 36 states.
"""

from __future__ import annotations

import json
import time
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
SLEEP = 0.2
MAX_RETRIES = 4
TIMEOUT = 30
SAVE_EVERY_PAGES = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://hem.nha.gov.in/",
    "Origin": "https://hem.nha.gov.in",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# States we don't scrape (scheme aggregates, not real states)
SKIP_STATES = {"CAPF", "CGHS", "ESIC", "PSU", "NHCP", "NHCP - PSU", "PVT", "Pvt"}


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
        time.sleep(1 + attempt)
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
        time.sleep(1 + attempt)
    return None


def fetch_state_list(session: requests.Session) -> dict[str, str]:
    data = get_json(session, f"{UMP_BASE}/ump/ump/fetch/statelist")
    if not data:
        return {}
    return data.get("StateList", {})


def fetch_districts_for_state(session: requests.Session, state_code: str) -> dict[str, int]:
    """Returns {district_name: district_code, ...} for the given state."""
    data = post_json(session, f"{UMP_BASE}/ump/ump/state/getDistrictCodeList",
                     {"stateCode": state_code})
    if isinstance(data, dict):
        # Already in name->code format
        return {k: int(v) for k, v in data.items() if str(v).isdigit()}
    if isinstance(data, list):
        out = {}
        for d in data:
            if isinstance(d, dict):
                name = d.get("districtName") or d.get("name") or d.get("distname")
                code = d.get("districtCode") or d.get("code") or d.get("distCd")
                if name and code is not None:
                    out[name] = int(code)
        return out
    return {}


def fetch_specialities(session: requests.Session) -> list[dict]:
    data = post_json(session, f"{API_BASE}/hem/hbp/get/specialities/list", {"status": "Active"})
    return data or []


def fetch_hospitals_for_state(session: requests.Session, state_code: str) -> list[dict]:
    """Paginate all hospitals for one state. ~2,500 rows × 30/page = ~85 pages."""
    out: list[dict] = []
    page = 1
    total_pages = None
    while True:
        payload = {
            "stateCode": str(state_code),
            "facilityName": "",
            "pageNo": page,
            "size": PAGE_SIZE,
            "card": "",
            "value": "",
            "pincode": "",
        }
        data = post_json(session, f"{API_BASE}/hem/external/hospital/list", payload)
        if not data:
            log(f"    failed at page {page}, stopping state {state_code}")
            break
        content = data.get("content", [])
        out.extend(content)
        if total_pages is None:
            total_pages = data.get("totalPages", 0)
            log(f"    {data.get('totalElements', 0)} hospitals, {total_pages} pages")
        if data.get("last") or not content:
            break
        page += 1
        if page % 50 == 0:
            log(f"    page {page}/{total_pages}, {len(out)} so far")
        time.sleep(SLEEP)
    return out


def main():
    LOG_FILE.touch(exist_ok=True)
    log("=" * 60)
    log("HEM portal scraper (per-state, with district names)")

    s = requests.Session()

    log("Fetching state list ...")
    states = fetch_state_list(s)
    log(f"  {len(states)} states (incl. CAPF/CGHS)")

    log("Fetching specialities ...")
    specs = fetch_specialities(s)
    log(f"  {len(specs)} active specialities")
    SPEC_OUT.write_text(json.dumps(specs, ensure_ascii=False, indent=2), encoding="utf-8")

    # Build code -> state name map
    code_to_state = {str(v): k for k, v in states.items()}

    # Fetch all district lists up front (5,500 districts, fast)
    log("Fetching district lists for all states ...")
    all_districts: dict[str, dict[str, int]] = {}  # state_code -> {name: code}
    code_to_district: dict[str, dict[int, str]] = {}  # state_code -> {code: name}
    for name, code in sorted(states.items(), key=lambda x: int(x[1])):
        if name.upper() in SKIP_STATES:
            continue
        d = fetch_districts_for_state(s, code)
        all_districts[code] = d
        code_to_district[code] = {v: k for k, v in d.items()}
        log(f"  {name} ({code}): {len(d)} districts")
    total_districts = sum(len(d) for d in all_districts.values())
    log(f"  total: {total_districts} districts")

    STATES_OUT.write_text(json.dumps({
        "states": states,
        "districts": all_districts,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Scrape hospitals per state
    all_hospitals: dict[str, dict] = {}
    real_states = [(n, c) for n, c in states.items() if n.upper() not in SKIP_STATES]
    real_states.sort(key=lambda x: int(x[1]))

    for state_name, state_code in real_states:
        log(f"--- {state_name} ({state_code}) ---")
        rows = fetch_hospitals_for_state(s, state_code)
        log(f"  fetched {len(rows)}")
        for h in rows:
            hid = str(h.get("hospitalId", ""))
            if not hid:
                continue
            # Enrich with state and district names
            sc = str(h.get("stateCode", ""))
            dc = h.get("districtCode")
            h["_stateName"] = code_to_state.get(sc, state_name)
            if dc is not None:
                try:
                    h["_districtName"] = code_to_district.get(sc, {}).get(int(dc), "")
                except (ValueError, TypeError):
                    h["_districtName"] = ""
            else:
                h["_districtName"] = ""
            all_hospitals[hid] = h
        # Save partial after every state
        RAW_OUT.write_text(json.dumps(all_hospitals, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"  saved partial ({len(all_hospitals)} total)")
        time.sleep(SLEEP)

    log(f"DONE. {len(all_hospitals)} unique hospitals written to {RAW_OUT.name}")

    # Coverage
    by_state: dict[str, int] = {}
    by_district: dict[str, int] = {}
    for h in all_hospitals.values():
        sn = h.get("_stateName", "?") or "?"
        dn = h.get("_districtName", "?") or "?"
        by_state[sn] = by_state.get(sn, 0) + 1
        by_district[f"{sn}|{dn}"] = by_district.get(f"{sn}|{dn}", 0) + 1
    log(f"By state (top 10):")
    for sn, n in sorted(by_state.items(), key=lambda x: -x[1])[:10]:
        log(f"  {sn:40s} {n}")
    missing_state = sum(1 for h in all_hospitals.values() if not h.get("_stateName"))
    missing_district = sum(1 for h in all_hospitals.values() if not h.get("_districtName"))
    log(f"Missing state name: {missing_state}")
    log(f"Missing district name: {missing_district}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Interrupted.")
    except Exception as e:
        log(f"FATAL: {e}")
        raise
