"""
scripts/16_extract_catalog_photos.py

Extract clean embedded photos from all catalog PDFs using PyMuPDF.

What this does:
- Opens each catalog PDF page by page
- Extracts embedded raster images (the original clean photos, no text overlay)
- Filters out small images (icons, logos, decorative elements)
- Saves to data/rag/photos/{brand}_{model}/page_{num}_img_{i}.jpg
- Stores paths in a new `catalog_photos` table mapped to RAG page rows

Run:
    python scripts/16_extract_catalog_photos.py
    python scripts/16_extract_catalog_photos.py --brand Kia --model EV6   # single catalog
"""

import argparse
import os
import re
import time
from pathlib import Path

import fitz  # PyMuPDF
import psycopg2

# ── Config ────────────────────────────────────────────────────────────────────

PDF_DIR   = Path("/Users/mehdichenini/Desktop/Car_Manuals")
PHOTO_DIR = Path("data/rag/photos")

# Minimum dimensions to keep — filters out icons, logos, decorative elements
MIN_WIDTH  = 400   # px
MIN_HEIGHT = 250   # px
MIN_SIZE_KB = 20   # KB — skip tiny compressed thumbnails

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5434")),
    "dbname":   os.getenv("DB_NAME",     "otto"),
    "user":     os.getenv("DB_USER",     "otto"),
    "password": os.getenv("DB_PASSWORD", "otto"),
}

# Full catalog manifest
CATALOGS = [
    {"brand": "Renault",       "model": "R5 E-Tech",           "pdf": "R5-Catalog.pdf"},
    {"brand": "Renault",       "model": "R4 E-Tech",           "pdf": "R4-E-Tech-Catalog.pdf"},
    {"brand": "Renault",       "model": "Megane E-Tech",        "pdf": "R-Megane-E-Tech.pdf"},
    {"brand": "Renault",       "model": "Scenic E-Tech",        "pdf": "Renault-Scenic-E-Tech-Catalog-IE.pdf"},
    {"brand": "Volkswagen",    "model": "ID.3",                 "pdf": "VW-ID-3-Catalog.pdf"},
    {"brand": "Volkswagen",    "model": "ID.4",                 "pdf": "VW-ID.4-catalog.pdf"},
    {"brand": "Volkswagen",    "model": "ID.7",                 "pdf": "VW-ID7-Catalog.pdf"},
    {"brand": "Volkswagen",    "model": "ID.Buzz",              "pdf": "ID-Buzz-Catalog.pdf"},
    {"brand": "Kia",           "model": "EV3",                  "pdf": "Kia-EV3-Catalog.pdf"},
    {"brand": "Kia",           "model": "EV6",                  "pdf": "Kia-EV6-Catalog.pdf"},
    {"brand": "Kia",           "model": "EV9",                  "pdf": "kia_catalog_ev9.pdf"},
    {"brand": "Hyundai",       "model": "IONIQ 5",              "pdf": "IONIQ_5_Brochure.pdf"},
    {"brand": "Hyundai",       "model": "IONIQ 6",              "pdf": "brochure_ioniq6_.pdf"},
    {"brand": "Hyundai",       "model": "IONIQ 9",              "pdf": "Hyundai_IONIQ-9_.catalog.pdf"},
    {"brand": "Hyundai",       "model": "KONA Electric",        "pdf": "KONA-EV-Brochure.pdf"},
    {"brand": "Audi",          "model": "Q4 e-tron",            "pdf": "q4-e-tron_catalog.pdf"},
    {"brand": "Audi",          "model": "Q6 e-tron",            "pdf": "q6-e-tron_catalog.pdf"},
    {"brand": "Audi",          "model": "A6 e-tron",            "pdf": "a6-sportback-e-tron-Catalog.pdf"},
    {"brand": "Mercedes-Benz", "model": "EQA",                  "pdf": "Mercedes-EQA-Catalog.pdf"},
    {"brand": "Mercedes-Benz", "model": "EQB",                  "pdf": "Mercedes-EQB-Catalog.pdf"},
    {"brand": "Mercedes-Benz", "model": "EQS",                  "pdf": "Mercedes-EQS-Catalog-IN.pdf"},
    {"brand": "Mercedes-Benz", "model": "CLA",                  "pdf": "Mercedes-CLA-Catalog.pdf"},
    {"brand": "Alpine",        "model": "A290",                 "pdf": "Alpine-A290-Catalog.pdf"},
    {"brand": "Alpine",        "model": "A390",                 "pdf": "Alpine-A390-Catalog.pdf"},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def ensure_table(conn):
    """Create catalog_photos table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS catalog_photos (
                id         SERIAL PRIMARY KEY,
                brand      VARCHAR(50)  NOT NULL,
                model      VARCHAR(100) NOT NULL,
                page_num   INTEGER      NOT NULL,
                photo_path TEXT         NOT NULL,
                width      INTEGER,
                height     INTEGER,
                size_kb    INTEGER,
                UNIQUE (brand, model, page_num, photo_path)
            )
        """)
        conn.commit()


def already_extracted(conn, brand: str, model: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM catalog_photos WHERE brand=%s AND model=%s",
            (brand, model)
        )
        return cur.fetchone()[0] > 0


def save_photo_to_db(conn, brand, model, page_num, path, width, height, size_kb):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO catalog_photos (brand, model, page_num, photo_path, width, height, size_kb)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (brand, model, page_num, str(path), width, height, size_kb))
    conn.commit()


# ── Core extraction ───────────────────────────────────────────────────────────

def extract_catalog(doc: dict, conn) -> dict:
    brand    = doc["brand"]
    model    = doc["model"]
    pdf_file = doc["pdf"]
    pdf_path = PDF_DIR / pdf_file

    label = f"{brand} {model}"

    if not pdf_path.exists():
        print(f"  ⚠  PDF not found: {pdf_path}")
        return {"skipped": True, "reason": "PDF not found"}

    if already_extracted(conn, brand, model):
        print(f"  ⏭  Already extracted — skipping")
        return {"skipped": True, "reason": "already done"}

    out_dir = PHOTO_DIR / f"{slugify(brand)}_{slugify(model)}"
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf     = fitz.open(str(pdf_path))
    saved   = 0
    skipped = 0

    for page_idx in range(len(pdf)):
        page_num = page_idx + 1
        page     = pdf[page_idx]
        images   = page.get_images(full=True)

        img_counter = 0
        for img in images:
            xref = img[0]
            try:
                info = pdf.extract_image(xref)
            except Exception:
                continue

            width   = info["width"]
            height  = info["height"]
            size_kb = len(info["image"]) // 1024
            ext     = info["ext"]

            # Skip small images — icons, logos, bullets, decorative lines
            if width < MIN_WIDTH or height < MIN_HEIGHT or size_kb < MIN_SIZE_KB:
                skipped += 1
                continue

            # Skip non-photo formats (SVG, etc.)
            if ext not in ("jpeg", "jpg", "png", "webp"):
                skipped += 1
                continue

            # Always save as JPEG for consistency
            filename = f"page_{page_num:03d}_img_{img_counter:02d}.jpg"
            out_path = out_dir / filename

            if ext in ("jpeg", "jpg"):
                out_path.write_bytes(info["image"])
            else:
                # Convert PNG/webp to JPEG via PyMuPDF
                pix = fitz.Pixmap(info["image"])
                if pix.alpha:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                pix.save(str(out_path), jpg_quality=92)

            save_photo_to_db(conn, brand, model, page_num, out_path, width, height, size_kb)
            img_counter += 1
            saved += 1

    pdf.close()
    return {"saved": saved, "filtered": skipped}


# ── Main ──────────────────────────────────────────────────────────────────────

def main(filter_brand=None, filter_model=None):
    conn = psycopg2.connect(**DB_CONFIG)
    ensure_table(conn)

    catalogs = CATALOGS
    if filter_brand:
        catalogs = [c for c in catalogs if c["brand"].lower() == filter_brand.lower()]
    if filter_model:
        catalogs = [c for c in catalogs if c["model"].lower() == filter_model.lower()]

    print(f"\n{'='*60}")
    print(f"  Catalog Photo Extraction — {len(catalogs)} catalog(s)")
    print(f"  Min size: {MIN_WIDTH}x{MIN_HEIGHT}px, {MIN_SIZE_KB}KB")
    print(f"{'='*60}\n")

    total_saved   = 0
    total_skipped = 0
    failed        = []

    for i, doc in enumerate(catalogs, 1):
        label = f"{doc['brand']} {doc['model']}"
        print(f"  [{i:>2}/{len(catalogs)}] {label}")
        t0 = time.time()

        try:
            result = extract_catalog(doc, conn)
            if "reason" in result:
                print(f"    ⏭  {result['reason']}")
            else:
                saved    = result["saved"]
                filtered = result["filtered"]
                elapsed  = time.time() - t0
                total_saved   += saved
                total_skipped += filtered
                print(f"    ✓  {saved} photos saved, {filtered} filtered out  ({elapsed:.1f}s)")
        except Exception as e:
            print(f"    ✗  FAILED: {e}")
            failed.append(label)

    conn.close()

    print(f"\n{'='*60}")
    print(f"  DONE")
    print(f"  Photos saved : {total_saved}")
    print(f"  Filtered out : {total_skipped}  (icons, logos, thumbnails)")
    if failed:
        print(f"  Failed       : {len(failed)}")
        for f in failed:
            print(f"    → {f}")
    print(f"  Location     : {PHOTO_DIR}/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", help="Extract single brand only")
    parser.add_argument("--model", help="Extract single model only")
    args = parser.parse_args()
    main(args.brand, args.model)
