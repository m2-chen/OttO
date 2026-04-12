"""
scripts/08_render_pages.py

RAG Pipeline B — Step 1: PDF Page Rendering with PyMuPDF

What this script does:
- Takes a PDF catalog as input
- Renders each page as a high-resolution PNG image
- Saves them in an organised folder ready for ColPali indexing

Why this step exists:
- ColPali cannot read PDF files directly
- It only accepts images as input
- This script bridges that gap — PDF pages become images

Usage:
    python scripts/08_render_pages.py \
        --pdf "/path/to/catalog.pdf" \
        --brand "Hyundai" \
        --model "IONIQ 6" \
        --doc_type "catalog"

Output:
    data/rag/rendered/hyundai_ioniq-6_catalog/
        page_001.png
        page_002.png
        ...
"""

import argparse
import re
from pathlib import Path

import pymupdf  # PyMuPDF


# ── Output directory ──────────────────────────────────────────────────────────

RENDERED_DIR = Path("data/rag/rendered")
RENDERED_DIR.mkdir(parents=True, exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ── Main rendering function ───────────────────────────────────────────────────

def render_pdf(pdf_path: str, brand: str, model: str, doc_type: str, dpi: int = 150):
    """
    Render every page of a PDF as a PNG image.

    DPI controls image quality vs file size:
    - 72 dpi  → small files, lower quality (not recommended for ColPali)
    - 150 dpi → good balance, sharp text, reasonable file size ← our default
    - 300 dpi → print quality, large files, slower indexing

    150 dpi is the sweet spot for document retrieval — sharp enough for
    ColPali to read fine text and visual details, without bloating storage.
    """

    output_name   = f"{slugify(brand)}_{slugify(model)}_{slugify(doc_type)}"
    output_folder = RENDERED_DIR / output_name
    output_folder.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Rendering: {Path(pdf_path).name}")
    print(f"  Brand: {brand}  |  Model: {model}  |  Type: {doc_type}")
    print(f"  DPI: {dpi}")
    print(f"{'='*60}\n")

    # Open the PDF
    doc = pymupdf.open(pdf_path)
    total_pages = len(doc)
    print(f"  Total pages: {total_pages}")
    print(f"  Output folder: {output_folder}\n")

    # Render each page
    # zoom factor converts DPI to PyMuPDF's matrix scale (72 dpi is the base)
    zoom   = dpi / 72
    matrix = pymupdf.Matrix(zoom, zoom)

    saved_paths = []

    for page_num in range(total_pages):
        page     = doc[page_num]
        pixmap   = page.get_pixmap(matrix=matrix)

        # Save as PNG with zero-padded page number (001, 002, ...)
        img_path = output_folder / f"page_{page_num + 1:03d}.png"
        pixmap.save(str(img_path))
        saved_paths.append(str(img_path))

        # Live progress — show every page so you can see it working
        print(f"  ✓ Page {page_num + 1:3d}/{total_pages}  →  {img_path.name}  "
              f"({pixmap.width}×{pixmap.height}px)")

    doc.close()

    print(f"\n  ✅ Done! {total_pages} pages rendered.")
    print(f"  📁 Saved to: {output_folder}/\n")

    return saved_paths


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Render PDF pages as images for ColPali indexing."
    )
    parser.add_argument("--pdf",      required=True,  help="Path to the PDF file")
    parser.add_argument("--brand",    required=True,  help="Car brand (e.g. Hyundai)")
    parser.add_argument("--model",    required=True,  help="Car model (e.g. 'IONIQ 6')")
    parser.add_argument("--doc_type", required=True,  help="catalog or manual")
    parser.add_argument("--dpi",      type=int, default=150, help="Resolution (default: 150)")

    args = parser.parse_args()

    render_pdf(
        pdf_path  = args.pdf,
        brand     = args.brand,
        model     = args.model,
        doc_type  = args.doc_type,
        dpi       = args.dpi,
    )
