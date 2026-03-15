"""
06_update_prices_ranges.py
Updates vehicle prices and WLTP ranges in the database
based on verified March 2026 French market data.

For each model: (brand, model, base_price, range_wltp_km)
Two variants per model — lower range = base trim, higher range = top trim.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from src.db.connection import engine

# ---------------------------------------------------------------------------
# Corrections — (brand, model, base_price, base_range, top_price, top_range)
# Source: French market research, March 2026
# ---------------------------------------------------------------------------
UPDATES = [
    # brand              model               base_price  base_range  top_price   top_range
    ("Alpine",     "A290",             38700,      380,        38700,      380),
    ("Alpine",     "A390",             67500,      503,        72000,      557),
    ("Audi",       "Q4 e-tron",        46990,      388,        54990,      545),
    ("Audi",       "Q6 e-tron",        70900,      627,        79900,      639),
    ("Audi",       "A6 e-tron",        66500,      592,        77170,      757),
    ("Hyundai",    "KONA Electric",    36300,      377,        42900,      514),
    ("Hyundai",    "IONIQ 5",          45450,      420,        55900,      570),
    ("Hyundai",    "IONIQ 6",          52300,      429,        59900,      614),
    ("Hyundai",    "IONIQ 9",          69900,      620,        79900,      620),
    ("Kia",        "EV3",              35990,      436,        42990,      605),
    ("Kia",        "EV6",              43950,      428,        54950,      582),
    ("Kia",        "EV9",              64400,      443,        70400,      563),
    ("Mercedes",   "EQA",              46950,      426,        55950,      560),
    ("Mercedes",   "EQB",              46950,      389,        57950,      536),
    ("Mercedes",   "CLA",              48050,      541,        52900,      792),
    ("Mercedes",   "EQS",             105950,      780,       127250,      821),
    ("Renault",    "R5 E-Tech",        24990,      312,        33990,      410),
    ("Renault",    "R4 E-Tech",        29990,      308,        37990,      409),
    ("Renault",    "Megane E-Tech",    39500,      468,        39500,      468),
    ("Renault",    "Scenic E-Tech",    41990,      429,        51990,      625),
    ("Volkswagen", "ID.3",             34990,      388,        43990,      604),
    ("Volkswagen", "ID.4",             41500,      345,        54500,      550),
    ("Volkswagen", "ID.7",             53000,      615,        62000,      702),
    ("Volkswagen", "ID.Buzz",          52850,      420,        62850,      469),
]


def main():
    print("=" * 60)
    print("OttO — Vehicle Price & Range Update")
    print("=" * 60)

    with engine.begin() as conn:
        updated = 0

        for brand, model, base_price, base_range, top_price, top_range in UPDATES:

            # Get current rows for this model ordered by range ascending
            rows = conn.execute(text("""
                SELECT vehicle_id, range_wltp_km, base_price_eur
                FROM vehicles
                WHERE LOWER(brand) = LOWER(:brand)
                  AND LOWER(model) = LOWER(:model)
                ORDER BY range_wltp_km ASC
            """), {"brand": brand, "model": model}).fetchall()

            if not rows:
                print(f"  ✗ Not found: {brand} {model}")
                continue

            if len(rows) == 1:
                # Single variant
                conn.execute(text("""
                    UPDATE vehicles
                    SET base_price_eur = :price, range_wltp_km = :range
                    WHERE vehicle_id = :vid
                """), {"price": base_price, "range": base_range, "vid": rows[0][0]})
                updated += 1
                print(f"  ✓ {brand} {model} (single): price={base_price} range={base_range}km")

            else:
                # Base variant (lowest range)
                conn.execute(text("""
                    UPDATE vehicles
                    SET base_price_eur = :price, range_wltp_km = :range
                    WHERE vehicle_id = :vid
                """), {"price": base_price, "range": base_range, "vid": rows[0][0]})

                # Top variant (highest range)
                conn.execute(text("""
                    UPDATE vehicles
                    SET base_price_eur = :price, range_wltp_km = :range
                    WHERE vehicle_id = :vid
                """), {"price": top_price, "range": top_range, "vid": rows[-1][0]})

                updated += 2
                print(f"  ✓ {brand} {model}: base={base_price}€/{base_range}km | top={top_price}€/{top_range}km")

    print(f"\n{'=' * 60}")
    print(f"Updated {updated} vehicle rows.")
    print("=" * 60)


if __name__ == "__main__":
    main()
