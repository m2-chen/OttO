"""
src/tools/booking.py
Booking domain tools — appointment slots and reservations.
"""

from datetime import datetime
from sqlalchemy import text
from src.db.connection import engine


def list_available_slots(
    appointment_type: str = "test_drive",
    brand: str | None = None,
    model: str | None = None,
    days_ahead: int = 7,
) -> list[dict]:
    """
    List open appointment slots for the next N days.
    appointment_type: test_drive | maintenance | parts_fitting
    Optionally filter by vehicle brand/model for test drives.
    """
    vehicle_filter = ""
    params: dict = {
        "type": appointment_type,
        "now": datetime.now(),
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
) -> dict:
    """
    Reserve an appointment slot for a customer.
    Returns confirmation details or an error if already taken.
    """
    with engine.begin() as conn:
        # Check current status (row-level lock)
        row = conn.execute(
            text("SELECT status, slot_datetime, staff_name, type FROM appointments WHERE slot_id = :id FOR UPDATE"),
            {"id": slot_id}
        ).mappings().fetchone()

        if not row:
            return {"success": False, "error": "Slot not found."}
        if row["status"] != "available":
            return {"success": False, "error": f"Slot is already {row['status']}."}

        conn.execute(
            text("""
                UPDATE appointments
                SET status = 'booked',
                    customer_name  = :name,
                    customer_phone = :phone
                WHERE slot_id = :id
            """),
            {"id": slot_id, "name": customer_name, "phone": customer_phone}
        )

    return {
        "success": True,
        "slot_id": slot_id,
        "slot_datetime": str(row["slot_datetime"]),
        "appointment_type": row["type"],
        "staff_name": row["staff_name"],
        "customer_name": customer_name,
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
