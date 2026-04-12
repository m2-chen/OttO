"""
src/tools/booking.py
Booking domain tools — appointment slots and reservations.

Slots are generated dynamically: list_available_slots() auto-extends the
appointments table whenever coverage falls short of today + days_ahead.
This means the calendar is always current regardless of when the app runs.
"""

import random
from datetime import date, time, datetime, timedelta

from sqlalchemy import text
from src.db.connection import engine


# ---------------------------------------------------------------------------
# Static config — mirrors the original synthetic data generator
# ---------------------------------------------------------------------------

SLOT_TEMPLATES = [
    # (start_time, duration_min, appt_type, department)
    # --- Morning test drives (every 30 min, 9am–12pm) ---
    (time(9,  0),  30,  "test_drive",    "Sales"),
    (time(9, 30),  30,  "test_drive",    "Sales"),
    (time(10, 0),  30,  "test_drive",    "Sales"),
    (time(10, 30), 30,  "test_drive",    "Sales"),
    (time(11, 0),  30,  "test_drive",    "Sales"),
    (time(11, 30), 30,  "test_drive",    "Sales"),
    # --- Morning maintenance (every hour, 9am–12pm) ---
    (time(9,  0),  60,  "maintenance",   "Maintenance"),
    (time(10, 0),  60,  "maintenance",   "Maintenance"),
    (time(11, 0),  60,  "maintenance",   "Maintenance"),
    # --- Afternoon test drives (every 30 min, 1:30pm–5:30pm) ---
    (time(13, 30), 30,  "test_drive",    "Sales"),
    (time(14, 0),  30,  "test_drive",    "Sales"),
    (time(14, 30), 30,  "test_drive",    "Sales"),
    (time(15, 0),  30,  "test_drive",    "Sales"),
    (time(15, 30), 30,  "test_drive",    "Sales"),
    (time(16, 0),  30,  "test_drive",    "Sales"),
    (time(16, 30), 30,  "test_drive",    "Sales"),
    (time(17, 0),  30,  "test_drive",    "Sales"),
    # --- Afternoon maintenance (every hour, 1pm–5pm) ---
    (time(13, 0),  60,  "maintenance",   "Maintenance"),
    (time(14, 0),  60,  "maintenance",   "Maintenance"),
    (time(15, 0),  60,  "maintenance",   "Maintenance"),
    (time(16, 0),  60,  "maintenance",   "Maintenance"),
    # --- Parts fitting (morning + afternoon) ---
    (time(10, 0),  60,  "parts_fitting", "Parts"),
    (time(11, 0),  60,  "parts_fitting", "Parts"),
    (time(14, 0),  60,  "parts_fitting", "Parts"),
    (time(15, 0),  60,  "parts_fitting", "Parts"),
    (time(16, 0),  60,  "parts_fitting", "Parts"),
]

STAFF_BY_DEPT = {
    "Sales":       [(1, "Thomas", "Lefebvre"), (2, "Marie", "Dubois"), (3, "Carlos", "Romero"),
                    (9, "Léa", "Fontaine"), (10, "Youssef", "Benhamou")],
    "Maintenance": [(4, "Lukas", "Schneider"), (5, "Amira", "Benali"), (7, "Pieter", "Van den Berg"),
                    (11, "Nadia", "Okonkwo"), (12, "Romain", "Descamps")],
    "Parts":       [(6, "Sophie", "Martin"), (13, "Fatima", "El Idrissi")],
}


# ---------------------------------------------------------------------------
# Calendar auto-extension
# ---------------------------------------------------------------------------

def _extend_calendar_if_needed(days_ahead: int = 45) -> None:
    """
    Ensure every day from today through today + days_ahead has available slots.
    Checks day by day — skips days that already have slots (any status).
    Skips Sundays. Staff is assigned deterministically per slot.
    """
    today = date.today()
    target_end = today + timedelta(days=days_ahead)

    with engine.begin() as conn:
        # Fetch all (date, time, type) combos that already exist
        rows = conn.execute(text("""
            SELECT slot_datetime, type
            FROM appointments
            WHERE slot_datetime::date >= :today AND slot_datetime::date <= :end
        """), {"today": today, "end": target_end}).fetchall()
        existing = {(r[0].date(), r[0].time(), r[1]) for r in rows}

        max_id_row = conn.execute(
            text("SELECT COALESCE(MAX(slot_id), 0) FROM appointments")
        ).fetchone()
        slot_id = max_id_row[0] + 1

        current = today
        while current <= target_end:
            if current.weekday() == 6:  # skip Sundays
                current += timedelta(days=1)
                continue

            for (start_t, duration, appt_type, dept) in SLOT_TEMPLATES:
                slot_dt = datetime.combine(current, start_t)

                # Skip if this exact slot already exists
                if (current, start_t, appt_type) in existing:
                    continue

                # Deterministic staff pick — same slot always gets same advisor
                seed = int(slot_dt.strftime("%Y%m%d%H%M")) + sum(ord(c) for c in dept)
                rng = random.Random(seed)
                staff = rng.choice(STAFF_BY_DEPT[dept])

                status = "blocked" if rng.random() < 0.12 else "available"

                conn.execute(text("""
                    INSERT INTO appointments
                        (slot_id, slot_datetime, duration_min, type, status,
                         staff_id, staff_name, customer_name, customer_phone, vehicle_id)
                    VALUES
                        (:slot_id, :slot_dt, :dur, :type, :status,
                         :staff_id, :staff_name, NULL, NULL, NULL)
                """), {
                    "slot_id":    slot_id,
                    "slot_dt":    slot_dt,
                    "dur":        duration,
                    "type":       appt_type,
                    "status":     status,
                    "staff_id":   staff[0],
                    "staff_name": f"{staff[1]} {staff[2]}",
                })
                slot_id += 1

            current += timedelta(days=1)


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

def list_available_slots(
    appointment_type: str = "test_drive",
    brand: str | None = None,
    model: str | None = None,
    days_ahead: int = 7,
) -> list[dict]:
    """
    List open appointment slots for the next N days.
    Auto-extends the calendar if needed so results are always current.
    appointment_type: test_drive | maintenance | parts_fitting
    """
    _extend_calendar_if_needed(days_ahead=max(days_ahead, 45))

    vehicle_filter = ""
    params: dict = {
        "type": appointment_type,
        "now":  datetime.now(),
        "days_ahead": days_ahead,
    }

    if brand or model:
        vehicle_filter = "JOIN vehicles v ON a.vehicle_id = v.vehicle_id"
        if brand:
            vehicle_filter += " AND LOWER(v.brand) = LOWER(:brand)"
            params["brand"] = brand
        if model:
            vehicle_filter += " AND LOWER(v.model) = LOWER(:model)"
            params["model"] = model

    query = text(f"""
        SELECT
            a.slot_id,
            a.slot_datetime,
            a.duration_min,
            a.type,
            a.staff_name,
            v.brand AS vehicle_brand,
            v.model AS vehicle_model
        FROM appointments a
        LEFT JOIN vehicles v ON a.vehicle_id = v.vehicle_id
        WHERE a.type = :type
          AND a.status = 'available'
          AND a.slot_datetime >= :now
          AND a.slot_datetime <= :now + INTERVAL '1 day' * :days_ahead
        ORDER BY a.slot_datetime
        LIMIT 10
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().fetchall()

    return [dict(r) for r in rows]


def book_slot(
    slot_id: int,
    customer_name: str,
    customer_phone: str,
    customer_email: str | None = None,
) -> dict:
    """
    Reserve an appointment slot for a customer.
    Returns confirmation details or an error if already taken.
    """
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT status, slot_datetime, staff_name, type FROM appointments WHERE slot_id = :id FOR UPDATE"),
            {"id": slot_id}
        ).mappings().fetchone()

        if not row:
            return {"success": False, "error": "Slot not found."}
        if row["status"] != "available":
            return {"success": False, "error": f"Slot is already {row['status']}."}

        conn.execute(text("""
            UPDATE appointments
            SET status         = 'booked',
                customer_name  = :name,
                customer_phone = :phone
            WHERE slot_id = :id
        """), {"id": slot_id, "name": customer_name, "phone": customer_phone})

    return {
        "success":          True,
        "slot_id":          slot_id,
        "slot_datetime":    str(row["slot_datetime"]),
        "appointment_type": row["type"],
        "staff_name":       row["staff_name"],
        "customer_name":    customer_name,
        "customer_phone":   customer_phone,
        "customer_email":   customer_email,
    }


def cancel_slot(slot_id: int, customer_phone: str) -> dict:
    """
    Cancel a booking by slot ID, verified by customer phone.
    """
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT status, customer_phone FROM appointments WHERE slot_id = :id FOR UPDATE"),
            {"id": slot_id}
        ).mappings().fetchone()

        if not row:
            return {"success": False, "error": "Slot not found."}
        if row["status"] != "booked":
            return {"success": False, "error": "This slot is not booked."}
        if row["customer_phone"] != customer_phone:
            return {"success": False, "error": "Phone number does not match booking."}

        conn.execute(
            text("UPDATE appointments SET status='available', customer_name=NULL, customer_phone=NULL WHERE slot_id=:id"),
            {"id": slot_id}
        )

    return {"success": True, "message": "Appointment cancelled successfully."}
