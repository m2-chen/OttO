"""
scripts/13_retrieve_text.py

RAG Pipeline A — Text Embedding Retrieval

Usage:
    python scripts/13_retrieve_text.py \
        --brand "Renault" --model "R5 E-Tech" --doc_type "catalog" --test
"""

import argparse
import os
import time

import psycopg2
from openai import OpenAI

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5434")),
    "dbname":   os.getenv("DB_NAME",     "otto"),
    "user":     os.getenv("DB_USER",     "otto"),
    "password": os.getenv("DB_PASSWORD", "otto"),
}

TEST_QUERIES = [
    "interior design and seat colours",
    "charging time and battery range",
    "exterior colours available",
    "technical specifications and dimensions",
    "price and trim levels",
    "safety features and driver assistance",
]


def embed_query(query: str, client: OpenAI) -> list[float]:
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=[query],
    )
    return response.data[0].embedding


def retrieve(query: str, brand: str, model_name: str, doc_type: str,
             client: OpenAI, conn, top_k: int = 3) -> list:
    query_embedding = embed_query(query, client)
    embedding_str   = str(query_embedding)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT page_num, page_text, image_path,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM document_pages_text
            WHERE brand = %s AND model = %s AND doc_type = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (embedding_str, brand, model_name, doc_type, embedding_str, top_k)
        )
        rows = cur.fetchall()

    return [(row[3], row[0], row[1], row[2]) for row in rows]
    # (similarity, page_num, text, image_path)


def display_results(query: str, results: list):
    print(f"\n  Query: \"{query}\"")
    print(f"  {'─'*55}")
    for rank, (score, page_num, text, image_path) in enumerate(results, 1):
        preview = text[:120].replace('\n', ' ')
        print(f"  #{rank}  Page {page_num:>3}  |  Similarity: {score:.4f}")
        print(f"       {preview}...")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand",    required=True)
    parser.add_argument("--model",    required=True)
    parser.add_argument("--doc_type", required=True)
    parser.add_argument("--query",    help="Single query")
    parser.add_argument("--test",     action="store_true")
    parser.add_argument("--top_k",    type=int, default=3)
    args = parser.parse_args()

    if not args.test and not args.query:
        parser.error("Either --query or --test required")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    conn   = psycopg2.connect(**DB_CONFIG)

    queries = TEST_QUERIES if args.test else [args.query]

    print(f"\n{'='*60}")
    print(f"  Text Embedding Retrieval — {args.brand} {args.model} ({args.doc_type})")
    print(f"{'='*60}")

    for query in queries:
        t0      = time.time()
        results = retrieve(query, args.brand, args.model, args.doc_type,
                           client, conn, top_k=args.top_k)
        elapsed = time.time() - t0
        display_results(query, results)
        print(f"  ⏱  {elapsed:.2f}s\n")

    conn.close()
    print("  ✅ Done!")
