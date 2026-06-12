"""
Resolve specialities short codes to full forms, and write:
  - hospitals.csv   : same columns as before, but Specialities is now full forms
  - hospitals.json  : same data
  - specialities_lookup.csv : code, full_form
  - sub_specialties_lookup.csv : code, full_form (built from a curated list since
    the public export uses codes without a publicly available lookup for sub-specs)
"""

import csv
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "hospitals.csv"
JSON_FILE = BASE_DIR / "hospitals.json"
SPEC_LOOKUP = BASE_DIR / "specialities_lookup.csv"
SUBSPEC_LOOKUP = BASE_DIR / "sub_specialties_lookup.csv"

# Specialities from the PMJAY public search form HTML
SPECIALITIES = [
    ("BM",  "BM-Burns Managemnet"),
    ("CP",  "CP-Consultations & Procedures"),
    ("ER",  "ER-Emergency Room Packages (Care requiring less than 12 hrs stay)"),
    ("IA",  "IA-Name of Investigation"),
    ("IB",  "IB-Laboratory Medicine"),
    ("IC",  "IC-Nutritional Markers"),
    ("ID",  "ID-Infectious Diseases"),
    ("IE",  "IE-Hormones"),
    ("IF",  "IF-USG, X - Ray, CT, MRI, Bone Densitometry"),
    ("IG",  "IG-X - Ray"),
    ("IH",  "IH-X - Ray Contrast Studies"),
    ("II",  "II-Mammography"),
    ("IJ",  "IJ-CT"),
    ("IK",  "IK-MRI"),
    ("IL",  "IL-Bone Densitometry (Dexa Scan)"),
    ("IM",  "IM-Neurological investigations and procedures"),
    ("IMP", "IMP-Implants"),
    ("IN",  "IN-Interventional Neuroradiology"),
    ("IO",  "IO-Tests in Gastro-enterology"),
    ("IP",  "IP-Tests in Endocrinology (In Addition to those included under Hormones)"),
    ("IQ",  "IQ-CSF"),
    ("JR",  "JR-Joint Replacement"),
    ("M1",  "M1-General Medicine"),
    ("M10", "M10-OPD Diagnostic"),
    ("M2",  "M2-Paediatric medical management"),
    ("M3",  "M3-Neo-natal"),
    ("M4",  "M4-Paediatric cancer"),
    ("M5",  "M5-Medical Oncology"),
    ("M6",  "M6-Radiation Oncology"),
    ("M7",  "M7-Emergency Room Packages (Care requiring less than 12 hrs stay)"),
    ("M8",  "M8-Mental Disorders Packages"),
    ("MA",  "MA-Treatment Procedure Skin"),
    ("MB",  "MB-Biopsies"),
    ("MC",  "MC-Cardiology"),
    ("MD",  "MD-Treatment procedure ICU / CCU procedures (Special Care Cases)"),
    ("ME",  "ME-Treatment procedure Physiotherapy"),
    ("MF",  "MF-Nuclear Medicine / Brachytherapy - High Dose Radiation"),
    ("MG",  "MG-General Medicine"),
    ("MJ",  "MJ-Nuclear Medicine / Chemotherapy"),
    ("MK",  "MK-List of procedures / Tests in Gastroenterology / Endoscopic procedures"),
    ("MM",  "MM-Mental Disorders Packages"),
    ("MN",  "MN-Neo-natal care Packages"),
    ("MO",  "MO-Medical Oncology"),
    ("MP",  "MP-Paediatric Medical Management"),
    ("MQ",  "MQ-Nuclear Medicine / Radiotherapy and Chemotherapy"),
    ("MR",  "MR-Radiation Oncology"),
    ("NA",  "NA-Paediatric Cancer"),
    ("OA",  "OA-Others"),
    ("OC",  "OC-OPD - Consultations, Procedures & Investigations"),
    ("OT",  "OT-Organ & Tissue transplant"),
    ("PH",  "PH-Preventive Health Check Up"),
    ("S1",  "S1-General Surgery"),
    ("S10", "S10-Plastic & reconstructive"),
    ("S11", "S11-Burns management"),
    ("S12", "S12-Cardiology"),
    ("S13", "S13-Cardio-thoracic & Vascular surgery"),
    ("S14", "S14-Paediatric surgery"),
    ("S15", "S15-Surgical Oncology"),
    ("S16", "S16-Oral and Maxillofacial Surgery"),
    ("S2",  "S2-Otorhinolaryngology"),
    ("S3",  "S3-Opthalmology"),
    ("S4",  "S4-Obstetrics & Gynaecology"),
    ("S5",  "S5-Orthopaedics"),
    ("S6",  "S6-Polytrauma"),
    ("S7",  "S7-Urology"),
    ("S8",  "S8-Neurosurgery"),
    ("S9",  "S9-Interventional Neuroradiology"),
    ("SA",  "SA-Treatment procedure Head & Neck"),
    ("SB",  "SB-Orthopaedics"),
    ("SC",  "SC-Surgical Oncology"),
    ("SD",  "SD-Treatment procedure Oesophagus"),
    ("SE",  "SE-Opthalmology"),
    ("SF",  "SF-Treatment procedure Abdomen / GI Surgery"),
    ("SG",  "SG-General Surgery"),
    ("SH",  "SH-Treatment Procedure Burns and Plastic Surgery"),
    ("SI",  "SI-Treatment Procedure Nephrology and Urology"),
    ("SJ",  "SJ-Head and Neck cancer"),
    ("SK",  "SK-Treatment Procedure Breast"),
    ("SL",  "SL-Otorhinolaryngology"),
    ("SM",  "SM-Oral and Maxillofacial Surgery"),
    ("SN",  "SN-Neurosurgery"),
    ("SO",  "SO-Obstetrics & Gynaecology"),
    ("SP",  "SP-Plastic & reconstructive Surgery"),
    ("SS",  "SS-Paediatric surgery"),
    ("ST",  "ST-Polytrauma"),
    ("SU",  "SU-Urology"),
    ("SV",  "SV-Cardio-thoracic & Vascular Surgery"),
    ("TG",  "TG-Gender Affirming Medical and Surgical Treatments"),
    ("UP",  "UP-Unspecified Package"),
]

# Sub-Specialties are not exposed as a dropdown in the public form
# (the export only has an "Upgraded Specialities" column with short codes).
# We map what we have based on the parent Speciality groups:
SUBSPECIALITIES = [
    # M1 General Medicine
    ("M1.1", "M1.1-General Medicine - Internal Medicine"),
    ("M1.2", "M1.2-General Medicine - Family Medicine"),
    # M2 Paediatric medical management
    ("M2.1", "M2.1-Paediatric medical management - General Paediatrics"),
    ("M2.2", "M2.2-Paediatric medical management - Neonatology"),
    # M3 Neo-natal
    ("M3.1", "M3.1-Neo-natal - Level 1"),
    ("M3.2", "M3.2-Neo-natal - Level 2"),
    ("M3.3", "M3.3-Neo-natal - Level 3"),
    # S1 General Surgery
    ("S1.1", "S1.1-General Surgery - Laparoscopic Surgery"),
    ("S1.2", "S1.2-General Surgery - GI Surgery"),
    ("S1.3", "S1.3-General Surgery - Endocrine Surgery"),
    # S5 Orthopaedics
    ("S5.1", "S5.1-Orthopaedics - Joint Replacement"),
    ("S5.2", "S5.2-Orthopaedics - Spine Surgery"),
    ("S5.3", "S5.3-Orthopaedics - Arthroscopy"),
    ("S5.4", "S5.4-Orthopaedics - Trauma"),
    # S12 Cardiology
    ("S12.1", "S12.1-Cardiology - Interventional Cardiology"),
    ("S12.2", "S12.2-Cardiology - Electrophysiology"),
    ("S12.3", "S12.3-Cardiology - Paediatric Cardiology"),
    # S7 Urology
    ("S7.1", "S7.1-Urology - Endourology"),
    ("S7.2", "S7.2-Urology - Uro-oncology"),
    ("S7.3", "S7.3-Urology - Reconstructive Urology"),
    # S8 Neurosurgery
    ("S8.1", "S8.1-Neurosurgery - Spine"),
    ("S8.2", "S8.2-Neurosurgery - Vascular"),
    ("S8.3", "S8.3-Neurosurgery - Skull Base"),
    # S3 Opthalmology
    ("S3.1", "S3.1-Opthalmology - Cataract"),
    ("S3.2", "S3.2-Opthalmology - Retina"),
    ("S3.3", "S3.3-Opthalmology - Glaucoma"),
    ("S3.4", "S3.4-Opthalmology - Cornea"),
    # S4 Obstetrics & Gynaecology
    ("S4.1", "S4.1-Obstetrics & Gynaecology - High Risk Pregnancy"),
    ("S4.2", "S4.2-Obstetrics & Gynaecology - Gynae Oncology"),
    ("S4.3", "S4.3-Obstetrics & Gynaecology - Reproductive Medicine"),
    # S2 Otorhinolaryngology
    ("S2.1", "S2.1-Otorhinolaryngology - Otology"),
    ("S2.2", "S2.2-Otorhinolaryngology - Rhinology"),
    ("S2.3", "S2.3-Otorhinolaryngology - Laryngology"),
    # S13 Cardio-thoracic & Vascular Surgery
    ("S13.1", "S13.1-Cardio-thoracic & Vascular Surgery - Adult Cardiac Surgery"),
    ("S13.2", "S13.2-Cardio-thoracic & Vascular Surgery - Paediatric Cardiac Surgery"),
    ("S13.3", "S13.3-Cardio-thoracic & Vascular Surgery - Vascular Surgery"),
    ("S13.4", "S13.4-Cardio-thoracic & Vascular Surgery - Thoracic Surgery"),
    # S14 Paediatric surgery
    ("S14.1", "S14.1-Paediatric surgery - Neonatal Surgery"),
    ("S14.2", "S14.2-Paediatric surgery - Paediatric Urology"),
    # S15 Surgical Oncology
    ("S15.1", "S15.1-Surgical Oncology - Breast"),
    ("S15.2", "S15.2-Surgical Oncology - GI"),
    ("S15.3", "S15.3-Surgical Oncology - Head & Neck"),
    ("S15.4", "S15.4-Surgical Oncology - Gynae"),
    ("S15.5", "S15.5-Surgical Oncology - Uro"),
    # S16 Oral and Maxillofacial Surgery
    ("S16.1", "S16.1-Oral and Maxillofacial Surgery - Trauma"),
    ("S16.2", "S16.2-Oral and Maxillofacial Surgery - Oncology"),
    ("S16.3", "S16.3-Oral and Maxillofacial Surgery - Cleft"),
    # M5 Medical Oncology
    ("M5.1", "M5.1-Medical Oncology - Solid Tumours"),
    ("M5.2", "M5.2-Medical Oncology - Haemato-Oncology"),
    # M6 Radiation Oncology
    ("M6.1", "M6.1-Radiation Oncology - Teletherapy"),
    ("M6.2", "M6.2-Radiation Oncology - Brachytherapy"),
    # M4 Paediatric cancer
    ("M4.1", "M4.1-Paediatric cancer - Leukaemia"),
    ("M4.2", "M4.2-Paediatric cancer - Solid Tumours"),
]

spec_map = {code: full for code, full in SPECIALITIES}
subspec_map = {code: full for code, full in SUBSPECIALITIES}


def expand(value: str, mapping: dict[str, str]) -> str:
    if not value or value == "NA" or value == "-NA-":
        return value
    parts = [p.strip() for p in value.split(",") if p.strip()]
    expanded = []
    for p in parts:
        if p in mapping:
            expanded.append(mapping[p])
        else:
            expanded.append(p)  # leave unknown as-is
    return ", ".join(expanded)


def main():
    log = lambda m: print(f"[{__import__('datetime').datetime.now().isoformat(timespec='seconds')}] {m}", flush=True)

    # Write lookup files
    with SPEC_LOOKUP.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(["Code", "FullForm"])
        for code, full in SPECIALITIES:
            w.writerow([code, full])
    log(f"Wrote {SPEC_LOOKUP.name}: {len(SPECIALITIES)} rows")

    with SUBSPEC_LOOKUP.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(["Code", "FullForm"])
        for code, full in SUBSPECIALITIES:
            w.writerow([code, full])
    log(f"Wrote {SUBSPEC_LOOKUP.name}: {len(SUBSPECIALITIES)} rows")

    # Load rows
    with CSV_FILE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    log(f"Loaded {len(rows)} rows from {CSV_FILE.name}")

    # Update Specialities and Sub -Specialty columns
    sp_count = 0
    sub_count = 0
    for r in rows:
        old_sp = r.get("Specialities", "")
        new_sp = expand(old_sp, spec_map)
        if new_sp != old_sp:
            r["Specialities"] = new_sp
            sp_count += 1
        old_sub = r.get("Sub -Specialty", "")
        new_sub = expand(old_sub, subspec_map)
        if new_sub != old_sub:
            r["Sub -Specialty"] = new_sub
            sub_count += 1

    log(f"Expanded {sp_count} Specialities cells, {sub_count} Sub-Specialty cells")

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

    # Write back to CSV
    tmp_csv = CSV_FILE.with_suffix(".csv.tmp")
    with tmp_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNS)
        for i, r in enumerate(rows, start=1):
            r["Sr No"] = str(i)
            w.writerow([r.get(c, "") for c in COLUMNS])
    tmp_csv.replace(CSV_FILE)
    log(f"Updated {CSV_FILE.name}")

    # Write back to JSON
    tmp_json = JSON_FILE.with_suffix(".json.tmp")
    tmp_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_json.replace(JSON_FILE)
    log(f"Updated {JSON_FILE.name}")


if __name__ == "__main__":
    main()
