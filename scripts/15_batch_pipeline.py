"""
scripts/15_batch_pipeline.py

Batch RAG Pipeline — Parse + Embed all car catalogs

What this script does:
1. Batch 1: Runs Docling on every catalog PDF → JSON files
2. Batch 2: Embeds every JSON with OpenAI → PostgreSQL

Features:
- Skips already-parsed/embedded documents (safe to re-run)
- Logs every step with timing
- Continues on failure — one bad PDF doesn't stop the rest
- Summary report at the end

Usage:
    # Full pipeline (parse + embed)
    python scripts/15_batch_pipeline.py

    # Only parsing (Docling)
    python scripts/15_batch_pipeline.py --parse-only

    # Only embedding (after parsing is done)
    python scripts/15_batch_pipeline.py --embed-only
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

# ── Catalog manifest ──────────────────────────────────────────────────────────
# All 22 remaining catalogs (R5 E-Tech already done)

CATALOGS = [
    # Renault
    {"brand": "Renault",   "model": "R4 E-Tech",       "pdf": "R4-E-Tech-Catalog.pdf"},
    {"brand": "Renault",   "model": "Megane E-Tech",    "pdf": "R-Megane-E-Tech.pdf"},
    {"brand": "Renault",   "model": "Scenic E-Tech",    "pdf": "Renault-Scenic-E-Tech-Catalog-IE.pdf"},

    # Volkswagen
    {"brand": "Volkswagen", "model": "ID.3",            "pdf": "VW-ID-3-Catalog.pdf"},
    {"brand": "Volkswagen", "model": "ID.4",            "pdf": "VW-ID.4-catalog.pdf"},
    {"brand": "Volkswagen", "model": "ID.7",            "pdf": "VW-ID7-Catalog.pdf"},
    {"brand": "Volkswagen", "model": "ID.Buzz",         "pdf": "ID-Buzz-Catalog.pdf"},

    # Kia
    {"brand": "Kia",       "model": "EV3",              "pdf": "Kia-EV3-Catalog.pdf"},
    {"brand": "Kia",       "model": "EV6",              "pdf": "Kia-EV6-Catalog.pdf"},
    {"brand": "Kia",       "model": "EV9",              "pdf": "kia_catalog_ev9.pdf"},

    # Hyundai
    {"brand": "Hyundai",   "model": "IONIQ 5",          "pdf": "IONIQ_5_Brochure.pdf"},
    {"brand": "Hyundai",   "model": "IONIQ 6",          "pdf": "brochure_ioniq6_.pdf"},
    {"brand": "Hyundai",   "model": "IONIQ 9",          "pdf": "Hyundai_IONIQ-9_.catalog.pdf"},
    {"brand": "Hyundai",   "model": "KONA Electric",    "pdf": "KONA-EV-Brochure.pdf"},

    # Audi
    {"brand": "Audi",      "model": "Q6 e-tron",        "pdf": "q6-e-tron_catalog.pdf"},
    {"brand": "Audi",      "model": "A6 e-tron Sportback", "pdf": "a6-sportback-e-tron-Catalog.pdf"},

    # Mercedes
    {"brand": "Mercedes-Benz", "model": "EQA",          "pdf": "Mercedes-EQA-Catalog.pdf"},
    {"brand": "Mercedes-Benz", "model": "EQB",          "pdf": "Mercedes-EQB-Catalog.pdf"},
    {"brand": "Mercedes-Benz", "model": "EQE",          "pdf": "Mercedes-EQE-catalog.pdf"},
    {"brand": "Mercedes-Benz", "model": "EQS",          "pdf": "Mercedes-EQS-Catalog-IN.pdf"},

    # Alpine
    {"brand": "Alpine",    "model": "A290",             "pdf": "Alpine-A290-Catalog.pdf"},
    {"brand": "Alpine",    "model": "A390",             "pdf": "Alpine-A390-Catalog.pdf"},
]

PDF_DIR    = Path("/Users/mehdichenini/Desktop/Car_Manuals")
PARSED_DIR = Path("data/rag/parsed")
PYTHON     = sys.executable


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def already_parsed(brand: str, model: str, doc_type: str) -> bool:
    name = f"{slugify(brand)}_{slugify(model)}_{slugify(doc_type)}.json"
    return (PARSED_DIR / name).exists()


def already_embedded(brand: str, model: str, doc_type: str) -> bool:
    """Check if at least one page is already embedded in the DB."""
    try:
        import os
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5434")),
            dbname=os.getenv("DB_NAME", "otto"),
            user=os.getenv("DB_USER", "otto"),
            password=os.getenv("DB_PASSWORD", "otto"),
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM document_pages_text WHERE brand=%s AND model=%s AND doc_type=%s",
                (brand, model, doc_type)
            )
            count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


def run_step(cmd: list, label: str) -> tuple[bool, float]:
    """Run a subprocess command, return (success, elapsed_seconds)."""
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"    ✗ FAILED: {result.stderr[-300:] if result.stderr else 'unknown error'}")
        return False, elapsed
    return True, elapsed


# ── Batch 1: Docling parsing ──────────────────────────────────────────────────

def batch_parse(catalogs: list) -> dict:
    print(f"\n{'='*60}")
    print(f"  BATCH 1 — Docling Parsing")
    print(f"  Documents: {len(catalogs)}")
    print(f"{'='*60}\n")

    results = {"success": [], "skipped": [], "failed": []}

    for i, doc in enumerate(catalogs, 1):
        brand    = doc["brand"]
        model    = doc["model"]
        pdf_file = doc["pdf"]
        pdf_path = PDF_DIR / pdf_file

        label = f"{brand} {model}"
        print(f"  [{i:>2}/{len(catalogs)}] {label}")

        # Check PDF exists
        if not pdf_path.exists():
            print(f"    ⚠ PDF not found: {pdf_path}")
            results["failed"].append({"doc": label, "reason": "PDF not found"})
            continue

        # Skip if already parsed
        if already_parsed(brand, model, "catalog"):
            print(f"    ⏭  Already parsed — skipping")
            results["skipped"].append(label)
            continue

        # Run Docling
        cmd = [
            PYTHON, "scripts/07_parse_documents.py",
            "--pdf",      str(pdf_path),
            "--brand",    brand,
            "--model",    model,
            "--doc_type", "catalog",
        ]

        success, elapsed = run_step(cmd, label)

        if success:
            print(f"    ✓ Parsed in {elapsed:.0f}s")
            results["success"].append(label)
        else:
            results["failed"].append({"doc": label, "reason": "Docling error"})

    return results


# ── Batch 2: Text embedding ───────────────────────────────────────────────────

def batch_embed(catalogs: list) -> dict:
    print(f"\n{'='*60}")
    print(f"  BATCH 2 — Text Embedding (OpenAI)")
    print(f"  Documents: {len(catalogs)}")
    print(f"{'='*60}\n")

    results = {"success": [], "skipped": [], "failed": []}

    for i, doc in enumerate(catalogs, 1):
        brand = doc["brand"]
        model = doc["model"]
        label = f"{brand} {model}"

        print(f"  [{i:>2}/{len(catalogs)}] {label}")

        # Skip if already embedded
        if already_embedded(brand, model, "catalog"):
            print(f"    ⏭  Already embedded — skipping")
            results["skipped"].append(label)
            continue

        # Check JSON exists
        json_name = f"{slugify(brand)}_{slugify(model)}_catalog.json"
        if not (PARSED_DIR / json_name).exists():
            print(f"    ⚠ JSON not found — run parsing first")
            results["failed"].append({"doc": label, "reason": "JSON not found"})
            continue

        # Run embedding
        cmd = [
            PYTHON, "scripts/12_index_text_embeddings.py",
            "--brand",    brand,
            "--model",    model,
            "--doc_type", "catalog",
        ]

        success, elapsed = run_step(cmd, label)

        if success:
            print(f"    ✓ Embedded in {elapsed:.0f}s")
            results["success"].append(label)
        else:
            results["failed"].append({"doc": label, "reason": "Embedding error"})

    return results


# ── Summary report ────────────────────────────────────────────────────────────

def print_summary(parse_results: dict, embed_results: dict):
    print(f"\n{'='*60}")
    print(f"  PIPELINE COMPLETE — SUMMARY")
    print(f"{'='*60}")

    print(f"\n  Parsing:")
    print(f"    ✓ Success:  {len(parse_results['success'])}")
    print(f"    ⏭ Skipped:  {len(parse_results['skipped'])}")
    print(f"    ✗ Failed:   {len(parse_results['failed'])}")
    if parse_results["failed"]:
        for f in parse_results["failed"]:
            print(f"      → {f['doc']}: {f['reason']}")

    print(f"\n  Embedding:")
    print(f"    ✓ Success:  {len(embed_results['success'])}")
    print(f"    ⏭ Skipped:  {len(embed_results['skipped'])}")
    print(f"    ✗ Failed:   {len(embed_results['failed'])}")
    if embed_results["failed"]:
        for f in embed_results["failed"]:
            print(f"      → {f['doc']}: {f['reason']}")

    total = len(parse_results["success"]) + len(embed_results["success"])
    print(f"\n  Total documents newly processed: {total}")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Batch parse and embed all car catalogs."
    )
    parser.add_argument("--parse-only", action="store_true", help="Only run Docling parsing")
    parser.add_argument("--embed-only", action="store_true", help="Only run text embedding")
    args = parser.parse_args()

    total_start = time.time()

    parse_results = {"success": [], "skipped": [], "failed": []}
    embed_results = {"success": [], "skipped": [], "failed": []}

    if not args.embed_only:
        parse_results = batch_parse(CATALOGS)

    if not args.parse_only:
        batch_embed(CATALOGS)

    total_elapsed = time.time() - total_start
    print_summary(parse_results, embed_results)
    print(f"  Total time: {total_elapsed/60:.1f} minutes")
