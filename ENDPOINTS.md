# PMJAY + HEM Hospital Endpoints Reference

> Endpoints reverse-engineered from two NHA portals:
> 1. `hospitals.pmjay.gov.in` (PMJAY public "Find Hospital" search, F5 LB + cookie required)
> 2. `hem.nha.gov.in` (Hospital Empanelment Module — React SPA, real API on `apisprod.nha.gov.in`)
>
> All endpoints are unauthenticated. The HEM API does not need the SPA session.
>
> ---
>
> ## HEM endpoints (used by `scrape_hem2.py` + `merge_hem.py`)
>
> **Base URL:** `https://apisprod.nha.gov.in/pmjay/prodhem`
> **UI:** `https://hem.nha.gov.in` — loads a 14 MB React bundle that calls these APIs.
> **Auth:** none. Browser-like headers required (`Referer: https://hem.nha.gov.in/`).
>
> ### Hospital list (the primary scrape endpoint)
>
> | | |
> |---|---|
> | Method | POST |
> | Path | `/hem/external/hospital/list` |
> | Body | `{ "facilityName": "", "pageNo": 1, "size": 30, "card": "", "value": "", "pincode": "" }` |
> | Returns | Spring-style paginated JSON: `content[]` of 42 fields per hospital, plus `totalElements`, `totalPages`, `last`. |
> | Max size | 30 per page (server returns 400 if larger) |
> | Total | 37,608 hospitals across 1,254 pages |
> | Filters | `card=hosp_type_code` with `value=G` (Government, 19,768) or `P` (Private, 17,828). `facilityName` (LIKE search). `pincode` (exact). **State/district/speciality cards return all 37k** — they are not implemented server-side, only as UI cards. |
>
> Per-hospital fields: `hospitalId` (numeric), `hospName`, `hospAddress`, `hospCity`, `hospPin`, `hospMobileNumber`, `hospEmailId`, `hospContactNumber`, `stateCode`, `districtCode`, `hospLatitude`, `hospLongitude`, `specialityCode` (comma-list of HEM speciality ids), `schemeCode` (e.g. PMJAY, CGHS, CAPF, SEC, SMILE, NAMASTE, PMCARE, MMLSAY, BOCW, MORTH), `accredited` (Y/N), `hospTypeCode` (G/P/N/D), `nodalOfficerName`, `nodalOfficerNumber`, `facilityId` (the merge key — same scheme as PMJAY UUID, e.g. `HOSP27P26277430`), `hospWebsite`, `type` (Hospital/Diagnostic Centre/...), `empaneledDate`, `establishmentYear`, `hfrId`, `createdDate`, `updatedDate`.
>
> ### Specialities
>
> | | |
> |---|---|
> | Method | POST |
> | Path | `/hem/hbp/get/specialities/list` |
> | Body | `{ "status": "Active" }` |
> | Returns | 74 active specialities: `specialityid` (e.g. `100001`), `specialitycode` (e.g. `BM`), `specialityname` (e.g. `Burns Management`). |
> | Used in | `scrape_hem2.py:fetch_specialities`, `merge_hem.py:hem_to_csv_row` to map comma-list `specialityCode` to human-readable names. |
>
> ### State list
>
> | | |
> |---|---|
> | Method | GET |
> | Path | `https://apisprod.nha.gov.in/pmjay/prodump/ump/ump/fetch/statelist` |
> | Returns | `{"StateList": {"ANDHRA PRADESH": "28", "DELHI": "7", ...}}` — 44 entries including CAPF, CGHS, ESIC, PSU, NHCP. |
>
> ### State-wise counts
>
> | | |
> |---|---|
> | Method | GET |
> | Path | `/hem/external/profile/getHospitalCountByStateWise` |
> | Returns | `{"28": {"data": {"Government": 1415, "Private": 1057, "NABH Accrediated": 27}}, ...}` |
>
> ### Per-hospital profile (non-functional in public API)
>
> | | |
> |---|---|
> | Method | POST |
> | Path | `/hem/external/hospital/profile` |
> | Body | `{ "hospInfoId": <numeric hospitalId> }` |
> | Returns | Always 400 with `{"errorcode":404,"error":"Data Not Found."}` — backend is wired but always 404. **Not usable for scraping.** |
>
> ### Lookup codes
>
> | | |
> |---|---|
> | Method | GET |
> | Path | `/hem/external/getLookupCodes` |
> | Returns | ~1000 lookup entries with `lookupCode`/`lookupValue` pairs for status codes, accreditation types, hospital facility types, CGHS cities, etc. |
>
> ---
>
> ## PMJAY endpoints (the original `hospitals.pmjay.gov.in` site)

---

## 1. The session bootstrap (mandatory)

| Step | Method | URL | Purpose |
|------|--------|-----|---------|
| 1 | `GET` | `https://hospitals.pmjay.gov.in/Search` | Triggers a 302 to `/Search/`. The 302 response sets two cookies: `TS014ff2a1` (F5 session) and `APP_encrypted` (server-side app state). Follow the redirect (curl `-L`) and **save the cookies** — every subsequent call must send them. |

The cookies do not appear to expire quickly; the same session was reused successfully for many requests in a row. If the server ever returns 403 again, re-bootstrap by hitting `/Search` once.

Browser-like request headers that work:

```
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
            (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8
Accept-Language: en-US,en;q=0.5
Referer: https://hospitals.pmjay.gov.in/Search/
```

---

## 2. The five data endpoints

All five are called by the scraper scripts in this repo. They all live under `/Search/`.

### 2.1 List hospitals (the "search screen" endpoint)

| | |
|---|---|
| **Method** | `GET` (works) or `POST` |
| **Path** | `/Search/empanelApplicationForm.htm` |
| **Key params** | `actionVal=GETHOSPNAMESLIST`, `searchState={state_id}`, `searchHospType={Public\|PrivateNP\|PrivateP}`, `search=Y` |
| **Returns** | Plain text (not JSON): a comma-separated list of `hospId~Hospital Name, hospId~Hospital Name, …` |
| **Used in** | `enrich.py:103` — note: the public listing is rarely used by the scraper because the bulk Excel export is faster. |
| **Cookie required** | Yes |

### 2.2 Districts for a state (dropdown population)

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/Search/empanelApplicationForm.htm` |
| **Key params** | `actionVal=GETLOCATIONS`, `locType=DT`, `locVal={state_id}` |
| **Returns** | Plain text: `code~District Name, code~District Name, …` |
| **Used in** | `enrich.py:fetch_state_district_table` |
| **Cookie required** | Yes |

### 2.3 Bulk hospital list (Excel export)

This is the **primary "search screen where all hospitals are listed"** endpoint used by the scraper. It returns an `.xls` workbook (~15 columns) for one state + one hospital type.

| | |
|---|---|
| **Method** | `POST` (works), body empty |
| **Path** | `/Search/empnlWorkFlow.htm` |
| **Key params** | `actionFlag=ViewRegisteredHosptlsNew`, `export=E`, `searchState={id}`, `searchHospType={Public\|PrivateNP\|PrivateP}`, `search=Y`, `applSearch=N`, `appReadOnly=Y`, `draftMenu=N`, `invalidMenu=N` |
| **Returns** | `application/vnd.ms-excel` (XLS) when there is data, or an HTML "no records" page when empty |
| **Used in** | `scrape_hem.py:export_xls`, `fetch_remaining.py`, `enrich.py` |
| **Cookie required** | Yes |
| **State IDs** | 36 IDs (see `STATES` in `scrape_hem.py`) — e.g. `1`=Jammu & Kashmir, `9`=UP, `22`=Chhattisgarh, `28`=Andhra Pradesh, `99`=NHCP, `98`=PSU |
| **Hospital types** | `Public`, `PrivateNP`, `PrivateP` |

### 2.4 Hospital basic details (per-hospital profile)

| | |
|---|---|
| **Method** | `POST` (works), body empty |
| **Path** | `/Search/empnlWorkFlow.htm` |
| **Key params** | `actionFlag=hospBasicDtlsWrkflw`, `hospInfoId={uuid}` |
| **Returns** | HTML page with the form fields (Address, Pincode, Latitude, Longitude, Nodal Officer Name/Number, Hospital Specialty Type, etc.) |
| **Used in** | `enrich.py:enrich_one`, `fetch_remaining.py:74` |
| **Cookie required** | Yes |

### 2.5 Hospital specialities (per-hospital checkbox list)

This is the endpoint that **fetches the specialities** for the 8k+ hospitals still missing them.

| | |
|---|---|
| **Method** | `GET` (the form is a GET form) — `POST` also works but returns a stripped page |
| **Path** | `/Search/empnlWorkFlow.htm` |
| **Key params** | `actionFlag=spclityServicesDetails`, `hospInfoId={uuid}`, `appReadOnly=Y` |
| **Returns** | HTML with three groups of checkboxes. The checked ones carry the suffix `checked` on the `id` attribute: |
| | `id="hospXX"` — specialities the hospital applied for |
| | `id="empXX"` — empanelled specialities |
| | `id="upEmpXX"` — upgraded (sub-)specialities |
| | `XX` is the short code (e.g. `MN`, `SO`, `S1`, `S12.3`). Extract with the regex `<input[^>]*id="(hosp\|emp\|upEmp)(\w+)"[^>]*checked`. |
| **Used in** | `fetch_specialities.py:fetch_specialities` |
| **Cookie required** | Yes |

### 2.6 External: Nominatim geocoder (lat/lon fallback)

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `https://nominatim.openstreetmap.org/search` |
| **Key params** | `q={district}, {state}, India`, `format=json`, `limit=1`, `countrycodes=in` |
| **Returns** | JSON array with `lat`, `lon`, `display_name` |
| **Used in** | `enrich.py:geocode_district` — only when a hospital's lat/lon is missing; Nominatim's 1 req/s rate-limit is respected with a 1 s sleep. |

---

## 3. Endpoint quick-reference table

| # | Path | Key param | Method | Returns | Cookie? |
|---|------|-----------|--------|---------|---------|
| 1 | `/Search/empanelApplicationForm.htm` | `actionVal=GETHOSPNAMESLIST` | GET | text list of `id~name` | ✓ |
| 2 | `/Search/empanelApplicationForm.htm` | `actionVal=GETLOCATIONS&locType=DT&locVal={state}` | GET | text list of `code~name` | ✓ |
| 3 | `/Search/empnlWorkFlow.htm` | `actionFlag=ViewRegisteredHosptlsNew&export=E&searchState={s}&searchHospType={t}` | POST | XLS workbook | ✓ |
| 4 | `/Search/empnlWorkFlow.htm` | `actionFlag=hospBasicDtlsWrkflw&hospInfoId={uuid}` | POST | HTML profile | ✓ |
| 5 | `/Search/empnlWorkFlow.htm` | `actionFlag=spclityServicesDetails&hospInfoId={uuid}&appReadOnly=Y` | GET | HTML with checkboxes | ✓ |
| 6 | `nominatim.openstreetmap.org/search` | `q=…&format=json&limit=1&countrycodes=in` | GET | JSON | — |

---

## 4. The ~9 459 hospitals with empty Specialities — investigation result

**TL;DR: those 9 459 hospitals genuinely have no specialities recorded in the PMJAY database. There is nothing to fetch.**

We instrumented `fetch_specialities_fast.py` to (a) bootstrap the F5 session cookie correctly and (b) verify each hospital's `spclityServicesDetails` page. Running the script against all 9 459 HIDs produced:

| Outcome | Count |
|---|---|
| `ok` (real checked checkboxes) | **0** |
| `empty` (32 KB real page, all checkboxes `disabled` unchecked) | 9 448 |
| `forbidden` (403, transient) | 11 |
| `error` | 0 |

The `empty` 9 448 hospitals all return a 32 KB page that contains the full speciality table HTML with header rows `Hospital Applied Specialities / Empanelled Specialities / Upgraded Specialities / De-Empanelled Specialities` but with every checkbox in the `disabled` state — i.e. the data is genuinely missing server-side.

The 11 `forbidden` results were transient: they happened late in the run when the F5 session expired. The script now auto re-bootstraps the session after 25 consecutive 403s.

### Why did the first run fail, then?

The original `fetch_specialities.py` was called **without** the load-balancer bootstrap. Every call returned a 403 "Access Forbidden" HTML page (597 bytes, `<title>Access Forbidden</title>`) that contained zero checkboxes, so the script silently recorded `[]` for the hospital and moved on. The 24 664 hospitals that succeeded were the ones the server happened to let through (the load-balancer sometimes lets unauthenticated calls pass for a window).

`fetch_specialities_fast.py` fixes this by adding a one-time `GET https://hospitals.pmjay.gov.in/Search` call (manually redirecting the 302 to https) **before** the bulk fetch. `requests.Session` keeps the cookies for all subsequent calls in the session.

### Recommendation

Mark the 9 459 empty specialities as `NA — no specialities listed in PMJAY database` and stop trying to fetch them. If specialities are needed for those hospitals, the source-of-truth is not the PMJAY portal and you'll have to look up each one individually.
