# PMJAY Public Hospital Scraper + Enrichment

Scrapes every empanelled hospital from the public PMJAY Find Hospital page (`https://hospitals.pmjay.gov.in/Search`) and enriches each record with per-hospital Address, Pincode, Latitude, Longitude, Email, Phone, Nodal Officer details, etc. — **no login, no CAPTCHA**.

## Final result (D:\SA_backend\hospitals\)

| File | Size | Rows |
|---|---|---|
| `hospitals.csv` | ~12 MB | 34,123 + header (38 cols) |
| `hospitals.json` | ~45 MB | 34,123 records |

## Field coverage (post-enrichment)

| Field | Coverage |
|---|---|
| Hospital Name, ID (UUID), State, Town, Timezone, Hospital Care Type, Hospital Category, Location | 100% |
| Latitude, Longitude | 97.4% |
| Address, Village | 96.6% |
| Subdistrict | 93.5% |
| Hospital Primary Email, Nodal Person Email | 82.3% |
| Helpline, Mobile Number | 83.7% |
| Pincode | 79.7% |
| Nodal Person Info, Nodal Person Tele | 74% |
| Specialities | 71.7% |
| Sub -Specialty | 11.0% |

Fields left blank (0%) are not exposed by the public PMJAY portal — they require HEM portal authentication.

## How it was built

1. **`scrape_hem.py`** — Enumerates 35 states × 3 hospital types from the public Excel export endpoint `empnlWorkFlow.htm?...&export=E`. Returns ~13 base fields.
2. **`enrich.py` / `fetch_remaining.py`** — Hits `empnlWorkFlow.htm?actionFlag=hospBasicDtlsWrkflw&hospInfoId=…` for every hospital ID (~11 req/s sequential) to get Address, Pincode, Lat/Lon, Nodal Officer, Email, Landline, etc.
3. **`apply_cache.py`** — Merges the fetched data with a hard-coded state/district centroid table (with Nominatim for unknown districts) to fill any remaining gaps.

## One-time setup

```cmd
cd D:\SA_backend\hospitals
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Running

```cmd
python scrape_hem.py        # ~10 min, builds hospitals.csv (export only)
python enrich.py             # ~1 hour, enriches per-hospital
python apply_cache.py        # < 1 min, merges all into final CSV/JSON
```

Or just use the existing final files:
- `hospitals.csv` (12 MB)
- `hospitals.json` (45 MB)

