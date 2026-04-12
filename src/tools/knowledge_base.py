"""
src/tools/knowledge_base.py

RAG tool — Catalog Knowledge Base Search
Called by OttO when the customer asks about a car's technical specs,
range, charging, colours, trims, dimensions or any product feature.

Flow:
1. Embed the customer query with OpenAI text-embedding-3-small
2. Search document_pages_text via pgvector cosine similarity
3. Return the top matching page texts as a formatted context string
4. OttO receives this and reformulates it naturally as a receptionist
"""

import os

import psycopg2
from openai import OpenAI

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5434")),
    "dbname":   os.getenv("DB_NAME",     "otto"),
    "user":     os.getenv("DB_USER",     "otto"),
    "password": os.getenv("DB_PASSWORD", "otto"),
}

_openai_client = None


def _get_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client


def _is_garbled(text: str) -> bool:
    """
    Returns True if a page's text looks like failed OCR from an infographic —
    many very short lines, lone numbers, random letter clusters — not real prose.
    Protects OttO from receiving noise as context.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return True
    short = sum(1 for l in lines if len(l.split()) <= 2)
    return (short / len(lines)) > 0.55


def search_knowledge_base(
    query: str,
    brand: str | None = None,
    model: str | None = None,
    top_k: int = 3,
) -> dict:
    """
    Search the catalog knowledge base for information about a specific car.

    Args:
        query:  The customer's question or topic (e.g. 'charging time', 'available colours')
        brand:  Car brand if known (e.g. 'Kia', 'Renault') — narrows the search
        model:  Car model if known (e.g. 'EV9', 'R5 E-Tech') — narrows the search
        top_k:  Number of catalog pages to retrieve (default 3)

    Returns:
        A dict with:
          - text:        formatted catalog excerpts for OttO to use
          - image_paths: list of clean photo paths from matching catalog pages
    """
    client = _get_client()

    # Embed the query
    query_embedding = client.embeddings.create(
        model="text-embedding-3-small",
        input=[query],
    ).data[0].embedding
    embedding_str = str(query_embedding)

    # Build SQL — filter by brand/model if provided, else cross-catalog search
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            if brand and model:
                cur.execute("""
                    SELECT brand, model, page_num, page_text,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM document_pages_text
                    WHERE LOWER(brand) LIKE LOWER(%s) AND LOWER(model) LIKE LOWER(%s)
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (embedding_str, f"%{brand}%", f"%{model}%", embedding_str, top_k))
            elif brand:
                cur.execute("""
                    SELECT brand, model, page_num, page_text,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM document_pages_text
                    WHERE LOWER(brand) LIKE LOWER(%s)
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (embedding_str, f"%{brand}%", embedding_str, top_k))
            else:
                cur.execute("""
                    SELECT brand, model, page_num, page_text,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM document_pages_text
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (embedding_str, embedding_str, top_k))

            rows = cur.fetchall()

        if not rows:
            return {"text": "No catalog information found for this query.", "image_paths": []}

        # Format text context and collect matching photo paths
        context_parts = []
        image_paths   = []

        for brand_r, model_r, page_num, page_text, similarity in rows:
            if similarity < 0.35:
                continue
            if _is_garbled(page_text):
                continue
            context_parts.append(
                f"[{brand_r} {model_r} — Catalog page {page_num}]\n{page_text}"
            )
            # Pull up to 2 clean photos per retrieved page
            with conn.cursor() as cur2:
                cur2.execute("""
                    SELECT photo_path FROM catalog_photos
                    WHERE LOWER(brand) = LOWER(%s)
                      AND LOWER(model) = LOWER(%s)
                      AND page_num = %s
                    ORDER BY photo_path
                    LIMIT 2
                """, (brand_r, model_r, page_num))
                image_paths.extend(r[0] for r in cur2.fetchall())

    finally:
        conn.close()

    if not context_parts:
        return {"text": "No relevant catalog information found for this query.", "image_paths": []}

    # Cap at 6 images total to avoid flooding the UI
    return {
        "text":        "\n\n---\n\n".join(context_parts),
        "image_paths": image_paths[:6],
    }
