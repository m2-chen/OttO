"""
scripts/10_retrieve_colpali.py

RAG Pipeline B — Step 3: ColPali Retrieval & Query Testing

What this script does:
- Takes a natural language query as input
- Encodes it with ColPali into token vectors
- Loads page embeddings from PostgreSQL
- Scores every page using MaxSim (late interaction)
- Returns the top matching page + displays it

MaxSim scoring:
    For each page:
        score = sum over query tokens of max(similarity(token, patch) for patch in page)
    The page with the highest score wins.

Usage:
    # Single query
    python scripts/10_retrieve_colpali.py \
        --query "show me the interior colours" \
        --brand "Hyundai" \
        --model "IONIQ 6" \
        --doc_type "catalog"

    # Run all 4 test queries at once
    python scripts/10_retrieve_colpali.py \
        --brand "Hyundai" \
        --model "IONIQ 6" \
        --doc_type "catalog" \
        --test

Output:
    Top matching page number + image path
    Optionally opens the image for visual verification
"""

import argparse
import json
import os
import time
from pathlib import Path

import psycopg2
import torch
from PIL import Image

from colpali_engine.models import ColPali, ColPaliProcessor


# ── Config ────────────────────────────────────────────────────────────────────

MODEL_NAME = "vidore/colpali-v1.2"

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5434")),
    "dbname":   os.getenv("DB_NAME",     "otto"),
    "user":     os.getenv("DB_USER",     "otto"),
    "password": os.getenv("DB_PASSWORD", "otto"),
}

# Test queries — covering the main things a customer would ask visually
TEST_QUERIES = [
    "interior design and seat colours",
    "charging time and battery range",
    "exterior colours available",
    "technical specifications and dimensions",
]


# ── Model loading ─────────────────────────────────────────────────────────────

def load_model():
    device = torch.device("cpu")
    dtype  = torch.float16
    print("  Loading ColPali model (from cache)...")

    model = ColPali.from_pretrained(
        MODEL_NAME,
        torch_dtype=dtype,
        device_map=device,
    ).eval()

    processor = ColPaliProcessor.from_pretrained(MODEL_NAME)
    print("  ✓ Model loaded\n")
    return model, processor, device


# ── Query encoding ────────────────────────────────────────────────────────────

def encode_query(query: str, model, processor, device) -> torch.Tensor:
    """
    Encode a text query into token vectors using ColPali.

    Returns:
        Tensor of shape (num_tokens, dim) — typically (32, 128)
    """
    batch_queries = processor.process_queries([query]).to(device)

    with torch.no_grad():
        query_embeddings = model(**batch_queries)  # (1, num_tokens, dim)

    return query_embeddings[0]  # (num_tokens, dim)


# ── MaxSim scoring ────────────────────────────────────────────────────────────

def maxsim_score(query_vectors: torch.Tensor, page_vectors: torch.Tensor) -> float:
    """
    Compute MaxSim score between a query and one page.

    MaxSim: for each query token, find the most similar page patch.
    Sum those max similarities → final page score.

    Args:
        query_vectors: (num_query_tokens, dim)
        page_vectors:  (num_patches, dim)

    Returns:
        Scalar score — higher = more relevant
    """
    # Normalise both sets of vectors
    query_norm = torch.nn.functional.normalize(query_vectors.float(), dim=-1)
    page_norm  = torch.nn.functional.normalize(page_vectors.float(),  dim=-1)

    # Similarity matrix: (num_query_tokens, num_patches)
    sim_matrix = torch.matmul(query_norm, page_norm.T)

    # Max over patches for each query token, then sum
    score = sim_matrix.max(dim=1).values.sum().item()

    return score


# ── Load page embeddings from DB ──────────────────────────────────────────────

def load_page_embeddings(brand: str, model_name: str, doc_type: str, conn):
    """
    Load all page embeddings for a document from PostgreSQL.

    Returns:
        List of dicts: {page_num, image_path, vectors (torch.Tensor)}
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT page_num, image_path, embeddings
            FROM document_pages
            WHERE brand = %s AND model = %s AND doc_type = %s
            ORDER BY page_num
            """,
            (brand, model_name, doc_type)
        )
        rows = cur.fetchall()

    if not rows:
        raise ValueError(f"No pages found for {brand} {model_name} ({doc_type}). Run indexing first.")

    pages = []
    for page_num, image_path, embeddings_json in rows:
        vectors = torch.tensor(embeddings_json, dtype=torch.float16)
        pages.append({
            "page_num":   page_num,
            "image_path": image_path,
            "vectors":    vectors,
        })

    print(f"  ✓ Loaded {len(pages)} pages from PostgreSQL")
    return pages


# ── Main retrieval function ───────────────────────────────────────────────────

def retrieve(query: str, pages: list, model, processor, device, top_k: int = 3) -> list:
    """
    Find the top-k most relevant pages for a query.

    Returns:
        List of (score, page_num, image_path) sorted by score descending
    """
    # Encode the query
    query_vectors = encode_query(query, model, processor, device)

    # Score every page
    scores = []
    for page in pages:
        score = maxsim_score(query_vectors, page["vectors"])
        scores.append((score, page["page_num"], page["image_path"]))

    # Sort by score descending
    scores.sort(key=lambda x: x[0], reverse=True)

    return scores[:top_k]


# ── Display results ───────────────────────────────────────────────────────────

def display_results(query: str, results: list, open_image: bool = False):
    print(f"\n  Query: \"{query}\"")
    print(f"  {'─'*55}")
    for rank, (score, page_num, image_path) in enumerate(results, 1):
        print(f"  #{rank}  Page {page_num:>3}  |  Score: {score:.4f}  |  {Path(image_path).name}")

    # Open the top result image
    top_image_path = results[0][2]
    if open_image and Path(top_image_path).exists():
        img = Image.open(top_image_path)
        img.show()
        print(f"\n  📄 Opened: {top_image_path}")
    elif open_image:
        print(f"\n  ⚠ Image not found: {top_image_path}")

    print()


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Retrieve relevant PDF pages using ColPali MaxSim scoring."
    )
    parser.add_argument("--query",    help="Natural language query")
    parser.add_argument("--brand",    required=True, help="Car brand (e.g. Hyundai)")
    parser.add_argument("--model",    required=True, help="Car model (e.g. 'IONIQ 6')")
    parser.add_argument("--doc_type", required=True, help="catalog or manual")
    parser.add_argument("--top_k",    type=int, default=3, help="Number of results to return (default: 3)")
    parser.add_argument("--test",     action="store_true", help="Run all test queries")
    parser.add_argument("--open",     action="store_true", help="Open top result image")

    args = parser.parse_args()

    if not args.test and not args.query:
        parser.error("Either --query or --test required")

    # Load model
    model, processor, device = load_model()

    # Connect to DB and load page embeddings
    print("  Connecting to PostgreSQL...")
    conn = psycopg2.connect(**DB_CONFIG)
    pages = load_page_embeddings(args.brand, args.model, args.doc_type, conn)
    conn.close()

    queries = TEST_QUERIES if args.test else [args.query]

    print(f"\n{'='*60}")
    print(f"  ColPali Retrieval — {args.brand} {args.model} ({args.doc_type})")
    print(f"{'='*60}")

    for query in queries:
        t0      = time.time()
        results = retrieve(query, pages, model, processor, device, top_k=args.top_k)
        elapsed = time.time() - t0

        display_results(query, results, open_image=args.open)
        print(f"  ⏱  Retrieved in {elapsed:.2f}s\n")

    print("  ✅ Retrieval complete!")
