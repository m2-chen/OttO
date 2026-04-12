"""
scripts/11_rag_demo.py

ColPali RAG — Interactive Demo Interface

Run:
    streamlit run scripts/11_rag_demo.py
"""

import base64
import json
import os
import time
from pathlib import Path

import psycopg2
import streamlit as st
import torch
from openai import OpenAI
from PIL import Image

from colpali_engine.models import ColPali, ColPaliProcessor

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ── Config ────────────────────────────────────────────────────────────────────

MODEL_NAME = "vidore/colpali-v1.2"

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5434")),
    "dbname":   os.getenv("DB_NAME",     "otto"),
    "user":     os.getenv("DB_USER",     "otto"),
    "password": os.getenv("DB_PASSWORD", "otto"),
}


# ── Cached model loading (loads once, stays in memory) ────────────────────────

@st.cache_resource
def load_model():
    device = torch.device("cpu")
    dtype  = torch.float16
    model  = ColPali.from_pretrained(
        MODEL_NAME,
        torch_dtype=dtype,
        device_map=device,
    ).eval()
    processor = ColPaliProcessor.from_pretrained(MODEL_NAME)
    return model, processor, device


@st.cache_data
def load_pages(brand, model_name, doc_type):
    conn = psycopg2.connect(**DB_CONFIG)
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
    conn.close()

    pages = []
    for page_num, image_path, embeddings_json in rows:
        vectors = torch.tensor(embeddings_json, dtype=torch.float16)
        pages.append({
            "page_num":   page_num,
            "image_path": image_path,
            "vectors":    vectors,
        })
    return pages


def get_available_documents():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT brand, model, doc_type, COUNT(*) FROM document_pages GROUP BY brand, model, doc_type ORDER BY brand, model"
            )
            rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []


# ── Retrieval ─────────────────────────────────────────────────────────────────

def encode_query(query, model, processor, device):
    batch = processor.process_queries([query]).to(device)
    with torch.no_grad():
        embeddings = model(**batch)
    return embeddings[0]


def maxsim_score(query_vectors, page_vectors):
    q = torch.nn.functional.normalize(query_vectors.float(), dim=-1)
    p = torch.nn.functional.normalize(page_vectors.float(),  dim=-1)
    sim = torch.matmul(q, p.T)
    return sim.max(dim=1).values.sum().item()


def retrieve(query, pages, model, processor, device, top_k=3):
    query_vectors = encode_query(query, model, processor, device)
    scores = []
    for page in pages:
        score = maxsim_score(query_vectors, page["vectors"])
        scores.append((score, page["page_num"], page["image_path"]))
    scores.sort(key=lambda x: x[0], reverse=True)
    return scores[:top_k]


def generate_answer(query: str, image_path: str) -> str:
    """
    Send the retrieved page image + query to GPT-4o Vision.
    Returns a natural language answer grounded in what's on the page.
    """
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are OttO, a knowledgeable EV dealership assistant. "
                    "Answer the customer's question based on the catalog page shown. "
                    "Be concise, friendly, and specific. If the page doesn't contain "
                    "the answer, say so honestly."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                    {
                        "type": "text",
                        "text": query,
                    },
                ],
            },
        ],
        max_tokens=400,
    )

    return response.choices[0].message.content


# ── UI ────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="OttO — RAG Demo",
    page_icon="🚗",
    layout="wide",
)

st.title("🚗 OttO — Visual RAG Demo")
st.caption("ColPali multimodal retrieval — find the right catalog page from a natural language query")

# Sidebar — document selector
st.sidebar.header("Document")

docs = get_available_documents()

if not docs:
    st.error("No documents indexed yet. Run scripts/09_index_colpali.py first.")
    st.stop()

doc_options = {f"{row[0]} {row[1]} ({row[2]}) — {row[3]} pages": row for row in docs}
selected_label = st.sidebar.selectbox("Select document", list(doc_options.keys()))
selected_doc   = doc_options[selected_label]
brand, model_name, doc_type, num_pages = selected_doc

st.sidebar.info(f"**{num_pages} pages indexed**")
st.sidebar.markdown("---")
st.sidebar.markdown("**How it works:**")
st.sidebar.markdown("1. Your query → 32 token vectors")
st.sidebar.markdown("2. MaxSim scored against all page patches")
st.sidebar.markdown("3. Best matching pages returned instantly")

# Load model + pages
with st.spinner("Loading ColPali model (first time only)..."):
    colpali_model, processor, device = load_model()

with st.spinner(f"Loading {num_pages} page embeddings from DB..."):
    pages = load_pages(brand, model_name, doc_type)

# Query input
st.markdown("### Ask a question about the catalog")

col_input, col_btn = st.columns([5, 1])
with col_input:
    query = st.text_input(
        label="Query",
        placeholder="e.g. show me the interior colours, charging time, exterior design...",
        label_visibility="collapsed",
    )
with col_btn:
    search = st.button("Search", type="primary", use_container_width=True)

# Quick test buttons
st.markdown("**Quick tests:**")
q1, q2, q3, q4 = st.columns(4)
if q1.button("🪑 Interior colours"):
    query = "interior design and seat colours"
    search = True
if q2.button("⚡ Charging & range"):
    query = "charging time and battery range"
    search = True
if q3.button("🎨 Exterior colours"):
    query = "exterior colour options"
    search = True
if q4.button("📐 Specifications"):
    query = "technical specifications and dimensions"
    search = True

# Run retrieval
if search and query:
    st.markdown("---")

    with st.spinner(f'Searching for: *"{query}"*'):
        t0      = time.time()
        results = retrieve(query, pages, colpali_model, processor, device, top_k=3)
        elapsed = time.time() - t0

    st.success(f"Retrieved in **{elapsed:.2f}s** — showing top 3 matches")
    st.markdown(f"### Results for: *\"{query}\"*")

    # ── Best match: full answer + image ───────────────────────────────────────
    top_score, top_page, top_image = results[0]

    with st.spinner("Generating answer from page..."):
        answer = generate_answer(query, top_image)

    st.markdown("#### OttO's answer")
    st.info(answer)

    # ── Page images side by side ───────────────────────────────────────────────
    st.markdown("#### Retrieved pages")
    cols = st.columns(3)

    for i, (score, page_num, image_path) in enumerate(results):
        with cols[i]:
            rank_label = ["🥇 Best match", "🥈 2nd", "🥉 3rd"][i]
            st.markdown(f"**{rank_label} — Page {page_num}**")
            st.caption(f"Score: `{score:.4f}`")

            if Path(image_path).exists():
                img = Image.open(image_path)
                st.image(img, use_container_width=True)
            else:
                st.warning(f"Image not found: {image_path}")

elif search and not query:
    st.warning("Please enter a query first.")
