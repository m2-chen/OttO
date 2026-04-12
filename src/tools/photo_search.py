"""
src/tools/photo_search.py

Photo-level semantic search using caption embeddings.
Called by OttO when the customer asks to see photos of a specific car
(exterior, interior, charging, design, colors, etc.)

Unlike search_knowledge_base() which searches page TEXT,
this tool searches photo CAPTIONS embedded individually —
so "show me the interior" returns exactly interior photos,
not whatever happened to be on a page that mentioned interior.

Flow:
1. Embed the customer's visual query
2. Optional hard filter by brand, model, photo_type
3. pgvector cosine search on photo embeddings
4. Return top matching photo paths
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


# Map common query terms to photo_type values for hard filtering
_TYPE_KEYWORDS = {
    "interior":    "interior",
    "inside":      "interior",
    "cabin":       "interior",
    "seats":       "interior",
    "dashboard":   "interior",
    "infotainment":"interior",
    "exterior":    "exterior",
    "outside":     "exterior",
    "design":      "exterior",
    "colour":      "exterior",
    "color":       "exterior",
    "charging":    "charging",
    "charge":      "charging",
    "plug":        "charging",
    "cable":       "charging",
}


def _infer_type(query: str) -> str | None:
    """Detect photo type from query keywords for hard pre-filtering."""
    q = query.lower()
    for keyword, photo_type in _TYPE_KEYWORDS.items():
        if keyword in q:
            return photo_type
    return None  # no hard filter — use pure vector similarity


def search_catalog_photos(
    query: str,
    brand: str | None = None,
    model: str | None = None,
    top_k: int = 4,
) -> dict:
    """
    Search catalog photos by visual similarity to the customer's query.

    Args:
        query:  What the customer wants to see (e.g. 'interior', 'exterior blue', 'charging port')
        brand:  Car brand if known (e.g. 'Renault', 'Kia')
        model:  Car model if known (e.g. 'R5 E-Tech', 'EV9')
        top_k:  Number of photos to return (default 4)

    Returns:
        dict with:
          - image_paths: list of photo file paths (for UI display)
          - descriptions: brief captions for OttO to describe naturally
    """
    client = _get_client()

    # Embed the query
    embedding = client.embeddings.create(
        model="text-embedding-3-small",
        input=[query],
    ).data[0].embedding
    embedding_str = str(embedding)

    # Infer photo type for hard pre-filtering
    photo_type = _infer_type(query)

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            # Build filters dynamically
            conditions = ["embedding IS NOT NULL"]
            params = []

            if brand:
                conditions.append("LOWER(brand) LIKE LOWER(%s)")
                params.append(f"%{brand}%")
            if model:
                conditions.append("LOWER(model) LIKE LOWER(%s)")
                params.append(f"%{model}%")
            if photo_type:
                conditions.append("photo_type = %s")
                params.append(photo_type)

            where = " AND ".join(conditions)

            # pgvector cosine similarity search
            cur.execute(f"""
                SELECT photo_path, caption, photo_type,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM catalog_photos
                WHERE {where}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, [embedding_str] + params + [embedding_str, top_k])

            rows = cur.fetchall()

    finally:
        conn.close()

    if not rows:
        return {
            "image_paths":   [],
            "descriptions":  [],
            "message":       "No matching photos found.",
        }

    # Filter by minimum similarity threshold
    rows = [(path, caption, ptype, sim) for path, caption, ptype, sim in rows if sim >= 0.25]

    if not rows:
        return {
            "image_paths":   [],
            "descriptions":  [],
            "message":       "No sufficiently similar photos found.",
        }

    image_paths  = [r[0] for r in rows]
    descriptions = [r[1] for r in rows if r[1]]

    return {
        "image_paths":  image_paths,
        "descriptions": descriptions,
    }
