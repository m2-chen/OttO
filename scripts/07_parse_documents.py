"""
scripts/07_parse_documents.py

RAG Pipeline — Step 1: Document Parsing with Docling

What this script does:
- Takes a PDF file (car catalog or owner manual) as input
- Runs Docling's full pipeline: layout analysis, OCR, image extraction, table recognition
- Saves structured output as JSON (one entry per document element)
- Saves all extracted images as PNG files
- Prints a human-readable summary of what was found

Usage:
    python scripts/07_parse_documents.py --pdf /path/to/file.pdf --brand Renault --model "R5 E-Tech" --doc_type catalog

Output structure:
    data/rag/
    ├── parsed/
    │   └── renault_r5-e-tech_catalog.json      ← structured content
    └── images/
        └── renault_r5-e-tech_catalog/
            ├── page_1_img_1.png
            ├── page_3_img_1.png
            └── ...
"""

import argparse
import json
import os
import re
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import PdfFormatOption


# ── Output directories ────────────────────────────────────────────────────────

RAG_DIR      = Path("data/rag")
PARSED_DIR   = RAG_DIR / "parsed"
IMAGES_DIR   = RAG_DIR / "images"

PARSED_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Convert 'R5 E-Tech' → 'r5-e-tech' for use in file names."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_output_name(brand: str, model: str, doc_type: str) -> str:
    """Build a consistent file/folder name: renault_r5-e-tech_catalog"""
    return f"{slugify(brand)}_{slugify(model)}_{slugify(doc_type)}"


# ── Main parsing function ─────────────────────────────────────────────────────

def parse_document(pdf_path: str, brand: str, model: str, doc_type: str) -> dict:
    """
    Run Docling on a PDF and return structured output.

    Docling analyzes the PDF page by page using computer vision models:
    - Detects layout: text blocks, images, tables, headings
    - Runs OCR on image-embedded text
    - Extracts and saves images as separate files
    - Preserves reading order and element relationships

    Returns a dict with metadata + list of elements (one per detected block).
    """

    print(f"\n{'='*60}")
    print(f"  Parsing: {Path(pdf_path).name}")
    print(f"  Brand:   {brand}  |  Model: {model}  |  Type: {doc_type}")
    print(f"{'='*60}\n")

    # ── Configure Docling pipeline ────────────────────────────────────────────
    # We enable:
    # - generate_page_images: renders each page as an image (needed for ColPali later)
    # - generate_picture_images: extracts individual images from the PDF
    # - do_ocr: runs OCR on image-embedded text (critical for catalogs)
    # - do_table_structure: recognises tables (critical for spec sheets)

    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_page_images    = True   # full page renders
    pipeline_options.generate_picture_images = True   # individual extracted images
    pipeline_options.do_ocr                  = True   # OCR for image-embedded text
    pipeline_options.do_table_structure      = True   # structured table recognition

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    # ── Run the pipeline ──────────────────────────────────────────────────────
    print("  Running Docling pipeline (this may take 1–3 minutes for a catalog)...")
    result = converter.convert(pdf_path)
    doc    = result.document

    # ── Set up image output folder ────────────────────────────────────────────
    output_name   = build_output_name(brand, model, doc_type)
    images_folder = IMAGES_DIR / output_name
    images_folder.mkdir(parents=True, exist_ok=True)

    # ── Extract and save page images ──────────────────────────────────────────
    # These are full-page renders — what ColPali will consume in the next step
    saved_page_images = []
    if hasattr(doc, 'pages') and doc.pages:
        for page_no, page in doc.pages.items():
            if page.image and page.image.pil_image:
                img_path = images_folder / f"page_{page_no}.png"
                page.image.pil_image.save(img_path)
                saved_page_images.append(str(img_path))

    # ── Extract and save individual picture images ────────────────────────────
    # These are individual images extracted from the PDF (car photos, diagrams, etc.)
    saved_picture_images = []
    for element, _ in doc.iterate_items():
        element_type = type(element).__name__

        if element_type == "PictureItem":
            if hasattr(element, 'image') and element.image and element.image.pil_image:
                page_no  = element.prov[0].page_no if element.prov else 0
                img_idx  = len(saved_picture_images) + 1
                img_path = images_folder / f"page_{page_no}_picture_{img_idx}.png"
                element.image.pil_image.save(img_path)
                saved_picture_images.append(str(img_path))

    # ── Build structured elements list ────────────────────────────────────────
    # Each element = one detected block (heading, paragraph, table, image, etc.)
    # This is what we'll use for metadata, filtering, and text-based retrieval
    elements = []

    for element, _ in doc.iterate_items():
        element_type = type(element).__name__

        # Extract text content
        text = ""
        if hasattr(element, 'text') and element.text:
            text = element.text.strip()
        elif hasattr(element, 'export_to_markdown'):
            try:
                text = element.export_to_markdown().strip()
            except Exception:
                pass

        # Get page number
        page_no = None
        if hasattr(element, 'prov') and element.prov:
            page_no = element.prov[0].page_no

        if not text and element_type not in ("PictureItem",):
            continue

        elements.append({
            "type":    element_type,
            "page":    page_no,
            "text":    text,
            "brand":   brand,
            "model":   model,
            "doc_type": doc_type,
        })

    # ── Build final output structure ──────────────────────────────────────────
    output = {
        "metadata": {
            "brand":        brand,
            "model":        model,
            "doc_type":     doc_type,
            "source_file":  str(pdf_path),
            "total_pages":  len(doc.pages) if hasattr(doc, 'pages') else 0,
            "total_elements": len(elements),
            "page_images":  saved_page_images,
            "picture_images": saved_picture_images,
        },
        "elements": elements
    }

    # ── Save JSON ─────────────────────────────────────────────────────────────
    json_path = PARSED_DIR / f"{output_name}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f"\n  ✅ Parsing complete!")
    print(f"\n  📄 Document summary:")
    print(f"     Total pages:          {output['metadata']['total_pages']}")
    print(f"     Total elements found: {output['metadata']['total_elements']}")
    print(f"     Page images saved:    {len(saved_page_images)}")
    print(f"     Picture images saved: {len(saved_picture_images)}")

    # Count by element type
    type_counts = {}
    for el in elements:
        type_counts[el["type"]] = type_counts.get(el["type"], 0) + 1
    print(f"\n  📊 Element breakdown:")
    for el_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"     {el_type:<25} {count}")

    print(f"\n  💾 Saved to:")
    print(f"     JSON:   {json_path}")
    print(f"     Images: {images_folder}/")
    print()

    return output


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Parse a car PDF (catalog or manual) using Docling."
    )
    parser.add_argument("--pdf",      required=True,  help="Path to the PDF file")
    parser.add_argument("--brand",    required=True,  help="Car brand (e.g. Renault)")
    parser.add_argument("--model",    required=True,  help="Car model (e.g. 'R5 E-Tech')")
    parser.add_argument("--doc_type", required=True,  help="Document type: catalog or manual")

    args = parser.parse_args()

    parse_document(
        pdf_path  = args.pdf,
        brand     = args.brand,
        model     = args.model,
        doc_type  = args.doc_type,
    )
