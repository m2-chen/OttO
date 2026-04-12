"""
03_generate_synthetic.py — OttO Data Pipeline, Step 3
Generates all synthetic dealership data for EV Land.

Datasets generated:
  data/synthetic/staff.csv           —  8 employees (Sales, Technicians, Parts, Manager)
  data/synthetic/inventory.csv       —  stock entries per vehicle variant
  data/synthetic/customers.csv       —  150 fictional CRM profiles
  data/synthetic/appointments.csv    —  45-day booking calendar
  data/synthetic/service_history.csv —  18 months of past service records
  data/synthetic/parts_catalog.json  —  EV parts catalog with compatibility arrays

Design principles:
  - Fixed random seed (42) → fully reproducible on every run
  - Pure Python + Faker — no LLM calls needed
  - All noise injections documented inline (% of nulls, blocked slots, etc.)
  - Staff pre-assigned to appointment slots at generation time (not a runtime constraint)
  - No real personal data — all names/phones/emails are Faker-generated
"""

import csv
import json
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from faker import Faker

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
SEED = 42
random.seed(SEED)

fake = Faker(["fr_FR", "de_DE", "en_GB", "es_ES"])
Faker.seed(SEED)

BASE_DIR   = Path(__file__).resolve().parent.parent
SYNTH_DIR  = BASE_DIR / "data" / "synthetic"
SYNTH_DIR.mkdir(parents=True, exist_ok=True)

PROCESSED_CSV = BASE_DIR / "data" / "processed" / "ev_specs_clean.csv"

TODAY = date(2026, 3, 13)   # fixed reference date for reproducibility

# ---------------------------------------------------------------------------
# Load vehicle variants from ev_specs_clean.csv
# We need vehicle_ids to reference across all datasets.
# ---------------------------------------------------------------------------
def load_vehicles() -> list[dict]:
    vehicles = []
    with open(PROCESSED_CSV, newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), start=1):
            row["vehicle_id"] = i
            vehicles.append(row)
    return vehicles


# ===========================================================================
# 1. STAFF
# 8 employees — Sales (3), Technician (2), Parts (1), Service Advisor (1), Manager (1)
# Staff are pre-assigned to appointment slots at generation time.
# ===========================================================================
STAFF = [
    # id, first, last, role, department
    (1,  "Thomas",   "Lefebvre",   "EV Sales Advisor",    "Sales"),
    (2,  "Marie",    "Dubois",     "EV Sales Advisor",    "Sales"),
    (3,  "Carlos",   "Romero",     "EV Sales Advisor",    "Sales"),
    (4,  "Lukas",    "Schneider",  "EV Technician",       "Maintenance"),
    (5,  "Amira",    "Benali",     "EV Technician",       "Maintenance"),
    (6,  "Sophie",   "Martin",     "Parts Specialist",    "Parts"),
    (7,  "Pieter",   "Van den Berg","Service Advisor",    "Maintenance"),
    (8,  "Isabelle", "Morel",      "Dealership Manager",  "Management"),
]

STAFF_BY_DEPT = {
    "Sales":       [s for s in STAFF if s[4] == "Sales"],
    "Maintenance": [s for s in STAFF if s[4] == "Maintenance"],
    "Parts":       [s for s in STAFF if s[4] == "Parts"],
}

def generate_staff() -> list[dict]:
    rows = []
    for staff_id, first, last, role, dept in STAFF:
        rows.append({
            "staff_id":   staff_id,
            "first_name": first,
            "last_name":  last,
            "role":       role,
            "department": dept,
            "email":      f"{first.lower()}.{last.lower().replace(' ', '').replace('den', '')}@evland.eu",
            "phone":      fake.phone_number(),
        })
    return rows


# ===========================================================================
# 2. INVENTORY
# For each of the 48 vehicle variants, generate 1–4 stock entries
# (different colors). Each entry is a physical unit on the lot.
#
# Noise:
#   - 8% of entries: stock_count = 0  (sold out)
#   - 10% of entries: is_demo_car = True
# ===========================================================================
COLORS_BY_BRAND = {
    "Renault":    ["Flame Red", "Midnight Blue", "Pearl White", "Iron Grey", "Soleil Yellow"],
    "Volkswagen": ["Candy White", "Deep Black", "Moonstone Grey", "Atoll Blue", "Kings Red"],
    "Kia":        ["Snow White Pearl", "Steel Grey", "Runway Red", "Aurora Black", "Ocean Blue"],
    "Hyundai":    ["Atlas White", "Abyss Black", "Cyber Grey", "Shooting Star", "Gravity Gold"],
    "Audi":       ["Glacier White", "Mythos Black", "Daytona Grey", "Navarra Blue", "Tango Red"],
    "Mercedes":   ["Polar White", "Obsidian Black", "Mojave Silver", "Spectral Blue", "Patagonia Red"],
    "Alpine":     ["Alpine White", "Premiere Blue", "Midnight Black", "Racing Red"],
}

def generate_inventory(vehicles: list[dict]) -> list[dict]:
    rows = []
    inv_id = 1

    for v in vehicles:
        brand  = v["brand"]
        msrp   = float(v["base_price_eur"]) if v["base_price_eur"] else 40000
        colors = COLORS_BY_BRAND.get(brand, ["White", "Black", "Grey"])

        # Pick 2–3 colors per variant
        num_colors = random.randint(2, 3)
        chosen_colors = random.sample(colors, min(num_colors, len(colors)))

        for color in chosen_colors:
            # Dealer margin: 4–8% above MSRP
            margin      = random.uniform(0.04, 0.08)
            dealer_price = int(msrp * (1 + margin))

            # 8% chance sold out
            stock_count = 0 if random.random() < 0.08 else random.randint(1, 8)

            # 10% chance it's a demo car
            is_demo = random.random() < 0.10

            # If demo car and in stock, max 1 unit
            if is_demo and stock_count > 1:
                stock_count = 1

            # Available from: today or up to 30 days in the future (pre-orders)
            days_offset    = random.randint(0, 30) if stock_count == 0 else 0
            available_from = (TODAY + timedelta(days=days_offset)).isoformat()

            rows.append({
                "inventory_id":    inv_id,
                "vehicle_id":      v["vehicle_id"],
                "brand":           brand,
                "model":           v["model"],
                "variant":         v["variant"],
                "color":           color,
                "stock_count":     stock_count,
                "is_demo_car":     is_demo,
                "dealer_price_eur": dealer_price,
                "available_from":  available_from,
            })
            inv_id += 1

    return rows


# ===========================================================================
# 3. CUSTOMERS
# 150 fictional CRM profiles. ~60% own a EV Land vehicle (owned_vehicle_id).
# Languages reflect European market: 40% FR, 25% EN, 20% DE, 15% ES.
# ===========================================================================
PARIS_CITIES = [
    "Suresnes", "Puteaux", "Nanterre", "Levallois-Perret", "Neuilly-sur-Seine",
    "Boulogne-Billancourt", "Issy-les-Moulineaux", "Courbevoie", "Asnières-sur-Seine",
    "Clichy", "Saint-Cloud", "Rueil-Malmaison", "Colombes", "Gennevilliers",
    "Montrouge", "Vanves", "Malakoff", "Clamart", "Châtillon", "Meudon",
]

def generate_customers(vehicles: list[dict], n: int = 150) -> list[dict]:
    rows = []
    vehicle_ids = [v["vehicle_id"] for v in vehicles]

    locale_fake = Faker("fr_FR")
    locale_fake.seed_instance(SEED)

    for i in range(1, n + 1):
        locale_fake.seed_instance(SEED + i)

        first = locale_fake.first_name()
        last  = locale_fake.last_name()

        # 60% of customers own a EV Land car
        owned_vehicle_id = random.choice(vehicle_ids) if random.random() < 0.60 else ""

        rows.append({
            "customer_id":      i,
            "first_name":       first,
            "last_name":        last,
            "phone":            locale_fake.phone_number(),
            "email":            f"{first.lower().replace(' ', '')}.{last.lower().replace(' ', '')}@{locale_fake.free_email_domain()}",
            "owned_vehicle_id": owned_vehicle_id,
            "city":             random.choice(PARIS_CITIES),
        })

    return rows


# ===========================================================================
# 4. APPOINTMENTS
# 45-day calendar (today → today + 44 days). Mon–Sat only.
# Slot types: test_drive (30 min) | maintenance (60–90 min) | parts_fitting (60 min)
# Business hours: 09:00–12:00 and 13:30–18:00 (lunch gap blocked).
# Staff pre-assigned based on appointment type.
#
# Noise:
#   - 12% of slots: status = "blocked"  (technician unavailable, no reason given)
# ===========================================================================
SLOT_TEMPLATES = [
    # (start_time, duration_min, appt_type, department)
    (time(9,  0),  30,  "test_drive",    "Sales"),
    (time(9, 30),  30,  "test_drive",    "Sales"),
    (time(10, 0),  30,  "test_drive",    "Sales"),
    (time(10, 30), 60,  "maintenance",   "Maintenance"),
    (time(11, 0),  30,  "test_drive",    "Sales"),
    (time(11, 30), 60,  "maintenance",   "Maintenance"),
    (time(13, 30), 30,  "test_drive",    "Sales"),
    (time(14, 0),  60,  "maintenance",   "Maintenance"),
    (time(14, 30), 30,  "test_drive",    "Sales"),
    (time(15, 0),  60,  "parts_fitting", "Parts"),
    (time(15, 30), 30,  "test_drive",    "Sales"),
    (time(16, 0),  90,  "maintenance",   "Maintenance"),
    (time(16, 30), 60,  "parts_fitting", "Parts"),
    (time(17, 0),  30,  "test_drive",    "Sales"),
]

def pick_staff(dept: str) -> tuple:
    """Pick a random staff member from the given department."""
    candidates = STAFF_BY_DEPT.get(dept, STAFF_BY_DEPT["Sales"])
    return random.choice(candidates)

def generate_appointments(customers: list[dict], vehicles: list[dict]) -> list[dict]:
    rows = []
    slot_id = 1

    booked_customers = [c for c in customers if c["owned_vehicle_id"]]
    vehicle_ids      = [v["vehicle_id"] for v in vehicles]

    for day_offset in range(45):
        slot_date = TODAY + timedelta(days=day_offset)

        # Skip Sundays (weekday() == 6)
        if slot_date.weekday() == 6:
            continue

        for (start_t, duration, appt_type, dept) in SLOT_TEMPLATES:
            slot_dt = datetime.combine(slot_date, start_t)
            staff   = pick_staff(dept)

            # 12% chance: blocked (technician/advisor unavailable)
            if random.random() < 0.12:
                rows.append({
                    "slot_id":         slot_id,
                    "slot_datetime":   slot_dt.isoformat(),
                    "duration_min":    duration,
                    "type":            appt_type,
                    "status":          "blocked",
                    "staff_id":        staff[0],
                    "staff_name":      f"{staff[1]} {staff[2]}",
                    "customer_name":   "",
                    "customer_phone":  "",
                    "vehicle_id":      "",
                })
                slot_id += 1
                continue

            # 40% chance: booked
            if random.random() < 0.40:
                customer = random.choice(booked_customers) if booked_customers else None
                vid = customer["owned_vehicle_id"] if customer and appt_type != "test_drive" \
                      else random.choice(vehicle_ids)

                rows.append({
                    "slot_id":         slot_id,
                    "slot_datetime":   slot_dt.isoformat(),
                    "duration_min":    duration,
                    "type":            appt_type,
                    "status":          "booked",
                    "staff_id":        staff[0],
                    "staff_name":      f"{staff[1]} {staff[2]}",
                    "customer_name":   f"{customer['first_name']} {customer['last_name']}" if customer else "",
                    "customer_phone":  customer["phone"] if customer else "",
                    "vehicle_id":      vid,
                })
                slot_id += 1
                continue

            # Otherwise: available
            rows.append({
                "slot_id":         slot_id,
                "slot_datetime":   slot_dt.isoformat(),
                "duration_min":    duration,
                "type":            appt_type,
                "status":          "available",
                "staff_id":        staff[0],
                "staff_name":      f"{staff[1]} {staff[2]}",
                "customer_name":   "",
                "customer_phone":  "",
                "vehicle_id":      "",
            })
            slot_id += 1

    return rows


# ===========================================================================
# 5. SERVICE HISTORY
# ~200 records over the past 18 months (Sept 2024 → March 2026).
# Links customers who own a EV Land car to their vehicle.
#
# Noise:
#   - 5% of records: cost_eur = null  (invoice not yet processed)
# ===========================================================================
SERVICE_TYPES = [
    ("annual_service",  0.30, 1.5, 2.0,  180,  420),
    ("battery_check",   0.20, 0.5, 1.0,   80,  150),
    ("tire_rotation",   0.15, 0.5, 1.0,   60,  120),
    ("repair",          0.20, 1.0, 4.0,  150, 1200),
    ("recall",          0.15, 0.5, 2.0,    0,    0),   # recall = free
]

def generate_service_history(customers: list[dict], n: int = 200) -> list[dict]:
    rows      = []
    record_id = 1

    # Only customers who own a car can have service history
    owners = [c for c in customers if c["owned_vehicle_id"]]
    if not owners:
        return rows

    # Reference date range: 18 months back from today
    start_date = TODAY - timedelta(days=548)   # ~18 months
    date_range = (TODAY - start_date).days

    technicians = [s for s in STAFF if s[4] == "Maintenance"]

    for _ in range(n):
        customer    = random.choice(owners)
        technician  = random.choice(technicians)

        # Pick service type by weighted probability
        svc_types, weights = zip(*[(s[0], s[1]) for s in SERVICE_TYPES])
        svc = random.choices(svc_types, weights=weights)[0]
        svc_details = next(s for s in SERVICE_TYPES if s[0] == svc)
        _, _, dur_min, dur_max, cost_min, cost_max = svc_details

        duration_hours = round(random.uniform(dur_min, dur_max), 1)

        # 5% chance: invoice not yet processed (cost = null)
        if svc == "recall" or random.random() < 0.05:
            cost_eur = ""
        else:
            cost_eur = round(random.uniform(cost_min, cost_max), 2)

        # Random date in the past 18 months
        svc_date = start_date + timedelta(days=random.randint(0, date_range - 1))

        # Status: mostly completed, some pending for recent dates
        if svc_date >= TODAY - timedelta(days=14):
            status = random.choice(["completed", "pending"])
        else:
            status = "completed" if random.random() < 0.92 else "cancelled"

        rows.append({
            "record_id":        record_id,
            "customer_id":      customer["customer_id"],
            "vehicle_id":       customer["owned_vehicle_id"],
            "service_type":     svc,
            "service_date":     svc_date.isoformat(),
            "technician_id":    technician[0],
            "technician_name":  f"{technician[1]} {technician[2]}",
            "duration_hours":   duration_hours,
            "cost_eur":         cost_eur,
            "status":           status,
        })
        record_id += 1

    # Sort by date for readability
    rows.sort(key=lambda r: r["service_date"])
    return rows


# ===========================================================================
# 6. PARTS CATALOG (JSON)
# EV-specific and general parts with brand/model compatibility arrays.
# Categories: Battery, Charging, Thermal, Brakes, Suspension, Interior, Exterior
#
# Noise:
#   - 3% of parts: lead_time_days = null  (supplier unknown)
# ===========================================================================

ALL_BRANDS  = ["Renault", "Volkswagen", "Kia", "Hyundai", "Audi", "Mercedes", "Alpine"]
BRAND_GROUPS = {
    "Korean":  ["Kia", "Hyundai"],
    "VW_Group": ["Volkswagen", "Audi"],
    "French":  ["Renault", "Alpine"],
    "Luxury":  ["Mercedes", "Audi", "Alpine"],
    "All":     ALL_BRANDS,
}

PARTS_DEFINITIONS = [
    # (name, category, compatible_brands_key, compatible_models, price_range, stock_range, lead_options, is_ev_specific)
    # Battery
    ("Battery Management System (BMS)",    "Battery",  "All",      [],                     (800,  2000), (2, 8),   [0, 7, 14],     True),
    ("High Voltage Battery Module 60kWh",  "Battery",  "Korean",   ["EV6", "IONIQ 5"],     (4500, 7000), (1, 3),   [14, 21],       True),
    ("High Voltage Battery Module 77kWh",  "Battery",  "VW_Group", ["ID.4", "ID.7", "Q4 e-tron"], (5500, 8500), (1, 2), [14, 21], True),
    ("12V Auxiliary Battery",              "Battery",  "All",      [],                     (120,  280),  (5, 15),  [0, 3],         False),
    ("Battery Cooling Plate",              "Battery",  "All",      [],                     (350,  700),  (2, 6),   [7, 14],        True),
    ("Battery Contactor Relay",            "Battery",  "All",      [],                     (180,  400),  (3, 10),  [0, 7],         True),

    # Charging
    ("Type 2 AC Charging Cable 7.4kW",     "Charging", "All",      [],                     (80,   180),  (8, 20),  [0],            True),
    ("Type 2 AC Charging Cable 11kW",      "Charging", "All",      [],                     (120,  250),  (8, 20),  [0],            True),
    ("CCS DC Fast Charging Adapter",       "Charging", "All",      [],                     (200,  450),  (4, 12),  [0, 7],         True),
    ("On-Board Charger (OBC) 11kW",        "Charging", "Korean",   [],                     (600, 1400),  (2, 5),   [7, 14],        True),
    ("On-Board Charger (OBC) 22kW",        "Charging", "Luxury",   ["A6 e-tron", "A390"],  (900, 1800),  (1, 3),   [14, 21],       True),
    ("DC-DC Converter",                    "Charging", "All",      [],                     (400,  900),  (2, 6),   [7, 14],        True),
    ("Charging Port Lock Actuator",        "Charging", "All",      [],                     (90,   200),  (5, 12),  [0, 7],         True),
    ("Wallbox Mounting Kit",               "Charging", "All",      [],                     (45,   120),  (10, 25), [0],            True),

    # Thermal
    ("Heat Pump Compressor",               "Thermal",  "All",      [],                     (900, 2200),  (1, 4),   [7, 14, 21],    True),
    ("Thermal Management Module",          "Thermal",  "All",      [],                     (500, 1200),  (2, 5),   [7, 14],        True),
    ("Coolant Pump (Electric)",            "Thermal",  "All",      [],                     (180,  400),  (4, 10),  [0, 7],         True),
    ("Cabin Air Filter",                   "Thermal",  "All",      [],                     (25,   65),   (15, 40), [0],            False),
    ("HVAC Blower Motor",                  "Thermal",  "All",      [],                     (120,  280),  (4, 10),  [0, 7],         False),

    # Brakes (EVs use regenerative braking — pads last longer)
    ("Brake Pad Set (Front) — EV spec",    "Brakes",   "All",      [],                     (80,   180),  (8, 20),  [0, 3],         False),
    ("Brake Pad Set (Rear) — EV spec",     "Brakes",   "All",      [],                     (70,   160),  (8, 20),  [0, 3],         False),
    ("Brake Disc Set (Front)",             "Brakes",   "All",      [],                     (180,  380),  (4, 10),  [0, 7],         False),
    ("Electronic Parking Brake Actuator",  "Brakes",   "All",      [],                     (220,  480),  (3, 8),   [7, 14],        False),

    # Suspension
    ("Air Suspension Compressor",          "Suspension","Luxury",  ["EQS", "EQE", "A6 e-tron"], (600, 1400), (1, 4), [7, 14],    False),
    ("Front Shock Absorber",               "Suspension","All",     [],                     (200,  500),  (3, 8),   [0, 7],         False),
    ("Rear Shock Absorber",                "Suspension","All",     [],                     (180,  450),  (3, 8),   [0, 7],         False),
    ("Control Arm (Front Left)",           "Suspension","All",     [],                     (150,  320),  (3, 8),   [0, 7],         False),
    ("Wheel Bearing Set",                  "Suspension","All",     [],                     (90,   220),  (5, 12),  [0, 7],         False),

    # Drivetrain / Motor
    ("Electric Motor Front",               "Drivetrain","All",     [],                     (2500, 5500), (1, 2),   [14, 21],       True),
    ("Electric Motor Rear",                "Drivetrain","All",     [],                     (2500, 5500), (1, 2),   [14, 21],       True),
    ("Reduction Gear Set",                 "Drivetrain","All",     [],                     (800, 1800),  (1, 3),   [14, 21],       True),
    ("CV Joint (Outer)",                   "Drivetrain","All",     [],                     (120,  280),  (5, 12),  [0, 7],         False),

    # Interior
    ("Touchscreen Display Unit 12\"",      "Interior", "VW_Group", ["ID.3","ID.4","ID.7"], (400,  900),  (2, 5),   [7, 14],        False),
    ("Instrument Cluster Display",         "Interior", "All",      [],                     (300,  700),  (2, 5),   [7, 14],        False),
    ("Door Handle (Flush type)",           "Interior", "Luxury",   [],                     (80,   200),  (4, 10),  [0, 7],         False),
    ("Seat Heating Element",               "Interior", "All",      [],                     (120,  280),  (5, 12),  [0, 7],         False),
    ("Steering Wheel Assembly",            "Interior", "All",      [],                     (250,  600),  (2, 5),   [7, 14],        False),

    # Exterior
    ("Front Bumper Assembly",              "Exterior", "All",      [],                     (400,  900),  (2, 6),   [7, 14],        False),
    ("Rear Bumper Assembly",               "Exterior", "All",      [],                     (380,  850),  (2, 6),   [7, 14],        False),
    ("LED Headlight Unit (Left)",          "Exterior", "All",      [],                     (500, 1200),  (2, 5),   [7, 14],        False),
    ("LED Headlight Unit (Right)",         "Exterior", "All",      [],                     (500, 1200),  (2, 5),   [7, 14],        False),
    ("Wing Mirror Assembly (Left)",        "Exterior", "All",      [],                     (180,  420),  (3, 8),   [0, 7],         False),
    ("Roof Rails Set",                     "Exterior", "All",      [],                     (200,  480),  (3, 8),   [0, 7],         False),
]

def generate_parts_catalog() -> list[dict]:
    parts = []

    for i, defn in enumerate(PARTS_DEFINITIONS, start=1):
        name, category, brand_group, specific_models, price_range, stock_range, lead_options, is_ev = defn

        # Resolve compatible brands
        comp_brands = BRAND_GROUPS.get(brand_group, ALL_BRANDS)

        # Resolve compatible models — empty means all models of those brands
        comp_models = specific_models if specific_models else []

        price       = round(random.uniform(*price_range), 2)
        stock_count = random.randint(*stock_range)

        # 3% chance lead_time_days = null (supplier unknown)
        if random.random() < 0.03:
            lead_time = None
        else:
            lead_time = random.choice(lead_options)
            # 0 means in stock and ships immediately

        parts.append({
            "part_id":           i,
            "part_name":         name,
            "category":          category,
            "compatible_brands": comp_brands,
            "compatible_models": comp_models,
            "price_eur":         price,
            "stock_count":       stock_count,
            "lead_time_days":    lead_time,
            "is_ev_specific":    is_ev,
        })

    return parts


# ===========================================================================
# Writers
# ===========================================================================
def write_csv(rows: list[dict], path: Path, fields: list[str]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ {path.name} — {len(rows)} rows")


def write_json(data: list, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  ✓ {path.name} — {len(data)} entries")


# ===========================================================================
# Main
# ===========================================================================
def main():
    print("=" * 60)
    print("OttO — Synthetic Data Generator")
    print(f"Reference date: {TODAY}  |  Seed: {SEED}")
    print("=" * 60)

    vehicles = load_vehicles()
    print(f"\nLoaded {len(vehicles)} vehicle variants from ev_specs_clean.csv")

    print("\n[1] Generating staff...")
    staff = generate_staff()
    write_csv(staff, SYNTH_DIR / "staff.csv", [
        "staff_id", "first_name", "last_name", "role", "department", "email", "phone",
    ])

    print("\n[2] Generating inventory...")
    inventory = generate_inventory(vehicles)
    write_csv(inventory, SYNTH_DIR / "inventory.csv", [
        "inventory_id", "vehicle_id", "brand", "model", "variant",
        "color", "stock_count", "is_demo_car", "dealer_price_eur", "available_from",
    ])

    print("\n[3] Generating customers...")
    customers = generate_customers(vehicles, n=150)
    write_csv(customers, SYNTH_DIR / "customers.csv", [
        "customer_id", "first_name", "last_name", "phone", "email",
        "owned_vehicle_id", "city",
    ])

    print("\n[4] Generating appointments...")
    appointments = generate_appointments(customers, vehicles)
    write_csv(appointments, SYNTH_DIR / "appointments.csv", [
        "slot_id", "slot_datetime", "duration_min", "type", "status",
        "staff_id", "staff_name", "customer_name", "customer_phone", "vehicle_id",
    ])

    print("\n[5] Generating service history...")
    service = generate_service_history(customers, n=200)
    write_csv(service, SYNTH_DIR / "service_history.csv", [
        "record_id", "customer_id", "vehicle_id", "service_type", "service_date",
        "technician_id", "technician_name", "duration_hours", "cost_eur", "status",
    ])

    print("\n[6] Generating parts catalog...")
    parts = generate_parts_catalog()
    write_json(parts, SYNTH_DIR / "parts_catalog.json")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print("Summary:")
    print(f"  Staff:           {len(staff)} employees")
    print(f"  Inventory:       {len(inventory)} stock entries")
    print(f"  Customers:       {len(customers)} profiles")
    print(f"  Appointments:    {len(appointments)} slots")
    print(f"  Service history: {len(service)} records")
    print(f"  Parts catalog:   {len(parts)} parts")

    blocked  = sum(1 for a in appointments if a["status"] == "blocked")
    booked   = sum(1 for a in appointments if a["status"] == "booked")
    available = sum(1 for a in appointments if a["status"] == "available")
    print(f"\n  Appointment breakdown:")
    print(f"    Available: {available} | Booked: {booked} | Blocked: {blocked}")

    sold_out = sum(1 for i in inventory if i["stock_count"] == 0)
    print(f"\n  Inventory sold-out entries: {sold_out} ({sold_out/len(inventory)*100:.1f}%)")

    null_cost = sum(1 for s in service if not s["cost_eur"])
    print(f"  Service records with null cost: {null_cost} ({null_cost/len(service)*100:.1f}%)")

    null_lead = sum(1 for p in parts if p["lead_time_days"] is None)
    print(f"  Parts with unknown lead time: {null_lead} ({null_lead/len(parts)*100:.1f}%)")
    print("=" * 60)


if __name__ == "__main__":
    main()
