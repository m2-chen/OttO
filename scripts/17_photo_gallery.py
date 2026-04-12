"""
scripts/17_photo_gallery.py
Quick browser for all extracted catalog photos.

Run:
    streamlit run scripts/17_photo_gallery.py
"""

import os
from pathlib import Path
import psycopg2
import streamlit as st
from PIL import Image

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5434")),
    "dbname":   os.getenv("DB_NAME",     "otto"),
    "user":     os.getenv("DB_USER",     "otto"),
    "password": os.getenv("DB_PASSWORD", "otto"),
}

st.set_page_config(page_title="OttO Photo Library", layout="wide")
st.title("OttO — Catalog Photo Library")

@st.cache_data
def get_models():
    conn = psycopg2.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT brand, model, COUNT(*) as n
            FROM catalog_photos
            GROUP BY brand, model
            ORDER BY brand, model
        """)
        rows = cur.fetchall()
    conn.close()
    return rows

models = get_models()
options = {f"{r[0]} {r[1]} ({r[2]} photos)": (r[0], r[1]) for r in models}

selected = st.sidebar.selectbox("Model", list(options.keys()))
brand, model = options[selected]

conn = psycopg2.connect(**DB_CONFIG)
with conn.cursor() as cur:
    cur.execute("""
        SELECT page_num, photo_path, width, height, size_kb
        FROM catalog_photos
        WHERE brand=%s AND model=%s
        ORDER BY page_num, photo_path
    """, (brand, model))
    photos = cur.fetchall()
conn.close()

st.caption(f"{len(photos)} photos — {brand} {model}")

cols = st.columns(4)
for i, (page_num, path, w, h, kb) in enumerate(photos):
    p = Path(path)
    if p.exists():
        with cols[i % 4]:
            img = Image.open(p)
            st.image(img, use_container_width=True)
            st.caption(f"Page {page_num} · {w}×{h} · {kb}KB")
