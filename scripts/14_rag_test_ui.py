"""
scripts/14_rag_test_ui.py

OttO RAG — Test Environment

Unified interface to test both RAG pipelines:
- Pipeline A: Text embeddings (Docling + OpenAI) — for spec/text queries
- Pipeline B: ColPali visual (for image retrieval)

Run:
    streamlit run scripts/14_rag_test_ui.py
"""

import os
import time
from pathlib import Path

import psycopg2
import streamlit as st
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5434")),
    "dbname":   os.getenv("DB_NAME",     "otto"),
    "user":     os.getenv("DB_USER",     "otto"),
    "password": os.getenv("DB_PASSWORD", "otto"),
}

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="OttO RAG Test",
    page_icon="🚗",
    layout="wide",
)

# ── OpenAI client ─────────────────────────────────────────────────────────────

@st.cache_resource
def get_openai_client():
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ── DB helpers ────────────────────────────────────────────────────────────────

@st.cache_data
def get_available_documents():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT brand, model, doc_type, COUNT(*) as pages
                FROM document_pages_text
                GROUP BY brand, model, doc_type
                ORDER BY brand, model
            """)
            rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def retrieve_text(query, top_k=3, brand=None, model_name=None, doc_type=None):
    """Retrieve top-k pages. If brand/model/doc_type are None, search across all catalogs."""
    client          = get_openai_client()
    query_embedding = client.embeddings.create(
        model="text-embedding-3-small",
        input=[query],
    ).data[0].embedding

    embedding_str = str(query_embedding)

    conn = psycopg2.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        if brand and model_name and doc_type:
            cur.execute("""
                SELECT brand, model, page_num, page_text, image_path,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM document_pages_text
                WHERE brand = %s AND model = %s AND doc_type = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (embedding_str, brand, model_name, doc_type, embedding_str, top_k))
        else:
            cur.execute("""
                SELECT brand, model, page_num, page_text, image_path,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM document_pages_text
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (embedding_str, embedding_str, top_k))
        rows = cur.fetchall()
    conn.close()

    return [
        {
            "brand":      r[0],
            "model":      r[1],
            "page_num":   r[2],
            "text":       r[3],
            "image_path": r[4],
            "similarity": r[5],
        }
        for r in rows
    ]


def generate_answer(query: str, context_pages: list) -> str:
    """Generate answer using retrieved text as context."""
    client = get_openai_client()

    context = ""
    for page in context_pages:
        context += f"\n[{page['brand']} {page['model']} — Page {page['page_num']}]\n{page['text']}\n"

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are OttO, a knowledgeable and friendly EV dealership assistant for EV Land. "
                    "Answer the customer's question based ONLY on the catalog pages provided as context. "
                    "Be specific — include actual numbers, names, and details from the context. "
                    "Always mention which car model your answer refers to. "
                    "If the context doesn't contain the answer, say so clearly. "
                    "Keep your answer concise and conversational — as if speaking to a customer."
                ),
            },
            {
                "role": "user",
                "content": f"Context from catalogs:\n{context}\n\nCustomer question: {query}",
            },
        ],
        max_tokens=400,
    )

    return response.choices[0].message.content


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("🚗 OttO — RAG Test Environment")
st.caption("Ask any question about a car catalog and evaluate retrieval + answer quality")

# Sidebar
with st.sidebar:
    st.header("Search Mode")

    docs = get_available_documents()

    if not docs:
        st.error("No documents indexed. Run script 12 first.")
        st.stop()

    cross_catalog = st.toggle("🌐 Cross-catalog search", value=False)

    if cross_catalog:
        st.success(f"Searching all **{len(docs)} catalogs** · 659 pages")
        brand, model_name, doc_type, num_pages = None, None, None, None
    else:
        st.markdown("**Select a specific catalog:**")
        doc_options = {
            f"{r[0]} {r[1]} ({r[2]}) — {r[3]} pages": r for r in docs
        }
        selected = st.selectbox("Document", list(doc_options.keys()))
        brand, model_name, doc_type, num_pages = doc_options[selected]
        st.info(f"**{num_pages} pages indexed**")

    top_k = st.slider("Pages to retrieve", min_value=1, max_value=5, value=3)

    st.markdown("---")
    show_pages = st.toggle("Show retrieved pages", value=True)
    show_text  = st.toggle("Show extracted text", value=False)

    st.markdown("---")
    st.markdown("**Pipeline:** Text Embeddings")
    st.markdown("**Embed model:** text-embedding-3-small")
    st.markdown("**Answer model:** GPT-4o")

# Main area
st.markdown("### Ask a question")

# Quick test buttons
st.markdown("**Quick tests:**")
cols = st.columns(3)
quick_query = None
if cols[0].button("⚡ Charging & range"):
    quick_query = "What is the charging time and battery range?"
if cols[1].button("🎨 Exterior colours"):
    quick_query = "What exterior colours are available?"
if cols[2].button("🪑 Interior & seats"):
    quick_query = "Tell me about the interior design and seat materials"

cols2 = st.columns(3)
if cols2[0].button("📐 Dimensions & specs"):
    quick_query = "What are the dimensions and technical specifications?"
if cols2[1].button("🛡️ Safety features"):
    quick_query = "What safety and driver assistance features are included?"
if cols2[2].button("🏷️ Trim levels"):
    quick_query = "What are the different trim levels and versions available?"

st.markdown("---")

query = st.text_input(
    "Or type your own question:",
    value=quick_query or "",
    placeholder="e.g. What is the range of the Kia EV9?",
)

search = st.button("Ask OttO", type="primary", use_container_width=False)

# Run retrieval + generation
if search and query:
    st.markdown("---")

    search_label = "all catalogs" if cross_catalog else f"{brand} {model_name}"

    with st.spinner(f"Searching {search_label}..."):
        t0      = time.time()
        results = retrieve_text(query, top_k=top_k, brand=brand, model_name=model_name, doc_type=doc_type)
        t_ret   = time.time() - t0

    with st.spinner("Generating answer..."):
        t1     = time.time()
        answer = generate_answer(query, results)
        t_gen  = time.time() - t1

    # Answer
    st.markdown("### OttO's Answer")
    st.success(answer)

    st.caption(f"Retrieved in {t_ret:.2f}s · Generated in {t_gen:.2f}s")

    # Retrieved pages
    if show_pages and results:
        st.markdown("---")
        st.markdown("### Retrieved Pages")

        for i, page in enumerate(results):
            rank_label = ["🥇 Best match", "🥈 2nd match", "🥉 3rd match", "4th", "5th"][i]
            confidence = "High" if page["similarity"] > 0.6 else "Medium" if page["similarity"] > 0.4 else "Low"
            conf_color = "🟢" if confidence == "High" else "🟡" if confidence == "Medium" else "🔴"
            source_label = f"{page['brand']} {page['model']} — Page {page['page_num']}"

            with st.expander(f"{rank_label} · {source_label} · Similarity: {page['similarity']:.4f} · {conf_color} {confidence}"):

                if show_text:
                    st.markdown("**Extracted text:**")
                    st.code(page["text"], language=None)

                if page["image_path"] and Path(page["image_path"]).exists():
                    from PIL import Image
                    img = Image.open(page["image_path"])
                    st.image(img, use_container_width=True)
                else:
                    st.caption("No image available for this page")

elif search and not query:
    st.warning("Please enter a question first.")

# Footer
st.markdown("---")
st.caption("OttO RAG Test Environment · Pipeline A: Docling + OpenAI text-embedding-3-small + GPT-4o")
