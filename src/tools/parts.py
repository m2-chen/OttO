"""
src/tools/parts.py
Parts domain tools — catalog search and stock check.
"""

from sqlalchemy import text
from src.db.connection import engine


def find_parts(
    part_name: str | None = None,
    category: str | None = None,
    brand: str | None = None,
    model: str | None = None,
    in_stock_only: bool = True,
) -> list[dict]:
    """
    Search the parts catalog by name, category, or compatible vehicle.
    """
    filters = ["1=1"]
    params: dict = {}

    if part_name:
        filters.append("LOWER(p.part_name) LIKE LOWER(:part_name)")
        params["part_name"] = f"%{part_name}%"
    if category:
        filters.append("LOWER(p.category) = LOWER(:category)")
        params["category"] = category
    if brand:
        filters.append(":brand = ANY(p.compatible_brands)")
        params["brand"] = brand
    if model:
        filters.append("(:model = ANY(p.compatible_models) OR p.compatible_models = '{}')")
        params["model"] = model
    if in_stock_only:
        filters.append("p.stock_count > 0")

    where = " AND ".join(filters)

    query = text(f"""
        SELECT
            part_id, part_name, category,
            compatible_brands, compatible_models,
            price_eur, stock_count, lead_time_days,
            is_ev_specific
        FROM parts p
        WHERE {where}
        ORDER BY p.stock_count DESC, p.price_eur ASC
        LIMIT 8
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().fetchall()

    return [dict(r) for r in rows]


def check_part_stock(part_id: int) -> dict:
    """
    Get real-time stock and lead time for a specific part.
    """
    query = text("""
        SELECT part_id, part_name, stock_count, lead_time_days, price_eur
        FROM parts
        WHERE part_id = :part_id
    """)

    with engine.connect() as conn:
        row = conn.execute(query, {"part_id": part_id}).mappings().fetchone()

    if not row:
        return {"error": "Part not found."}

    result = dict(row)
    if result["stock_count"] > 0:
        result["availability"] = "in stock"
    elif result["lead_time_days"]:
        result["availability"] = f"order required — {result['lead_time_days']} day lead time"
    else:
        result["availability"] = "contact supplier for availability"

    return result
