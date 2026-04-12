"""
02_clean_normalize.py — OttO Data Pipeline, Step 2
Cleans and normalises the external EV dataset (electric_vehicles_spec_2025.csv)
into our canonical schema for the EV Land 24-model catalog.

What this script does (documented for the technical report):
  1. Load the raw external dataset (478 models, all brands)
  2. Filter to EV Land's 24 target models using an explicit model map
  3. For each model, sort variants by battery size → keep base + top trim (2 rows max)
  4. Rename and map columns to our schema
  5. Normalise drivetrain values (FWD / RWD / AWD)
  6. Normalise body_type to controlled vocabulary
  7. Inject missing fields: ac_charging_kw, weight_kg, year, base_price_eur
  8. Deduplicate on (brand, model, variant)
  9. Output data/processed/ev_specs_clean.csv

Input:  downloads/electric_vehicles_spec_2025.csv (external dataset)
Output: data/processed/ev_specs_clean.csv
"""

import csv
import re
from pathlib import Path
from copy import deepcopy

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR    = Path(__file__).resolve().parent.parent
INPUT_CSV   = Path("/Users/mehdichenini/Downloads/electric_vehicles_spec_2025.csv.csv")
OUTPUT_CSV  = BASE_DIR / "data" / "processed" / "ev_specs_clean.csv"
OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# MODEL MAP — maps raw dataset model names → our canonical (brand, model) pair
#
# Why explicit mapping instead of fuzzy matching?
# Fuzzy matching on model names is fragile — "EQS SUV" would match "EQS",
# "IONIQ 5 N" would match "IONIQ 5". An explicit map is deterministic and
# fully auditable — every inclusion decision is visible and intentional.
# ---------------------------------------------------------------------------
MODEL_MAP = {
    # (dataset_brand, dataset_model_prefix) → (canonical_brand, canonical_model)

    # Renault — dataset uses "5 E-Tech" not "R5 E-Tech"
    ("Renault", "5 E-Tech"):            ("Renault",      "R5 E-Tech"),
    ("Renault", "4 E-Tech"):            ("Renault",      "R4 E-Tech"),
    ("Renault", "Megane E-Tech"):       ("Renault",      "Megane E-Tech"),
    ("Renault", "Scenic E-Tech"):       ("Renault",      "Scenic E-Tech"),

    # Volkswagen
    ("Volkswagen", "ID.3"):             ("Volkswagen",   "ID.3"),
    ("Volkswagen", "ID.4"):             ("Volkswagen",   "ID.4"),
    ("Volkswagen", "ID.7"):             ("Volkswagen",   "ID.7"),
    ("Volkswagen", "ID. Buzz"):         ("Volkswagen",   "ID.Buzz"),

    # Kia
    ("Kia", "EV3"):                     ("Kia",          "EV3"),
    ("Kia", "EV6"):                     ("Kia",          "EV6"),
    ("Kia", "EV9"):                     ("Kia",          "EV9"),

    # Hyundai
    ("Hyundai", "Kona Electric"):       ("Hyundai",      "KONA Electric"),
    ("Hyundai", "IONIQ 5"):             ("Hyundai",      "IONIQ 5"),
    ("Hyundai", "IONIQ 6"):             ("Hyundai",      "IONIQ 6"),
    ("Hyundai", "IONIQ 9"):             ("Hyundai",      "IONIQ 9"),

    # Audi — dataset uses full descriptive names, we normalise to model family
    ("Audi", "Q4 e-tron"):              ("Audi",         "Q4 e-tron"),
    ("Audi", "Q6 e-tron"):              ("Audi",         "Q6 e-tron"),
    ("Audi", "A6 Sportback e-tron"):    ("Audi",         "A6 e-tron"),

    # Mercedes-Benz — dataset brand is "Mercedes-Benz", we use "Mercedes"
    ("Mercedes-Benz", "CLA"):           ("Mercedes",     "CLA"),
    ("Mercedes-Benz", "EQA"):           ("Mercedes",     "EQA"),
    ("Mercedes-Benz", "EQB"):           ("Mercedes",     "EQB"),
    ("Mercedes-Benz", "EQS"):           ("Mercedes",     "EQS"),
    # Note: EQE excluded — not in original EV Land catalog

    # Alpine — performance EV brand (Renault Group)
    ("Alpine", "A290"):                 ("Alpine",       "A290"),
    # Note: A390 not in dataset — injected via MANUAL_ENTRIES below
}

# Prefixes we want to EXCLUDE even if they match a model prefix above.
# e.g. "EQE SUV" starts with "EQE" but is a different model — not in our catalog.
# "ID.7 Tourer" starts with "ID.7" but is the estate variant — we want the sedan only.
# "Q4 Sportback" starts with "Q4 e-tron" — not in our catalog.
# "A6 Avant" is the wagon — we carry the Sportback sedan.
EXCLUDE_MODEL_SUBSTRINGS = [
    "EQE SUV", "EQS SUV",          # SUV variants of EQE/EQS — different model line
    "EQE",                          # EQE not in EV Land catalog (CLA replaces it)
    "ID.7 Tourer",                  # Estate variant — we carry the liftback
    "Q4 Sportback",                 # Sportback variant of Q4 — not in catalog
    "Q6 e-tron Sportback",          # Sportback variant of Q6 — not in catalog
    "SQ6",                          # Performance sub-brand — not in catalog
    "A6 Avant",                     # Estate variant of A6 — we carry Sportback
    "IONIQ 5 N",                    # Performance variant — not in catalog
    "EV6 GT",                       # Performance variant — not in catalog
    "EV9 99.8 kWh AWD GT",          # GT sub-variant — keep standard AWD only
]

# ---------------------------------------------------------------------------
# VARIANT OVERRIDES — for models where battery-size sorting gives unintuitive
# results (e.g. Mercedes naming where 350 4MATIC has same battery as 250).
# Format: (canonical_brand, canonical_model) → [exact_variant_label_base, exact_variant_label_top]
# If a label is None, fall back to the automatic sort for that position.
# ---------------------------------------------------------------------------
VARIANT_OVERRIDES = {
    ("Mercedes", "EQA"):   ["250",              "350 4MATIC"],        # FWD base → AWD top
    ("Mercedes", "EQB"):   ["250+",             "350 4MATIC"],        # FWD base → AWD top
    ("Mercedes", "CLA"):   ["250+",             "350 4MATIC"],        # RWD base → AWD top (same battery)
    ("Hyundai",  "IONIQ 9"): ["Long Range RWD", "Performance AWD"],   # RWD base → AWD top
    ("Alpine",   "A290"):  ["Electric 180 hp",  "Electric 220 hp"],   # same battery, diff power
    ("Renault",  "Megane E-Tech"): ["EV60 130hp (TU2025)", "EV60 220hp (TU2025)"],  # same battery, diff power
}

# ---------------------------------------------------------------------------
# MISSING FIELD INJECTIONS
# Fields not present in the external dataset — added from our scrape + known specs.
#
# ac_charging_kw: Max AC on-board charger (kW). Most modern EVs use 11kW.
#   Exceptions: entry-level Hyundai/Kia use 7.2kW, Renault Megane uses 7.4kW.
# weight_kg: Kerb weight in kg. Sourced from our evspecs.org scrape.
# year: Model year of the current generation. Sourced from evspecs.org scrape.
# base_price_eur: European MSRP in EUR. Sourced from official price lists (early 2025).
# ---------------------------------------------------------------------------

AC_CHARGING = {
    ("Renault",    "R5 E-Tech"):      11,
    ("Renault",    "R4 E-Tech"):      11,
    ("Renault",    "Megane E-Tech"):   7,   # 7.4kW rounded
    ("Renault",    "Scenic E-Tech"):  11,
    ("Volkswagen", "ID.3"):           11,
    ("Volkswagen", "ID.4"):           11,
    ("Volkswagen", "ID.7"):           11,
    ("Volkswagen", "ID.Buzz"):        11,
    ("Kia",        "EV3"):            11,
    ("Kia",        "EV6"):            11,
    ("Kia",        "EV9"):            11,
    ("Hyundai",    "KONA Electric"):   7,   # 7.2kW rounded
    ("Hyundai",    "IONIQ 5"):        11,
    ("Hyundai",    "IONIQ 6"):        11,
    ("Hyundai",    "IONIQ 9"):        11,
    ("Audi",       "Q4 e-tron"):      11,
    ("Audi",       "Q6 e-tron"):      11,
    ("Audi",       "A6 e-tron"):      11,
    ("Mercedes",   "CLA"):            11,
    ("Mercedes",   "EQA"):            11,
    ("Mercedes",   "EQB"):            11,
    ("Mercedes",   "EQS"):            11,
    ("Alpine",     "A290"):           11,
    ("Alpine",     "A390"):           22,   # Performance flagship — 3-phase 22kW AC
}

WEIGHT_KG = {
    ("Renault",    "R5 E-Tech"):      1350,
    ("Renault",    "R4 E-Tech"):      1450,
    ("Renault",    "Megane E-Tech"):  1630,
    ("Renault",    "Scenic E-Tech"):  1790,
    ("Volkswagen", "ID.3"):           1820,
    ("Volkswagen", "ID.4"):           2050,
    ("Volkswagen", "ID.7"):           2200,
    ("Volkswagen", "ID.Buzz"):        2400,
    ("Kia",        "EV3"):            1800,
    ("Kia",        "EV6"):            2100,
    ("Kia",        "EV9"):            2500,
    ("Hyundai",    "KONA Electric"):  1650,
    ("Hyundai",    "IONIQ 5"):        2000,
    ("Hyundai",    "IONIQ 6"):        1970,
    ("Hyundai",    "IONIQ 9"):        2657,
    ("Audi",       "Q4 e-tron"):      2190,
    ("Audi",       "Q6 e-tron"):      2350,
    ("Audi",       "A6 e-tron"):      2350,
    ("Mercedes",   "CLA"):            2100,
    ("Mercedes",   "EQA"):            2040,
    ("Mercedes",   "EQB"):            2145,
    ("Mercedes",   "EQS"):            2500,
    ("Alpine",     "A290"):           1490,
    ("Alpine",     "A390"):           2250,
}

MODEL_YEAR = {
    ("Renault",    "R5 E-Tech"):      2025,
    ("Renault",    "R4 E-Tech"):      2024,
    ("Renault",    "Megane E-Tech"):  2022,
    ("Renault",    "Scenic E-Tech"):  2023,
    ("Volkswagen", "ID.3"):           2024,
    ("Volkswagen", "ID.4"):           2024,
    ("Volkswagen", "ID.7"):           2023,
    ("Volkswagen", "ID.Buzz"):        2024,
    ("Kia",        "EV3"):            2024,
    ("Kia",        "EV6"):            2024,
    ("Kia",        "EV9"):            2023,
    ("Hyundai",    "KONA Electric"):  2023,
    ("Hyundai",    "IONIQ 5"):        2024,
    ("Hyundai",    "IONIQ 6"):        2022,
    ("Hyundai",    "IONIQ 9"):        2025,
    ("Audi",       "Q4 e-tron"):      2023,
    ("Audi",       "Q6 e-tron"):      2024,
    ("Audi",       "A6 e-tron"):      2024,
    ("Mercedes",   "CLA"):            2025,
    ("Mercedes",   "EQA"):            2023,
    ("Mercedes",   "EQB"):            2023,
    ("Mercedes",   "EQS"):            2022,
    ("Alpine",     "A290"):           2024,
    ("Alpine",     "A390"):           2025,
}

MSRP_EUR = {
    ("Renault",    "R5 E-Tech"):      25000,
    ("Renault",    "R4 E-Tech"):      32000,
    ("Renault",    "Megane E-Tech"):  35000,
    ("Renault",    "Scenic E-Tech"):  40000,
    ("Volkswagen", "ID.3"):           35000,
    ("Volkswagen", "ID.4"):           44000,
    ("Volkswagen", "ID.7"):           57000,
    ("Volkswagen", "ID.Buzz"):        60000,
    ("Kia",        "EV3"):            36000,
    ("Kia",        "EV6"):            46000,
    ("Kia",        "EV9"):            70000,
    ("Hyundai",    "KONA Electric"):  35000,
    ("Hyundai",    "IONIQ 5"):        45000,
    ("Hyundai",    "IONIQ 6"):        43000,
    ("Hyundai",    "IONIQ 9"):        75000,
    ("Audi",       "Q4 e-tron"):      47000,
    ("Audi",       "Q6 e-tron"):      63000,
    ("Audi",       "A6 e-tron"):      75000,
    ("Mercedes",   "CLA"):            56000,
    ("Mercedes",   "EQA"):            51000,
    ("Mercedes",   "EQB"):            54000,
    ("Mercedes",   "EQS"):           105000,
    ("Alpine",     "A290"):           38000,
    ("Alpine",     "A390"):           58000,
}

# ---------------------------------------------------------------------------
# Body type normalisation → controlled vocabulary
# ---------------------------------------------------------------------------
BODY_TYPE_MAP = {
    "hatchback":        "Hatchback",
    "suv":              "SUV",
    "sedan":            "Sedan",
    "van":              "Van",
    "liftback":         "Liftback",
    "pickup truck":     "Pickup",
    "station wagon":    "Estate",
    "coupe":            "Coupe",
    "convertible":      "Convertible",
    "mpv":              "Van",
}


def normalise_body_type(raw: str) -> str:
    return BODY_TYPE_MAP.get(raw.strip().lower(), raw.strip())


def normalise_drivetrain(raw: str) -> str:
    mapping = {"fwd": "FWD", "rwd": "RWD", "awd": "AWD", "4wd": "AWD", "4x4": "AWD"}
    return mapping.get(raw.strip().lower(), raw.strip())


# ---------------------------------------------------------------------------
# MANUAL ENTRIES — models not in the external dataset, hardcoded from
# verified sources (ultimatespecs.com, official press releases).
# ---------------------------------------------------------------------------
MANUAL_ENTRIES = [
    {
        "_canonical_brand": "Alpine", "_canonical_model": "A390", "_variant_label": "GT",
        "brand": "Alpine", "model": "A390", "variant": "GT", "year": 2025,
        "body_type": "SUV", "drivetrain": "AWD", "seats": "5",
        "battery_kwh": "89.0", "range_wltp_km": "555",
        "ac_charging_kw": "22", "dc_charging_kw": "190",
        "acceleration_0_100_s": "4.8", "top_speed_kmh": "200",
        "torque_nm": "", "efficiency_wh_per_km": "",
        "cargo_l": "532", "towing_capacity_kg": "",
        "length_mm": "4615", "width_mm": "1885", "height_mm": "1532",
        "weight_kg": "2250", "base_price_eur": "58000",
        "source_url": "https://www.ultimatespecs.com/car-specs/Alpine/150357/Alpine-A390-GT.html",
    },
    {
        "_canonical_brand": "Alpine", "_canonical_model": "A390", "_variant_label": "GTS",
        "brand": "Alpine", "model": "A390", "variant": "GTS", "year": 2025,
        "body_type": "SUV", "drivetrain": "AWD", "seats": "5",
        "battery_kwh": "89.0", "range_wltp_km": "520",
        "ac_charging_kw": "22", "dc_charging_kw": "190",
        "acceleration_0_100_s": "3.9", "top_speed_kmh": "220",
        "torque_nm": "808", "efficiency_wh_per_km": "",
        "cargo_l": "532", "towing_capacity_kg": "",
        "length_mm": "4615", "width_mm": "1885", "height_mm": "1532",
        "weight_kg": "2250", "base_price_eur": "58000",
        "source_url": "https://www.ultimatespecs.com/car-specs/Alpine/150356/Alpine-A390-GTS.html",
    },
]


def safe_float(val: str) -> float | None:
    try:
        return float(val.strip())
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Step 1: Match a raw dataset row to a canonical (brand, model) pair
# Returns (canonical_brand, canonical_model, variant_label) or None if no match.
# ---------------------------------------------------------------------------
def match_model(raw_brand: str, raw_model: str):
    # First check exclusions — some model names start with a prefix we DO carry
    # but the full name is a sub-model we don't want (e.g. "EQE SUV 300")
    for excl in EXCLUDE_MODEL_SUBSTRINGS:
        if raw_model.startswith(excl):
            return None

    # Try to match against our model map prefixes
    for (map_brand, map_prefix), (can_brand, can_model) in MODEL_MAP.items():
        if raw_brand == map_brand and raw_model.startswith(map_prefix):
            # Variant label = whatever comes after the model prefix
            variant = raw_model[len(map_prefix):].strip()
            return (can_brand, can_model, variant)

    return None


# ---------------------------------------------------------------------------
# Step 2: Load and filter the raw dataset
# ---------------------------------------------------------------------------
def load_and_filter(path: Path) -> dict:
    """
    Load all rows from the external CSV and group them by canonical model.
    Returns: { (brand, model): [row_dict, ...] }
    """
    groups = {}

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            result = match_model(row["brand"], row["model"])
            if result is None:
                continue

            can_brand, can_model, variant = result
            key = (can_brand, can_model)
            if key not in groups:
                groups[key] = []
            row["_canonical_brand"]  = can_brand
            row["_canonical_model"]  = can_model
            row["_variant_label"]    = variant
            groups[key].append(row)

    return groups


# ---------------------------------------------------------------------------
# Step 3: For each model group, pick base + top trim
# Sort by battery_capacity_kWh ascending → first = base, last = top
# ---------------------------------------------------------------------------
def select_variants(rows: list, canonical_key: tuple) -> list:
    # Check for manual override first
    if canonical_key in VARIANT_OVERRIDES:
        wanted = VARIANT_OVERRIDES[canonical_key]
        selected = []
        for label in wanted:
            match = next((r for r in rows if r["_variant_label"] == label), None)
            if match:
                selected.append(match)
            else:
                print(f"    [warn] Override variant '{label}' not found for {canonical_key}")
        if selected:
            return selected

    # Default: sort by battery size ascending → first = base, last = top
    def battery_sort_key(r):
        return safe_float(r.get("battery_capacity_kWh", "0")) or 0

    sorted_rows = sorted(rows, key=battery_sort_key)

    if len(sorted_rows) == 1:
        return sorted_rows

    base = sorted_rows[0]
    top  = sorted_rows[-1]

    if base["battery_capacity_kWh"] == top["battery_capacity_kWh"]:
        return [base]  # Only one real battery tier

    return [base, top]


# ---------------------------------------------------------------------------
# Step 4: Build a clean output row from a matched raw row
# ---------------------------------------------------------------------------
def build_clean_row(raw: dict) -> dict:
    brand = raw["_canonical_brand"]
    model = raw["_canonical_model"]
    key   = (brand, model)

    return {
        "brand":                 brand,
        "model":                 model,
        "variant":               raw["_variant_label"],
        "year":                  MODEL_YEAR.get(key, ""),
        "body_type":             normalise_body_type(raw.get("car_body_type", "")),
        "drivetrain":            normalise_drivetrain(raw.get("drivetrain", "")),
        "seats":                 raw.get("seats", ""),
        "battery_kwh":           raw.get("battery_capacity_kWh", ""),
        "range_wltp_km":         raw.get("range_km", ""),
        "ac_charging_kw":        AC_CHARGING.get(key, ""),
        "dc_charging_kw":        raw.get("fast_charging_power_kw_dc", ""),
        "acceleration_0_100_s":  raw.get("acceleration_0_100_s", ""),   # proper km/h metric
        "top_speed_kmh":         raw.get("top_speed_kmh", ""),
        "torque_nm":             raw.get("torque_nm", ""),
        "efficiency_wh_per_km":  raw.get("efficiency_wh_per_km", ""),
        "cargo_l":               raw.get("cargo_volume_l", ""),
        "towing_capacity_kg":    raw.get("towing_capacity_kg", ""),
        "length_mm":             raw.get("length_mm", ""),
        "width_mm":              raw.get("width_mm", ""),
        "height_mm":             raw.get("height_mm", ""),
        "weight_kg":             WEIGHT_KG.get(key, ""),
        "base_price_eur":        MSRP_EUR.get(key, ""),
        "source_url":            raw.get("source_url", ""),
    }


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------
CSV_FIELDS = [
    "brand", "model", "variant", "year",
    "body_type", "drivetrain", "seats",
    "battery_kwh", "range_wltp_km",
    "ac_charging_kw", "dc_charging_kw",
    "acceleration_0_100_s", "top_speed_kmh", "torque_nm", "efficiency_wh_per_km",
    "cargo_l", "towing_capacity_kg",
    "length_mm", "width_mm", "height_mm", "weight_kg",
    "base_price_eur", "source_url",
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("OttO — EV Specs Cleaning & Normalisation")
    print(f"Input:  {INPUT_CSV}")
    print(f"Output: {OUTPUT_CSV}")
    print("=" * 60)

    # --- Load & filter ---
    print("\n[1] Loading and filtering dataset...")
    groups = load_and_filter(INPUT_CSV)
    print(f"    Matched {len(groups)} canonical models out of 24 target")

    # Warn about any missing models
    expected = set(MSRP_EUR.keys())
    found    = set(groups.keys())
    missing  = expected - found
    if missing:
        print(f"    WARNING: Missing models: {missing}")

    # --- Select variants + build clean rows ---
    print("\n[2] Selecting base + top variant per model...")
    clean_rows = []

    for (brand, model), rows in sorted(groups.items()):
        selected = select_variants(rows, (brand, model))
        for row in selected:
            clean_rows.append(build_clean_row(row))
        variant_labels = [r["_variant_label"] for r in selected]
        print(f"    {brand} {model}: {len(rows)} variants → kept {variant_labels}")

    # --- Inject manual entries ---
    for entry in MANUAL_ENTRIES:
        clean_rows.append({k: entry.get(k, "") for k in CSV_FIELDS})
        print(f"    [manual] Injected: {entry['brand']} {entry['model']} {entry['_variant_label']}")

    # --- Deduplication ---
    print(f"\n[3] Deduplicating on (brand, model, variant)...")
    seen = set()
    deduped = []
    for row in clean_rows:
        key = (row["brand"], row["model"], row["variant"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    removed = len(clean_rows) - len(deduped)
    print(f"    {removed} duplicates removed → {len(deduped)} rows remaining")

    # --- Quality report ---
    print(f"\n[4] Quality report:")
    for field in ["battery_kwh", "range_wltp_km", "dc_charging_kw", "acceleration_0_100_s"]:
        nulls = [f"{r['brand']} {r['model']} {r['variant']}" for r in deduped if not r.get(field)]
        status = f"{len(nulls)} missing" if nulls else "✓ complete"
        print(f"    {field}: {status}")
        if nulls:
            for n in nulls:
                print(f"      - {n}")

    # --- Write output ---
    print(f"\n[5] Writing {len(deduped)} rows to {OUTPUT_CSV}")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(deduped)

    print(f"\nDone. ✓ {OUTPUT_CSV}")
    print("=" * 60)


if __name__ == "__main__":
    main()
