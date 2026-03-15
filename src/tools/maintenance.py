"""
src/tools/maintenance.py
Maintenance domain tools — service history and diagnostics.
"""

from sqlalchemy import text
from src.db.connection import engine


def get_customer_service_history(
    customer_phone: str | None = None,
    customer_name: str | None = None,
) -> list[dict]:
    """
    Look up a customer's full service history.
    Identifies the customer by phone number or name.
    """
    if not customer_phone and not customer_name:
        return []

    filters = []
    params: dict = {}

    if customer_phone:
        filters.append("c.phone = :phone")
        params["phone"] = customer_phone
    if customer_name:
        filters.append("LOWER(CONCAT(c.first_name, ' ', c.last_name)) LIKE LOWER(:name)")
        params["name"] = f"%{customer_name}%"

    where = " OR ".join(filters)

    query = text(f"""
        SELECT
            sh.record_id,
            sh.service_type,
            sh.service_date,
            sh.technician_name,
            sh.duration_hours,
            sh.cost_eur,
            sh.status,
            v.brand AS vehicle_brand,
            v.model AS vehicle_model,
            v.year  AS vehicle_year
        FROM service_history sh
        JOIN customers c  ON sh.customer_id = c.customer_id
        JOIN vehicles  v  ON sh.vehicle_id  = v.vehicle_id
        WHERE {where}
        ORDER BY sh.service_date DESC
        LIMIT 10
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().fetchall()

    return [dict(r) for r in rows]


def get_next_service_recommendation(customer_phone: str) -> dict:
    """
    Based on last service date and type, recommend what's due next.
    Simple rule-based logic — no ML needed for a dealership assistant.
    """
    query = text("""
        SELECT sh.service_type, sh.service_date, v.brand, v.model
        FROM service_history sh
        JOIN customers c ON sh.customer_id = c.customer_id
        JOIN vehicles  v ON sh.vehicle_id  = v.vehicle_id
        WHERE c.phone = :phone
        ORDER BY sh.service_date DESC
        LIMIT 1
    """)

    with engine.connect() as conn:
        row = conn.execute(query, {"phone": customer_phone}).mappings().fetchone()

    if not row:
        return {"recommendation": "No service history found. Please book an initial inspection."}

    from datetime import date
    days_since = (date.today() - row["service_date"]).days

    if days_since > 365:
        next_service = "annual_service"
        urgency = "overdue"
    elif days_since > 300:
        next_service = "annual_service"
        urgency = "due soon"
    else:
        next_service = "battery_check"
        urgency = "optional"

    return {
        "vehicle": f"{row['brand']} {row['model']}",
        "last_service_type": row["service_type"],
        "last_service_date": str(row["service_date"]),
        "days_since_last_service": days_since,
        "recommended_next_service": next_service,
        "urgency": urgency,
    }
