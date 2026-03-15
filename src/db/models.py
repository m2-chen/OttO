"""
src/db/models.py
SQLAlchemy ORM models — one class per database table.

Tables:
  vehicles        — 48 EV variants (specs + pgvector embedding)
  inventory       — stock entries per variant (color, price, availability)
  staff           — 8 EV Land employees
  customers       — 150 CRM profiles
  appointments    — 45-day booking calendar
  service_history — 18 months of past maintenance records
  parts           — EV parts catalog
"""

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float,
    ForeignKey, Integer, Numeric, String, Text
)
from sqlalchemy.dialects.postgresql import ARRAY
from pgvector.sqlalchemy import Vector

from src.db.connection import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    vehicle_id              = Column(Integer, primary_key=True, index=True)
    brand                   = Column(String(50),  nullable=False)
    model                   = Column(String(100), nullable=False)
    variant                 = Column(String(100))
    year                    = Column(Integer)
    body_type               = Column(String(50))
    drivetrain              = Column(String(10))   # FWD / RWD / AWD
    seats                   = Column(Integer)
    battery_kwh             = Column(Numeric(5, 1))
    range_wltp_km           = Column(Integer)
    ac_charging_kw          = Column(Numeric(4, 1))
    dc_charging_kw          = Column(Integer)
    acceleration_0_100_s    = Column(Numeric(4, 1))
    top_speed_kmh           = Column(Integer)
    torque_nm               = Column(Integer)
    efficiency_wh_per_km    = Column(Integer)
    cargo_l                 = Column(Integer)
    towing_capacity_kg      = Column(Integer)
    length_mm               = Column(Integer)
    width_mm                = Column(Integer)
    height_mm               = Column(Integer)
    weight_kg               = Column(Integer)
    base_price_eur          = Column(Integer)
    source_url              = Column(Text)
    specs_embedding         = Column(Vector(1536), nullable=True)  # pgvector — populated later


class Inventory(Base):
    __tablename__ = "inventory"

    inventory_id        = Column(Integer, primary_key=True, index=True)
    vehicle_id          = Column(Integer, ForeignKey("vehicles.vehicle_id"), nullable=False)
    brand               = Column(String(50))
    model               = Column(String(100))
    variant             = Column(String(100))
    color               = Column(String(50))
    stock_count         = Column(Integer, default=0)
    is_demo_car         = Column(Boolean, default=False)
    dealer_price_eur    = Column(Integer)
    available_from      = Column(Date)


class Staff(Base):
    __tablename__ = "staff"

    staff_id    = Column(Integer, primary_key=True, index=True)
    first_name  = Column(String(50))
    last_name   = Column(String(50))
    role        = Column(String(100))
    department  = Column(String(50))   # Sales / Maintenance / Parts / Management
    email       = Column(String(100))
    phone       = Column(String(30))


class Customer(Base):
    __tablename__ = "customers"

    customer_id         = Column(Integer, primary_key=True, index=True)
    first_name          = Column(String(50))
    last_name           = Column(String(50))
    phone               = Column(String(30))
    email               = Column(String(100))
    owned_vehicle_id    = Column(Integer, ForeignKey("vehicles.vehicle_id"), nullable=True)
    city                = Column(String(100))


class Appointment(Base):
    __tablename__ = "appointments"

    slot_id         = Column(Integer, primary_key=True, index=True)
    slot_datetime   = Column(DateTime, nullable=False)
    duration_min    = Column(Integer)
    type            = Column(String(30))    # test_drive / maintenance / parts_fitting
    status          = Column(String(20), default="available")  # available / booked / blocked
    staff_id        = Column(Integer, ForeignKey("staff.staff_id"))
    staff_name      = Column(String(100))
    customer_name   = Column(String(100))
    customer_phone  = Column(String(30))
    vehicle_id      = Column(Integer, ForeignKey("vehicles.vehicle_id"), nullable=True)


class ServiceHistory(Base):
    __tablename__ = "service_history"

    record_id       = Column(Integer, primary_key=True, index=True)
    customer_id     = Column(Integer, ForeignKey("customers.customer_id"))
    vehicle_id      = Column(Integer, ForeignKey("vehicles.vehicle_id"))
    service_type    = Column(String(50))   # annual_service / battery_check / etc.
    service_date    = Column(Date)
    technician_id   = Column(Integer, ForeignKey("staff.staff_id"))
    technician_name = Column(String(100))
    duration_hours  = Column(Numeric(4, 1))
    cost_eur        = Column(Numeric(8, 2), nullable=True)   # nullable = invoice pending
    status          = Column(String(20))   # completed / pending / cancelled


class Part(Base):
    __tablename__ = "parts"

    part_id             = Column(Integer, primary_key=True, index=True)
    part_name           = Column(String(150))
    category            = Column(String(50))
    compatible_brands   = Column(ARRAY(String))   # PostgreSQL native array
    compatible_models   = Column(ARRAY(String))
    price_eur           = Column(Numeric(8, 2))
    stock_count         = Column(Integer)
    lead_time_days      = Column(Integer, nullable=True)   # null = supplier unknown
    is_ev_specific      = Column(Boolean, default=True)
