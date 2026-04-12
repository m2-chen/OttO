"""
scripts/09_index_colpali.py

RAG Pipeline B — Step 2: ColPali Indexing

What this script does:
- Loads rendered PNG images from data/rag/rendered/{brand}_{model}_{doc_type}/
- Runs ColPali (vidore/colpali-v1.2) to embed each page as multi-vectors
- Stores the embeddings in PostgreSQL (pgvector) for MaxSim retrieval

How ColPali works:
- Each page image → Vision Language Model → 627 patch embeddings × 128 dimensions
- These multi-vectors capture visual layout, text, colours, and diagrams simultaneously
- At query time: query text → 32 token embeddings → MaxSim scored against each page
- MaxSim = max similarity between each query token and all page patches (late interaction)

Why multi-vector (not single-vector):
- A single 1536-dim embedding loses spatial and detail information
- Multi-vector preserves "where on the page" information
- Result: ColPali retrieves the exact page showing a red interior or charging diagram,
  not just a page that "mentions" those words

Usage:
    python scripts/09_index_colpali.py \
        --brand "Hyundai" \
        --model "IONIQ 6" \
        --doc_type "catalog"

    # Or index all rendered folders:
    python scripts/09_index_colpali.py --all

Output:
    PostgreSQL table `document_pages`:
        id, brand, model, doc_type, page_num, image_path, embeddings (VECTOR[])
"""

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
import torch
from PIL import Image
from tqdm import tqdm

# ── ColPali imports ────────────────────────────────────────────────────────────
from colpali_engine.models import ColPali, ColPaliProcessor


# ── Config ────────────────────────────────────────────────────────────────────

MODEL_NAME    = "vidore/colpali-v1.2"
RENDERED_DIR  = Path("data/rag/rendered")
BATCH_SIZE    = 4   # pages per batch — reduce if OOM (4 is safe on 8GB RAM)

# PostgreSQL connection (matches docker-compose.yml)
DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5434")),
    "dbname":   os.getenv("DB_NAME",     "otto"),
    "user":     os.getenv("DB_USER",     "otto"),
    "password": os.getenv("DB_PASSWORD", "otto"),
}


# ── Database setup ────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS document_pages (
    id          SERIAL PRIMARY KEY,
    brand       TEXT NOT NULL,
    model       TEXT NOT NULL,
    doc_type    TEXT NOT NULL,
    page_num    INTEGER NOT NULL,
    image_path  TEXT NOT NULL,
    -- ColPali produces ~627 patch embeddings of dim 128 per page
    -- We store as JSONB array of float arrays for flexibility
    -- (pgvector multi-vector support is v0.8+ — using JSONB as fallback)
    embeddings  JSONB NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE(brand, model, doc_type, page_num)
);

CREATE INDEX IF NOT EXISTS idx_doc_pages_lookup
    ON document_pages(brand, model, doc_type);
"""


def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


def setup_database(conn):
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    print("  ✓ Database table ready: document_pages")


# ── ColPali model loading ─────────────────────────────────────────────────────

def load_colpali_model():
    """
    Load ColPali model and processor.

    Device selection:
    - MPS (Apple Silicon GPU) → fastest on Mac
    - CUDA → fastest on NVIDIA
    - CPU → fallback, slow but works
    """
    if torch.backends.mps.is_available():
        device = torch.device("cpu")   # MPS OOM on <16GB RAM — use CPU with float16
        dtype  = torch.float16
        print("  ✓ Apple Silicon detected — running on CPU with float16 (MPS OOM)")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
        dtype  = torch.bfloat16
        print("  ✓ Using CUDA GPU")
    else:
        device = torch.device("cpu")
        dtype  = torch.float32
        print("  ⚠ Using CPU — indexing will be slow (~2-5 min per page)")

    print(f"  Loading ColPali model: {MODEL_NAME} ...")

    model = ColPali.from_pretrained(
        MODEL_NAME,
        torch_dtype=dtype,
        device_map=device,
    ).eval()

    # 0.2.x: ColPaliProcessor wraps the HuggingFace PaliGemmaProcessor
    processor = ColPaliProcessor.from_pretrained(MODEL_NAME)

    print("  ✓ Model loaded\n")
    return model, processor, device


# ── Embedding function ────────────────────────────────────────────────────────

def embed_pages(images: list, model, processor, device) -> list:
    """
    Embed a batch of page images with ColPali (0.2.x API).

    Returns:
        List of embeddings, one per image.
        Each embedding = list of patch vectors (shape: ~627 × 128)
    """
    # Process images into model inputs
    batch_inputs = processor.process_images(images).to(device)

    with torch.no_grad():
        # Forward pass → shape: (batch, num_patches, dim)
        embeddings = model(**batch_inputs)  # (B, 627, 128)

    # Convert to Python lists for JSON storage
    return [emb.cpu().float().tolist() for emb in embeddings]


# ── Main indexing function ────────────────────────────────────────────────────

def index_folder(brand: str, model_name: str, doc_type: str, colpali_model, processor, device, conn):
    """
    Index all rendered pages from one document folder.
    """
    import re

    def slugify(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

    folder_name   = f"{slugify(brand)}_{slugify(model_name)}_{slugify(doc_type)}"
    folder_path   = RENDERED_DIR / folder_name

    if not folder_path.exists():
        print(f"  ✗ Folder not found: {folder_path}")
        print(f"    → Run scripts/08_render_pages.py first")
        return 0

    # Get all PNG files sorted by page number
    page_files = sorted(folder_path.glob("page_*.png"))
    total_pages = len(page_files)

    if total_pages == 0:
        print(f"  ✗ No page images found in {folder_path}")
        return 0

    print(f"\n{'='*60}")
    print(f"  Indexing: {folder_name}")
    print(f"  Pages to embed: {total_pages}")
    print(f"  Batch size: {BATCH_SIZE}")
    print(f"{'='*60}\n")

    # Check which pages are already indexed (resume support)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT page_num FROM document_pages WHERE brand=%s AND model=%s AND doc_type=%s",
            (brand, model_name, doc_type)
        )
        already_indexed = {row[0] for row in cur.fetchall()}

    pages_to_do = [f for f in page_files
                   if int(f.stem.split("_")[1]) not in already_indexed]

    if len(already_indexed) > 0:
        print(f"  ⏭  Skipping {len(already_indexed)} already-indexed pages")
        print(f"  ▶  Indexing {len(pages_to_do)} remaining pages\n")

    if not pages_to_do:
        print("  ✅ All pages already indexed!")
        return 0

    # Process in batches
    indexed_count = 0

    for batch_start in range(0, len(pages_to_do), BATCH_SIZE):
        batch_files = pages_to_do[batch_start : batch_start + BATCH_SIZE]

        # Load images
        images   = [Image.open(f).convert("RGB") for f in batch_files]
        page_nums = [int(f.stem.split("_")[1]) for f in batch_files]

        # Embed with ColPali
        embeddings = embed_pages(images, colpali_model, processor, device)

        # Store in database
        with conn.cursor() as cur:
            for i, (page_num, emb) in enumerate(zip(page_nums, embeddings)):
                cur.execute(
                    """
                    INSERT INTO document_pages
                        (brand, model, doc_type, page_num, image_path, embeddings)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (brand, model, doc_type, page_num) DO UPDATE
                        SET embeddings = EXCLUDED.embeddings,
                            image_path = EXCLUDED.image_path
                    """,
                    (
                        brand,
                        model_name,
                        doc_type,
                        page_num,
                        str(batch_files[i]),
                        json.dumps(emb),
                    )
                )
        conn.commit()

        indexed_count += len(batch_files)
        page_range = f"{page_nums[0]}–{page_nums[-1]}"
        print(f"  ✓ Pages {page_range:>8}  [{indexed_count}/{len(pages_to_do)}]  "
              f"(patches/page: {len(embeddings[0])})")

    print(f"\n  ✅ Done! {indexed_count} pages indexed.")
    print(f"  💾 Stored in PostgreSQL: document_pages\n")

    return indexed_count


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Index rendered PDF pages with ColPali into PostgreSQL."
    )
    parser.add_argument("--brand",    help="Car brand (e.g. Hyundai)")
    parser.add_argument("--model",    help="Car model (e.g. 'IONIQ 6')")
    parser.add_argument("--doc_type", help="catalog or manual")
    parser.add_argument("--all",      action="store_true",
                        help="Index all folders in data/rag/rendered/")

    args = parser.parse_args()

    if not args.all and not all([args.brand, args.model, args.doc_type]):
        parser.error("Either --all or --brand + --model + --doc_type required")

    # Load model once (expensive — ~3-5 GB download on first run)
    colpali_model, processor, device = load_colpali_model()

    # Connect to database
    print("  Connecting to PostgreSQL...")
    conn = get_db_connection()
    setup_database(conn)

    if args.all:
        # Index every rendered folder
        folders = [d for d in RENDERED_DIR.iterdir() if d.is_dir()]
        print(f"\n  Found {len(folders)} folder(s) to index\n")

        for folder in sorted(folders):
            # Parse folder name: brand_model_doc_type
            parts = folder.name.split("_", 2)
            if len(parts) < 3:
                continue
            b, m, d = parts
            index_folder(b, m, d, colpali_model, processor, device, conn)
    else:
        index_folder(
            brand      = args.brand,
            model_name = args.model,
            doc_type   = args.doc_type,
            colpali_model = colpali_model,
            processor  = processor,
            device     = device,
            conn       = conn,
        )

    conn.close()
    print("  🎯 Indexing complete!")
