"""
src/tools/sales.py
Sales domain tools — vehicle search and comparison.
Called by the OpenAI Realtime API when the customer asks about EVs.
"""

from sqlalchemy import text
from src.db.connection import engine


def search_vehicles(
    max_price_eur: int | None = None,
    min_range_km: int | None = None,
    brand: str | None = None,
    model: str | None = None,
    body_type: str | None = None,
    min_seats: int | None = None,
    drivetrain: str | None = None,
) -> list[dict]:
    """
    Search available vehicles matching the customer's criteria.
    Returns up to 5 matches with key specs and dealer price.
    """
    filters = ["1=1"]
    params = {}

    if max_price_eur:
        filters.append("v.base_price_eur <= :max_price")
        params["max_price"] = max_price_eur
    if min_range_km:
        filters.append("v.range_wltp_km >= :min_range")
        params["min_range"] = min_range_km
    if brand:
        filters.append("LOWER(v.brand) = LOWER(:brand)")
        params["brand"] = brand
    if model:
        filters.append("LOWER(v.model) LIKE LOWER(:model)")
        params["model"] = f"%{model}%"
    if body_type:
        # Normalise common aliases so they all match "Small Passenger Van"
        body_type_normalised = body_type.strip().lower()
        if body_type_normalised in ("mpv", "van", "minivan", "people carrier"):
            params["body_type"] = "%van%"
        else:
            params["body_type"] = f"%{body_type}%"
        filters.append("LOWER(v.body_type) LIKE LOWER(:body_type)")
    if min_seats:
        filters.append("v.seats >= :min_seats")
        params["min_seats"] = min_seats
    if drivetrain:
        filters.append("LOWER(v.drivetrain) = LOWER(:drivetrain)")
        params["drivetrain"] = drivetrain

    where = " AND ".join(filters)

    query = text(f"""
        SELECT
            v.brand, v.model, v.variant, v.year,
            v.body_type, v.drivetrain, v.seats,
            v.battery_kwh, v.range_wltp_km,
            v.dc_charging_kw, v.acceleration_0_100_s,
            v.base_price_eur,
            MIN(i.dealer_price_eur) AS dealer_price_eur,
            BOOL_OR(i.stock_count > 0) AS in_stock
        FROM vehicles v
        LEFT JOIN inventory i ON i.vehicle_id = v.vehicle_id
        WHERE {where}
        GROUP BY v.vehicle_id
        ORDER BY v.base_price_eur DESC
        LIMIT 10
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().fetchall()

    return [dict(r) for r in rows]


def get_vehicle_details(brand: str, model: str) -> dict | None:
    """
    Get full technical specs for a specific vehicle.
    Used when the customer wants to deep-dive on one model.
    """
    query = text("""
        SELECT
            v.*,
            ARRAY_AGG(DISTINCT i.color) FILTER (WHERE i.color IS NOT NULL) AS available_colors,
            SUM(i.stock_count) AS total_stock,
            MIN(i.dealer_price_eur) AS min_dealer_price,
            MAX(i.dealer_price_eur) AS max_dealer_price
        FROM vehicles v
        LEFT JOIN inventory i ON i.vehicle_id = v.vehicle_id
        WHERE LOWER(v.brand) = LOWER(:brand) AND LOWER(v.model) = LOWER(:model)
        GROUP BY v.vehicle_id
        ORDER BY v.base_price_eur ASC
        LIMIT 1
    """)

    with engine.connect() as conn:
        row = conn.execute(query, {"brand": brand, "model": model}).mappings().fetchone()

    return dict(row) if row else None


def compare_vehicles(vehicle_ids: list[int]) -> list[dict]:
    """
    Return side-by-side specs for a list of vehicle IDs.
    Used when the customer is torn between two or three models.
    """
    if not vehicle_ids:
        return []

    placeholders = ", ".join(f":id{i}" for i in range(len(vehicle_ids)))
    params = {f"id{i}": vid for i, vid in enumerate(vehicle_ids)}

    query = text(f"""
        SELECT
            vehicle_id, brand, model, variant,
            range_wltp_km, battery_kwh, dc_charging_kw,
            acceleration_0_100_s, seats, cargo_l,
            base_price_eur
        FROM vehicles
        WHERE vehicle_id IN ({placeholders})
        ORDER BY base_price_eur
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().fetchall()

    return [dict(r) for r in rows]
