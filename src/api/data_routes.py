"""
src/api/data_routes.py
REST API endpoints for the EV Land website.
Serves vehicle and parts data as JSON for frontend pages.
"""

from decimal import Decimal
from datetime import date, datetime
from typing import Annotated
from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import text
from src.db.connection import engine

data_router = APIRouter(prefix="/api")

# ---------------------------------------------------------------------------
# Image map: (brand.lower(), model.lower()) → filename in /static/images/
# ---------------------------------------------------------------------------
IMAGE_MAP = {
    ("alpine",     "a290"):           "Alpine_A290.jpg",
    ("alpine",     "a390"):           "Alpine_A390.jpg",
    ("audi",       "q4 e-tron"):      "Audi_Q4_e-tron.jpg",
    ("audi",       "q6 e-tron"):      "Audi_Q6_e-tron.jpg",
    ("audi",       "a6 e-tron"):      "Audi-A6-e-tron-2024.jpg",
    ("hyundai",    "kona electric"):  "hyundai-kona-electric.jpg",
    ("hyundai",    "ioniq 5"):        "Hyundai-Ioniq-5.jpg",
    ("hyundai",    "ioniq 6"):        "hyundai-Ioniq-6.jpg",
    ("hyundai",    "ioniq 9"):        "hyundai-ioniq-9.jpg",
    ("kia",        "ev3"):            "Kia-EV3.jpg",
    ("kia",        "ev6"):            "Kia-EV-6.jpeg",
    ("kia",        "ev9"):            "Kia-EV-9.jpg",
    ("mercedes",   "eqa"):            "mercedes-eqa.jpg",
    ("mercedes",   "eqb"):            "mercedes-eqb.jpg",
    ("mercedes",   "cla"):            "mercedes-CLA.jpg",
    ("mercedes",   "eqs"):            "mercedes-eqs.jpg",
    ("renault",    "r5 e-tech"):      "renault-r5-e-tech.jpg",
    ("renault",    "r4 e-tech"):      "renault-r4-e-tech.jpg",
    ("renault",    "megane e-tech"):  "renault-megane-etech.jpg",
    ("renault",    "scenic e-tech"):  "renault-scenic-e-tech.jpg",
    ("volkswagen", "id.3"):           "volkswagen-id3.jpg",
    ("volkswagen", "id.4"):           "volkswagen-id.4.jpg",
    ("volkswagen", "id.7"):           "Volkswagen-ID7-DriveOne.jpg",
    ("volkswagen", "id.buzz"):        "volkswagen-id-buzz.jpg",
}


def _serialize(obj):
    """Recursively convert DB types to JSON-safe primitives."""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj


def _with_image(row: dict) -> dict:
    key = (row["brand"].lower(), row["model"].lower())
    filename = IMAGE_MAP.get(key)
    row["image"] = f"/static/images/{filename}" if filename else None
    return row


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

@data_router.get("/vehicles")
def list_vehicles(brand: Annotated[str | None, Query()] = None):
    """
    Return one card per model (cheapest variant as representative).
    Includes from_price, max_range, and in_stock flag.
    """
    joined_filter = "AND LOWER(v.brand) = LOWER(:brand)" if brand else ""
    plain_filter  = "AND LOWER(brand)   = LOWER(:brand)" if brand else ""
    params = {"brand": brand} if brand else {}

    query = text(f"""
        WITH model_summary AS (
            SELECT
                v.brand,
                v.model,
                MIN(v.base_price_eur)        AS from_price,
                MAX(v.range_wltp_km)         AS max_range_km,
                BOOL_OR(i.stock_count > 0)   AS in_stock
            FROM vehicles v
            LEFT JOIN inventory i ON i.vehicle_id = v.vehicle_id
            WHERE 1=1 {joined_filter}
            GROUP BY v.brand, v.model
        ),
        base_variant AS (
            SELECT DISTINCT ON (brand, model)
                vehicle_id, brand, model, body_type, seats,
                battery_kwh, acceleration_0_100_s, dc_charging_kw
            FROM vehicles
            WHERE 1=1 {plain_filter}
            ORDER BY brand, model, base_price_eur ASC
        )
        SELECT
            bv.vehicle_id, bv.brand, bv.model, bv.body_type, bv.seats,
            bv.battery_kwh, bv.acceleration_0_100_s, bv.dc_charging_kw,
            ms.from_price, ms.max_range_km, ms.in_stock
        FROM base_variant bv
        JOIN model_summary ms ON ms.brand = bv.brand AND ms.model = bv.model
        ORDER BY bv.brand, ms.from_price
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().fetchall()

    return [_with_image(_serialize(dict(r))) for r in rows]


@data_router.get("/vehicles/{vehicle_id}")
def get_vehicle(vehicle_id: int):
    """Full specs for a specific vehicle variant."""
    query = text("""
        SELECT
            v.*,
            ARRAY_AGG(DISTINCT i.color ORDER BY i.color)
                FILTER (WHERE i.color IS NOT NULL) AS colors,
            SUM(i.stock_count)          AS total_stock,
            MIN(i.dealer_price_eur)     AS min_dealer_price,
            MAX(i.dealer_price_eur)     AS max_dealer_price
        FROM vehicles v
        LEFT JOIN inventory i ON i.vehicle_id = v.vehicle_id
        WHERE v.vehicle_id = :vid
        GROUP BY v.vehicle_id
    """)

    # Also fetch sibling variants (same brand+model)
    sibling_query = text("""
        SELECT vehicle_id, variant, base_price_eur, range_wltp_km, battery_kwh
        FROM vehicles
        WHERE brand = (SELECT brand FROM vehicles WHERE vehicle_id = :vid)
          AND model = (SELECT model FROM vehicles WHERE vehicle_id = :vid)
        ORDER BY base_price_eur ASC
    """)

    with engine.connect() as conn:
        row = conn.execute(query, {"vid": vehicle_id}).mappings().fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        siblings = conn.execute(sibling_query, {"vid": vehicle_id}).mappings().fetchall()

    result = _with_image(_serialize(dict(row)))
    result["variants"] = _serialize([dict(s) for s in siblings])
    return result


@data_router.get("/brands")
def list_brands():
    """Return sorted list of brand names."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT brand FROM vehicles ORDER BY brand")).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------

@data_router.get("/parts")
def list_parts(
    q: Annotated[str | None, Query(description="Search by name")] = None,
    category: Annotated[str | None, Query()] = None,
    in_stock_only: Annotated[bool, Query()] = False,
):
    filters = ["1=1"]
    params: dict = {}

    if q:
        filters.append("LOWER(part_name) LIKE LOWER(:q)")
        params["q"] = f"%{q}%"
    if category:
        filters.append("LOWER(category) = LOWER(:category)")
        params["category"] = category
    if in_stock_only:
        filters.append("stock_count > 0")

    where = " AND ".join(filters)
    query = text(f"""
        SELECT part_id, part_name, category,
               compatible_brands, compatible_models,
               price_eur, stock_count, lead_time_days, is_ev_specific
        FROM parts
        WHERE {where}
        ORDER BY stock_count DESC, price_eur ASC
        LIMIT 100
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().fetchall()

    return _serialize([dict(r) for r in rows])


@data_router.get("/parts/categories")
def list_part_categories():
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT category FROM parts ORDER BY category")
        ).fetchall()
    return [r[0] for r in rows]
