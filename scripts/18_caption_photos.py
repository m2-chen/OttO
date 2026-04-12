"""
scripts/18_caption_photos.py

Caption all extracted catalog photos using GPT-4o vision.
For each photo:
  1. Send to GPT-4o with detail:"auto"
  2. Get structured JSON: caption, type, perspective, color, features
  3. Embed the caption with text-embedding-3-small
  4. Store in catalog_photos table

This runs once. Re-running skips already-captioned photos.

Run:
    python scripts/18_caption_photos.py
    python scripts/18_caption_photos.py --brand Renault   # single brand
    python scripts/18_caption_photos.py --dry-run         # show what would run, no API calls
"""

import argparse
import base64
import json
import os
import time
from pathlib import Path

import psycopg2
from openai import OpenAI

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5434")),
    "dbname":   os.getenv("DB_NAME",     "otto"),
    "user":     os.getenv("DB_USER",     "otto"),
    "password": os.getenv("DB_PASSWORD", "otto"),
}

VISION_MODEL    = "gpt-4o"
EMBEDDING_MODEL = "text-embedding-3-small"

# Prompt asking for structured JSON output
CAPTION_PROMPT = """You are analyzing a professional automotive catalog photo.
Return a JSON object with exactly these fields:

{
  "caption": "one concise phrase describing the image, e.g. 'front exterior in metallic blue, three-quarter angle'",
  "type": "one of: exterior | interior | charging | detail | other",
  "perspective": "e.g. front_quarter, rear_quarter, side, rear, dashboard, cabin, close_up",
  "color": "dominant car color if visible, else null",
  "features": ["list", "of", "visible", "elements", "e.g.", "alloy wheels", "sunroof", "infotainment screen"]
}

Rules:
- type must be exactly one of the five options
- caption must be specific and searchable — someone should be able to find this photo by searching your caption
- Return only valid JSON, no extra text"""


def _add_columns_if_missing(conn):
    """Add caption, photo_type, embedding columns to catalog_photos if not present."""
    with conn.cursor() as cur:
        cur.execute("""
            ALTER TABLE catalog_photos
            ADD COLUMN IF NOT EXISTS caption     TEXT,
            ADD COLUMN IF NOT EXISTS photo_type  VARCHAR(20),
            ADD COLUMN IF NOT EXISTS embedding   vector(1536)
        """)
    conn.commit()
    print("DB columns ready (caption, photo_type, embedding)")


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _caption_photo(client: OpenAI, photo_path: str) -> dict:
    """Send photo to GPT-4o vision, return parsed structured caption."""
    b64 = _encode_image(photo_path)
    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url":    f"data:image/jpeg;base64,{b64}",
                        "detail": "auto",
                    },
                },
                {
                    "type": "text",
                    "text": CAPTION_PROMPT,
                },
            ],
        }],
        max_tokens=300,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    return json.loads(raw)


def _embed_caption(client: OpenAI, caption_data: dict) -> list[float]:
    """Build a rich text from structured caption and embed it."""
    # Combine all fields for a richer embedding
    parts = [caption_data.get("caption", "")]
    if caption_data.get("type"):
        parts.append(caption_data["type"])
    if caption_data.get("perspective"):
        parts.append(caption_data["perspective"])
    if caption_data.get("color"):
        parts.append(caption_data["color"])
    features = caption_data.get("features", [])
    if features:
        parts.append(", ".join(features))

    text = " | ".join(p for p in parts if p)
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[text],
    )
    return response.data[0].embedding


def run(brand_filter: str | None = None, dry_run: bool = False):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    conn   = psycopg2.connect(**DB_CONFIG)

    _add_columns_if_missing(conn)

    # Load photos that haven't been captioned yet
    with conn.cursor() as cur:
        if brand_filter:
            cur.execute("""
                SELECT id, brand, model, photo_path
                FROM catalog_photos
                WHERE caption IS NULL
                  AND LOWER(brand) = LOWER(%s)
                ORDER BY brand, model, photo_path
            """, (brand_filter,))
        else:
            cur.execute("""
                SELECT id, brand, model, photo_path
                FROM catalog_photos
                WHERE caption IS NULL
                ORDER BY brand, model, photo_path
            """)
        photos = cur.fetchall()

    total = len(photos)
    print(f"\nPhotos to caption: {total}")
    if dry_run:
        for photo_id, brand, model, path in photos[:10]:
            print(f"  [{photo_id}] {brand} {model} — {path}")
        if total > 10:
            print(f"  ... and {total - 10} more")
        print("\nDry run complete — no API calls made.")
        conn.close()
        return

    done = 0
    errors = 0

    for photo_id, brand, model, photo_path in photos:
        if not Path(photo_path).exists():
            print(f"  SKIP (file missing): {photo_path}")
            errors += 1
            continue

        try:
            # 1. Caption
            caption_data = _caption_photo(client, photo_path)

            # 2. Embed
            embedding = _embed_caption(client, caption_data)
            embedding_str = str(embedding)

            # 3. Store
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE catalog_photos
                    SET caption    = %s,
                        photo_type = %s,
                        embedding  = %s::vector
                    WHERE id = %s
                """, (
                    caption_data.get("caption", ""),
                    caption_data.get("type", "other"),
                    embedding_str,
                    photo_id,
                ))
            conn.commit()

            done += 1
            print(f"  [{done}/{total}] {brand} {model} — {caption_data.get('type','?')} — {caption_data.get('caption','')[:60]}")

            # Small delay to avoid rate limits
            time.sleep(0.1)

        except Exception as e:
            errors += 1
            print(f"  ERROR [{photo_id}] {photo_path}: {e}")
            conn.rollback()
            time.sleep(1)  # back off on error

    conn.close()
    print(f"\nDone: {done} captioned, {errors} errors")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand",   help="Caption only this brand")
    parser.add_argument("--dry-run", action="store_true", help="Preview without API calls")
    args = parser.parse_args()

    run(brand_filter=args.brand, dry_run=args.dry_run)
