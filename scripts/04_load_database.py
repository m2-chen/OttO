"""
04_load_database.py — OttO Data Pipeline, Step 4
Creates all tables and loads every dataset into PostgreSQL.

Load order matters — foreign keys must be satisfied:
  1. vehicles       (no dependencies)
  2. staff          (no dependencies)
  3. inventory      (→ vehicles)
  4. customers      (→ vehicles)
  5. appointments   (→ staff, vehicles)
  6. service_history(→ customers, vehicles, staff)
  7. parts          (no FK dependencies)
"""

import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Make sure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from src.db.connection import engine, Base
from src.db.models import (
    Vehicle, Inventory, Staff, Customer,
    Appointment, ServiceHistory, Part
)
from sqlalchemy.orm import Session

BASE_DIR  = Path(__file__).resolve().parent.parent
PROCESSED = BASE_DIR / "data" / "processed"
SYNTH     = BASE_DIR / "data" / "synthetic"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_int(val):
    try:
        return int(float(val)) if val not in (None, "") else None
    except (ValueError, TypeError):
        return None

def safe_float(val):
    try:
        return float(val) if val not in (None, "") else None
    except (ValueError, TypeError):
        return None

def safe_bool(val):
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes")

def safe_date(val):
    if not val:
        return None
    try:
        return date.fromisoformat(val[:10])
    except ValueError:
        return None

def safe_datetime(val):
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_vehicles(session: Session):
    print("  Loading vehicles...")
    rows = []
    with open(PROCESSED / "ev_specs_clean.csv", newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), start=1):
            rows.append(Vehicle(
                vehicle_id           = i,
                brand                = row["brand"],
                model                = row["model"],
                variant              = row["variant"],
                year                 = safe_int(row["year"]),
                body_type            = row["body_type"],
                drivetrain           = row["drivetrain"],
                seats                = safe_int(row["seats"]),
                battery_kwh          = safe_float(row["battery_kwh"]),
                range_wltp_km        = safe_int(row["range_wltp_km"]),
                ac_charging_kw       = safe_float(row["ac_charging_kw"]),
                dc_charging_kw       = safe_int(row["dc_charging_kw"]),
                acceleration_0_100_s = safe_float(row["acceleration_0_100_s"]),
                top_speed_kmh        = safe_int(row["top_speed_kmh"]),
                torque_nm            = safe_int(row["torque_nm"]),
                efficiency_wh_per_km = safe_int(row["efficiency_wh_per_km"]),
                cargo_l              = safe_int(row["cargo_l"]),
                towing_capacity_kg   = safe_int(row["towing_capacity_kg"]),
                length_mm            = safe_int(row["length_mm"]),
                width_mm             = safe_int(row["width_mm"]),
                height_mm            = safe_int(row["height_mm"]),
                weight_kg            = safe_int(row["weight_kg"]),
                base_price_eur       = safe_int(row["base_price_eur"]),
                source_url           = row["source_url"],
                specs_embedding      = None,   # populated by embedding pipeline later
            ))
    session.add_all(rows)
    session.flush()
    print(f"    ✓ {len(rows)} vehicles")


def load_staff(session: Session):
    print("  Loading staff...")
    rows = []
    with open(SYNTH / "staff.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(Staff(
                staff_id   = safe_int(row["staff_id"]),
                first_name = row["first_name"],
                last_name  = row["last_name"],
                role       = row["role"],
                department = row["department"],
                email      = row["email"],
                phone      = row["phone"],
            ))
    session.add_all(rows)
    session.flush()
    print(f"    ✓ {len(rows)} staff")


def load_inventory(session: Session):
    print("  Loading inventory...")
    rows = []
    with open(SYNTH / "inventory.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(Inventory(
                inventory_id     = safe_int(row["inventory_id"]),
                vehicle_id       = safe_int(row["vehicle_id"]),
                brand            = row["brand"],
                model            = row["model"],
                variant          = row["variant"],
                color            = row["color"],
                stock_count      = safe_int(row["stock_count"]),
                is_demo_car      = safe_bool(row["is_demo_car"]),
                dealer_price_eur = safe_int(row["dealer_price_eur"]),
                available_from   = safe_date(row["available_from"]),
            ))
    session.add_all(rows)
    session.flush()
    print(f"    ✓ {len(rows)} inventory entries")


def load_customers(session: Session):
    print("  Loading customers...")
    rows = []
    with open(SYNTH / "customers.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            owned = safe_int(row["owned_vehicle_id"])
            rows.append(Customer(
                customer_id      = safe_int(row["customer_id"]),
                first_name       = row["first_name"],
                last_name        = row["last_name"],
                phone            = row["phone"],
                email            = row["email"],
                owned_vehicle_id = owned,
                city             = row["city"],
            ))
    session.add_all(rows)
    session.flush()
    print(f"    ✓ {len(rows)} customers")


def load_appointments(session: Session):
    print("  Loading appointments...")
    rows = []
    with open(SYNTH / "appointments.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(Appointment(
                slot_id        = safe_int(row["slot_id"]),
                slot_datetime  = safe_datetime(row["slot_datetime"]),
                duration_min   = safe_int(row["duration_min"]),
                type           = row["type"],
                status         = row["status"],
                staff_id       = safe_int(row["staff_id"]),
                staff_name     = row["staff_name"],
                customer_name  = row["customer_name"] or None,
                customer_phone = row["customer_phone"] or None,
                vehicle_id     = safe_int(row["vehicle_id"]),
            ))
    session.add_all(rows)
    session.flush()
    print(f"    ✓ {len(rows)} appointment slots")


def load_service_history(session: Session):
    print("  Loading service history...")
    rows = []
    with open(SYNTH / "service_history.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(ServiceHistory(
                record_id       = safe_int(row["record_id"]),
                customer_id     = safe_int(row["customer_id"]),
                vehicle_id      = safe_int(row["vehicle_id"]),
                service_type    = row["service_type"],
                service_date    = safe_date(row["service_date"]),
                technician_id   = safe_int(row["technician_id"]),
                technician_name = row["technician_name"],
                duration_hours  = safe_float(row["duration_hours"]),
                cost_eur        = safe_float(row["cost_eur"]),
                status          = row["status"],
            ))
    session.add_all(rows)
    session.flush()
    print(f"    ✓ {len(rows)} service records")


def load_parts(session: Session):
    print("  Loading parts catalog...")
    rows = []
    with open(SYNTH / "parts_catalog.json", encoding="utf-8") as f:
        parts = json.load(f)
    for p in parts:
        rows.append(Part(
            part_id           = p["part_id"],
            part_name         = p["part_name"],
            category          = p["category"],
            compatible_brands = p["compatible_brands"],
            compatible_models = p["compatible_models"],
            price_eur         = p["price_eur"],
            stock_count       = p["stock_count"],
            lead_time_days    = p["lead_time_days"],
            is_ev_specific    = p["is_ev_specific"],
        ))
    session.add_all(rows)
    session.flush()
    print(f"    ✓ {len(rows)} parts")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("OttO — Database Loader")
    print("=" * 60)

    # Enable pgvector extension
    print("\n[0] Enabling pgvector extension...")
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    print("    ✓ pgvector ready")

    # Create all tables from ORM models
    print("\n[1] Creating tables...")
    Base.metadata.create_all(engine)
    print("    ✓ All tables created")

    # Load data in FK-safe order
    print("\n[2] Loading data...")
    with Session(engine) as session:
        load_vehicles(session)
        load_staff(session)
        load_inventory(session)
        load_customers(session)
        load_appointments(session)
        load_service_history(session)
        load_parts(session)
        session.commit()

    # Gate check — verify counts
    print("\n[3] Verification...")
    with engine.connect() as conn:
        tables = ["vehicles", "staff", "inventory", "customers",
                  "appointments", "service_history", "parts"]
        for table in tables:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"    {table}: {count} rows")

    print(f"\n{'=' * 60}")
    print("Database loaded successfully.")
    print("=" * 60)


if __name__ == "__main__":
    main()
