"""
05_sanity_check.py — OttO Phase 1 Validation
Fast database sanity check before starting Phase 2.

Checks:
  1. Row counts vs expected values
  2. FK integrity (no orphaned records)
  3. One agent-readiness query per specialist domain
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from src.db.connection import engine

EXPECTED = {
    "vehicles":        48,
    "staff":            8,
    "inventory":      112,
    "customers":      150,
    "appointments":   532,
    "service_history": 200,
    "parts":           43,
}

PASS = "  ✓"
FAIL = "  ✗"

errors = 0


def check(label, ok, detail=""):
    global errors
    status = PASS if ok else FAIL
    print(f"{status}  {label}" + (f"  →  {detail}" if detail else ""))
    if not ok:
        errors += 1


with engine.connect() as c:

    # ------------------------------------------------------------------
    # 1. Row counts
    # ------------------------------------------------------------------
    print("\n[1] Row counts")
    for table, expected in EXPECTED.items():
        actual = c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        check(f"{table}: {actual}", actual == expected,
              f"expected {expected}" if actual != expected else "")

    # ------------------------------------------------------------------
    # 2. FK integrity
    # ------------------------------------------------------------------
    print("\n[2] FK integrity")

    orphaned = c.execute(text(
        "SELECT COUNT(*) FROM inventory i "
        "LEFT JOIN vehicles v ON i.vehicle_id = v.vehicle_id "
        "WHERE v.vehicle_id IS NULL"
    )).scalar()
    check("inventory → vehicles", orphaned == 0, f"{orphaned} orphans")

    orphaned = c.execute(text(
        "SELECT COUNT(*) FROM customers c "
        "LEFT JOIN vehicles v ON c.owned_vehicle_id = v.vehicle_id "
        "WHERE c.owned_vehicle_id IS NOT NULL AND v.vehicle_id IS NULL"
    )).scalar()
    check("customers → vehicles", orphaned == 0, f"{orphaned} orphans")

    orphaned = c.execute(text(
        "SELECT COUNT(*) FROM appointments a "
        "LEFT JOIN staff s ON a.staff_id = s.staff_id "
        "WHERE s.staff_id IS NULL"
    )).scalar()
    check("appointments → staff", orphaned == 0, f"{orphaned} orphans")

    orphaned = c.execute(text(
        "SELECT COUNT(*) FROM service_history sh "
        "LEFT JOIN customers c ON sh.customer_id = c.customer_id "
        "WHERE c.customer_id IS NULL"
    )).scalar()
    check("service_history → customers", orphaned == 0, f"{orphaned} orphans")

    # ------------------------------------------------------------------
    # 3. Agent-readiness queries
    # ------------------------------------------------------------------
    print("\n[3] Agent-readiness")

    # Sales Agent — find EVs under 40k with 400+ km range
    rows = c.execute(text(
        "SELECT brand, model, base_price_eur, range_wltp_km "
        "FROM vehicles "
        "WHERE base_price_eur < 40000 AND range_wltp_km >= 400 "
        "ORDER BY base_price_eur LIMIT 3"
    )).fetchall()
    check(f"Sales: EVs <40k EUR, 400+ km range ({len(rows)} found)", len(rows) > 0,
          str([(r[0], r[1], r[2]) for r in rows]))

    # Booking Agent — next 3 available test-drive slots
    rows = c.execute(text(
        "SELECT slot_datetime, staff_name, vehicle_id "
        "FROM appointments "
        "WHERE type = 'test_drive' AND status = 'available' "
        "ORDER BY slot_datetime LIMIT 3"
    )).fetchall()
    check(f"Booking: available test-drive slots ({len(rows)} found)", len(rows) > 0,
          str([(str(r[0])[:16], r[1]) for r in rows]))

    # Maintenance Agent — customer + last service lookup
    rows = c.execute(text(
        "SELECT c.first_name, c.last_name, sh.service_type, sh.service_date "
        "FROM service_history sh "
        "JOIN customers c ON sh.customer_id = c.customer_id "
        "ORDER BY sh.service_date DESC LIMIT 3"
    )).fetchall()
    check(f"Maintenance: service history join ({len(rows)} records)", len(rows) > 0,
          str([(r[0], r[1], r[2]) for r in rows]))

    # Parts Agent — EV-specific parts in stock
    rows = c.execute(text(
        "SELECT part_name, stock_count, price_eur "
        "FROM parts "
        "WHERE is_ev_specific = TRUE AND stock_count > 0 "
        "ORDER BY price_eur DESC LIMIT 3"
    )).fetchall()
    check(f"Parts: EV-specific in-stock parts ({len(rows)} found)", len(rows) > 0,
          str([(r[0][:30], r[1]) for r in rows]))

# ------------------------------------------------------------------
# Result
# ------------------------------------------------------------------
print(f"\n{'=' * 50}")
if errors == 0:
    print("ALL CHECKS PASSED — database is Phase 2 ready.")
else:
    print(f"{errors} CHECK(S) FAILED — fix before proceeding.")
print("=" * 50)

sys.exit(0 if errors == 0 else 1)
