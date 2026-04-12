"""
scripts/12_index_text_embeddings.py

RAG Pipeline A — Text Embedding Indexing with OpenAI

What this script does:
- Loads the Docling JSON for a parsed document
- Groups extracted elements by page
- Embeds each page's text using OpenAI text-embedding-3-small
- Stores in PostgreSQL (pgvector) for semantic search

Why text embeddings over ColPali for catalogs:
- Catalogs have real extracted text (colours, specs, descriptions)
- text-embedding-3-small is 1536-dim single vector per page — simple and fast
- No heavy model to load — just OpenAI API calls
- Much better for specific spec queries (range, price, charging time)

Usage:
    python scripts/12_index_text_embeddings.py \
        --brand "Renault" \
        --model "R5 E-Tech" \
        --doc_type "catalog"

Output:
    PostgreSQL table `document_pages_text`:
        id, brand, model, doc_type, page_num, text, image_path, embedding VECTOR(1536)
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────

RAG_DIR     = Path("data/rag")
PARSED_DIR  = RAG_DIR / "parsed"
IMAGES_DIR  = RAG_DIR / "images"

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5434")),
    "dbname":   os.getenv("DB_NAME",     "otto"),
    "user":     os.getenv("DB_USER",     "otto"),
    "password": os.getenv("DB_PASSWORD", "otto"),
}

EMBED_MODEL = "text-embedding-3-small"  # 1536 dims, fast, cheap
BATCH_SIZE  = 20  # pages per API call


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ── Database setup ────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS document_pages_text (
    id          SERIAL PRIMARY KEY,
    brand       TEXT NOT NULL,
    model       TEXT NOT NULL,
    doc_type    TEXT NOT NULL,
    page_num    INTEGER NOT NULL,
    page_text   TEXT NOT NULL,
    image_path  TEXT,
    embedding   VECTOR(1536),
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE(brand, model, doc_type, page_num)
);

CREATE INDEX IF NOT EXISTS idx_doc_pages_text_lookup
    ON document_pages_text(brand, model, doc_type);
"""


def setup_database(conn):
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    print("  ✓ Table ready: document_pages_text")


# ── Build page text chunks from Docling JSON ──────────────────────────────────

def build_page_chunks(json_path: Path, brand: str, model_name: str, doc_type: str) -> list[dict]:
    """
    Group Docling elements by page and build one text chunk per page.

    Each chunk includes:
    - Section headers (most important — named prominently)
    - Body text
    - List items
    - Table content

    Returns list of {page_num, text, image_path}
    """
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    # Build image path map: page_num → image path
    output_name   = f"{slugify(brand)}_{slugify(model_name)}_{slugify(doc_type)}"
    images_folder = IMAGES_DIR / output_name

    page_images = {}
    for img_path in data["metadata"].get("page_images", []):
        p = Path(img_path)
        # Extract page number from filename like page_3.png
        try:
            page_no = int(p.stem.split("_")[1])
            page_images[page_no] = img_path
        except Exception:
            pass

    # Group elements by page
    pages_text: dict[int, list[str]] = {}

    for el in data["elements"]:
        page_no = el.get("page")
        text    = el.get("text", "").strip()
        el_type = el.get("type", "")

        if not page_no or not text:
            continue

        if page_no not in pages_text:
            pages_text[page_no] = []

        # Weight section headers by repeating them (so embedding captures topic)
        if el_type == "SectionHeaderItem":
            pages_text[page_no].insert(0, f"## {text}")
        elif el_type in ("TextItem", "ListItem", "TableItem"):
            pages_text[page_no].append(text)

    # Build final chunks
    chunks = []
    for page_num in sorted(pages_text.keys()):
        combined_text = "\n".join(pages_text[page_num])
        if len(combined_text.strip()) < 10:
            continue  # skip nearly empty pages

        chunks.append({
            "page_num":   page_num,
            "text":       combined_text,
            "image_path": page_images.get(page_num, ""),
        })

    return chunks


# ── Embed with OpenAI ─────────────────────────────────────────────────────────

def embed_texts(texts: list[str], client: OpenAI) -> list[list[float]]:
    """Embed a batch of texts using OpenAI text-embedding-3-small."""
    response = client.embeddings.create(
        model=EMBED_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


# ── Main indexing function ────────────────────────────────────────────────────

def index_document(brand: str, model_name: str, doc_type: str):
    output_name = f"{slugify(brand)}_{slugify(model_name)}_{slugify(doc_type)}"
    json_path   = PARSED_DIR / f"{output_name}.json"

    if not json_path.exists():
        print(f"  ✗ JSON not found: {json_path}")
        print(f"    → Run scripts/07_parse_documents.py first")
        return

    print(f"\n{'='*60}")
    print(f"  Indexing: {brand} {model_name} ({doc_type})")
    print(f"  Source: {json_path}")
    print(f"{'='*60}\n")

    # Build page chunks
    chunks = build_page_chunks(json_path, brand, model_name, doc_type)
    print(f"  ✓ Built {len(chunks)} page chunks from Docling JSON")

    # Preview first few chunks
    print(f"\n  Sample chunks:")
    for chunk in chunks[:3]:
        preview = chunk['text'][:100].replace('\n', ' ')
        print(f"    Page {chunk['page_num']:>3}: {preview}...")

    print()

    # Connect to DB
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    conn   = psycopg2.connect(**DB_CONFIG)
    setup_database(conn)

    # Check already indexed
    with conn.cursor() as cur:
        cur.execute(
            "SELECT page_num FROM document_pages_text WHERE brand=%s AND model=%s AND doc_type=%s",
            (brand, model_name, doc_type)
        )
        already_indexed = {row[0] for row in cur.fetchall()}

    chunks_to_do = [c for c in chunks if c["page_num"] not in already_indexed]

    if already_indexed:
        print(f"  ⏭  Skipping {len(already_indexed)} already-indexed pages")

    print(f"  ▶  Embedding {len(chunks_to_do)} pages via OpenAI API...\n")

    # Process in batches
    indexed = 0
    for i in range(0, len(chunks_to_do), BATCH_SIZE):
        batch  = chunks_to_do[i : i + BATCH_SIZE]
        texts  = [c["text"] for c in batch]

        embeddings = embed_texts(texts, client)

        with conn.cursor() as cur:
            for chunk, emb in zip(batch, embeddings):
                cur.execute(
                    """
                    INSERT INTO document_pages_text
                        (brand, model, doc_type, page_num, page_text, image_path, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                    ON CONFLICT (brand, model, doc_type, page_num) DO UPDATE
                        SET page_text  = EXCLUDED.page_text,
                            image_path = EXCLUDED.image_path,
                            embedding  = EXCLUDED.embedding
                    """,
                    (
                        brand, model_name, doc_type,
                        chunk["page_num"],
                        chunk["text"],
                        chunk["image_path"],
                        str(emb),
                    )
                )
        conn.commit()

        indexed += len(batch)
        page_range = f"{batch[0]['page_num']}–{batch[-1]['page_num']}"
        print(f"  ✓ Pages {page_range:<8}  [{indexed}/{len(chunks_to_do)}]")

        # Small delay to respect rate limits
        if i + BATCH_SIZE < len(chunks_to_do):
            time.sleep(0.2)

    conn.close()

    print(f"\n  ✅ Done! {indexed} pages embedded and stored.")
    print(f"  💾 Table: document_pages_text\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Embed Docling-parsed document pages with OpenAI text embeddings."
    )
    parser.add_argument("--brand",    required=True, help="Car brand (e.g. Renault)")
    parser.add_argument("--model",    required=True, help="Car model (e.g. 'R5 E-Tech')")
    parser.add_argument("--doc_type", required=True, help="catalog or manual")

    args = parser.parse_args()

    index_document(
        brand      = args.brand,
        model_name = args.model,
        doc_type   = args.doc_type,
    )
