"""
01_scrape_ev_specs.py — OttO Data Pipeline, Step 1
Scrapes EV technical specs from evspecs.org for all 22 VoltDrive models.

Strategy:
  - For each model, fetch the index page → grab all variant URLs → pick first (base) + last (top)
  - Per variant page: extract JSON-LD (schema.org) for most fields + targeted HTML for
    range_wltp_km, ac_charging_kw, dc_charging_kw
  - Raw HTML is saved to data/raw/ before parsing — scraper never re-fetches a saved page
  - Polite crawling: 2s delay between requests
  - IONIQ 9 is sourced from ultimatespecs.com (not on evspecs.org yet)

Output: data/interim/ev_specs_raw.csv
"""

import json
import re
import time
import csv
import os
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
INTERIM_DIR = BASE_DIR / "data" / "interim"

RAW_DIR.mkdir(parents=True, exist_ok=True)
INTERIM_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_CSV = INTERIM_DIR / "ev_specs_raw.csv"

# ---------------------------------------------------------------------------
# Model catalog — the 22 VoltDrive EV models
#
# Each entry has:
#   brand       : display brand name
#   model       : display model name
#   index_url   : the model's variant-listing page on evspecs.org
#   source      : "evspecs" (default) or "ultimatespecs" (fallback)
#
# index_url for ultimatespecs entries is the direct spec page URL (no variant
# index — we just scrape the one page).
# ---------------------------------------------------------------------------
MODELS = [
    # Renault
    {"brand": "Renault", "model": "R5 E-Tech",      "index_url": "https://www.evspecs.org/tech-specs/renault/5-e-tech-electric/"},
    {"brand": "Renault", "model": "R4 E-Tech",      "index_url": "https://www.evspecs.org/tech-specs/renault/4-e-tech-electric/"},
    {"brand": "Renault", "model": "Megane E-Tech",  "index_url": "https://www.evspecs.org/tech-specs/renault/megane-e-tech-electric/"},
    {"brand": "Renault", "model": "Scenic E-Tech",  "index_url": "https://www.evspecs.org/tech-specs/renault/scenic-e-tech-electric/"},
    # Volkswagen
    {"brand": "Volkswagen", "model": "ID.3",        "index_url": "https://www.evspecs.org/tech-specs/volkswagen/id-3/"},
    {"brand": "Volkswagen", "model": "ID.4",        "index_url": "https://www.evspecs.org/tech-specs/volkswagen/id-4/"},
    {"brand": "Volkswagen", "model": "ID.7",        "index_url": "https://www.evspecs.org/tech-specs/volkswagen/id-7/"},
    {"brand": "Volkswagen", "model": "ID.Buzz",     "index_url": "https://www.evspecs.org/tech-specs/volkswagen/id-buzz/"},
    # Kia
    {"brand": "Kia", "model": "EV3",               "index_url": "https://www.evspecs.org/tech-specs/kia/ev3/"},
    {"brand": "Kia", "model": "EV6",               "index_url": "https://www.evspecs.org/tech-specs/kia/ev6/"},
    {"brand": "Kia", "model": "EV9",               "index_url": "https://www.evspecs.org/tech-specs/kia/ev9/"},
    # Hyundai
    {"brand": "Hyundai", "model": "KONA Electric", "index_url": "https://www.evspecs.org/tech-specs/hyundai/kona-electric/"},
    {"brand": "Hyundai", "model": "IONIQ 5",       "index_url": "https://www.evspecs.org/tech-specs/hyundai/ioniq-5/"},
    {"brand": "Hyundai", "model": "IONIQ 6",       "index_url": "https://www.evspecs.org/tech-specs/hyundai/ioniq-6/"},
    # IONIQ 9 is not yet on evspecs.org — row is injected from MANUAL_ENTRIES below
    # {"brand": "Hyundai", "model": "IONIQ 9", ...},  # handled separately
    # Audi
    {"brand": "Audi", "model": "Q4 e-tron",        "index_url": "https://www.evspecs.org/tech-specs/audi/q4-e-tron/"},
    {"brand": "Audi", "model": "Q6 e-tron",        "index_url": "https://www.evspecs.org/tech-specs/audi/q6-e-tron/"},
    {"brand": "Audi", "model": "A6 e-tron",        "index_url": "https://www.evspecs.org/tech-specs/audi/a6-sportback-e-tron/"},
    # Mercedes-Benz
    {"brand": "Mercedes", "model": "EQA",           "index_url": "https://www.evspecs.org/tech-specs/mercedes-benz/eqa/"},
    {"brand": "Mercedes", "model": "EQB",           "index_url": "https://www.evspecs.org/tech-specs/mercedes-benz/eqb/"},
    {"brand": "Mercedes", "model": "EQS",           "index_url": "https://www.evspecs.org/tech-specs/mercedes-benz/eqs/"},
    {"brand": "Mercedes", "model": "EQE",           "index_url": "https://www.evspecs.org/tech-specs/mercedes-benz/eqe/"},
]

# ---------------------------------------------------------------------------
# MSRP lookup — base price in EUR per model (hardcoded, sourced from
# official European market list prices as of early 2025).
# The cleaning script will use these to derive dealer_price_eur.
# ---------------------------------------------------------------------------
MSRP_EUR = {
    ("Renault",    "R5 E-Tech"):      25000,
    ("Renault",    "R4 E-Tech"):      32000,
    ("Renault",    "Megane E-Tech"):  35000,
    ("Renault",    "Scenic E-Tech"):  40000,
    ("Volkswagen", "ID.3"):           35000,
    ("Volkswagen", "ID.4"):           44000,
    ("Volkswagen", "ID.7"):           57000,
    ("Volkswagen", "ID.Buzz"):        60000,
    ("Kia",        "EV3"):            36000,
    ("Kia",        "EV6"):            46000,
    ("Kia",        "EV9"):            70000,
    ("Hyundai",    "KONA Electric"):  35000,
    ("Hyundai",    "IONIQ 5"):        45000,
    ("Hyundai",    "IONIQ 6"):        43000,
    ("Hyundai",    "IONIQ 9"):        75000,
    ("Audi",       "Q4 e-tron"):      47000,
    ("Audi",       "Q6 e-tron"):      63000,
    ("Audi",       "A6 e-tron"):      75000,
    ("Mercedes",   "EQA"):            51000,
    ("Mercedes",   "EQB"):            54000,
    ("Mercedes",   "EQS"):           105000,
    ("Mercedes",   "EQE"):            75000,
}

# ---------------------------------------------------------------------------
# HTTP session — shared across all requests
# ---------------------------------------------------------------------------
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})

CRAWL_DELAY = 2  # seconds between requests — polite scraping


# ---------------------------------------------------------------------------
# Utility: fetch a URL, save raw HTML, and return the HTML string
# If the raw file already exists on disk, load from disk instead.
# ---------------------------------------------------------------------------
def fetch_html(url: str, filename: str) -> str:
    """
    Fetch a URL and cache the raw HTML to data/raw/<filename>.html.
    On subsequent runs, load from disk — never re-scrape a saved page.
    """
    filepath = RAW_DIR / f"{filename}.html"

    if filepath.exists():
        print(f"  [cache] Loading from disk: {filepath.name}")
        return filepath.read_text(encoding="utf-8")

    print(f"  [fetch] GET {url}")
    response = SESSION.get(url, timeout=15)
    response.raise_for_status()

    filepath.write_text(response.text, encoding="utf-8")
    print(f"  [saved] {filepath.name} ({len(response.text):,} bytes)")

    time.sleep(CRAWL_DELAY)
    return response.text


# ---------------------------------------------------------------------------
# Step 1: Given a model's index page, return [first_url, last_url]
# The index page lists all variants — we keep base (first) + top (last).
# If single_page=True, the index_url IS the spec page — return it directly.
# ---------------------------------------------------------------------------
def get_variant_urls(model: dict, html: str) -> list[str]:
    """
    Parse the model index page and return [base_variant_url, top_variant_url].
    Uses BeautifulSoup to find all <a> links that point to sub-variant pages.
    """
    if model.get("single_page"):
        return [model["index_url"]]

    soup = BeautifulSoup(html, "html.parser")
    base_url = model["index_url"].rstrip("/")

    # Variant links are <a href="/tech-specs/brand/model/variant-slug">
    # We match links that extend the base path by exactly one segment.
    variant_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Normalise to absolute URL
        if href.startswith("/"):
            href = "https://www.evspecs.org" + href

        # Must extend the base model URL by exactly one path segment
        # e.g. base_url = ".../kia/ev6"  →  keep ".../kia/ev6/rwd" but not ".../kia/ev6"
        if (
            href.startswith(base_url + "/")
            and href.count("/") == base_url.count("/") + 1
            and not href.endswith("/compare/")
        ):
            if href not in variant_links:
                variant_links.append(href)

    if not variant_links:
        print(f"  [warn] No variant links found for {model['brand']} {model['model']}")
        return []

    # Keep first (base/cheapest) and last (top/most powerful)
    selected = [variant_links[0]]
    if len(variant_links) > 1:
        selected.append(variant_links[-1])

    print(f"  [variants] Found {len(variant_links)} total → keeping: {[u.split('/')[-1] for u in selected]}")
    return selected


# ---------------------------------------------------------------------------
# Step 2a: Extract fields from the JSON-LD (schema.org) block
# This is the primary extraction path — clean, structured, no regex needed.
# ---------------------------------------------------------------------------
def extract_jsonld(html: str) -> dict:
    """
    Find the schema.org/Car JSON-LD block in the page and extract all fields
    that map directly to our schema. Returns a dict of raw values.
    """
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    for script in soup.find_all("script"):
        text = script.string or ""
        if '"@type": "Car"' not in text and '"@type":"Car"' not in text:
            continue
        try:
            ld = json.loads(text.strip())
        except json.JSONDecodeError:
            continue

        # --- Identity ---
        data["name"]    = ld.get("name", "")           # e.g. "Kia EV6 RWD"
        data["model"]   = ld.get("model", "")           # e.g. "EV6"
        data["variant"] = ld.get("vehicleConfiguration", "")  # e.g. "RWD"
        data["year"]    = ld.get("modelDate", "")

        # --- Classification ---
        data["body_type"]  = ld.get("bodyType", "")
        data["drivetrain"] = _map_drivetrain(ld.get("driveWheelConfiguration", ""))
        data["seats"]      = ld.get("seatingCapacity", "")

        # --- Battery (useable kWh) ---
        for entry in ld.get("fuelCapacity", []):
            if entry.get("valueReference", {}).get("unitText") == "Useable Battery Capacity":
                data["battery_kwh"] = entry.get("value", "")

        # --- Performance ---
        data["top_speed_kmh"] = ld.get("speed", {}).get("value", "")

        # Acceleration: find "0..100 MPH" entry
        for entry in ld.get("accelerationTime", []):
            if entry.get("valueReference", {}).get("unitText") == "0..100 MPH":
                data["acceleration_0_100mph_s"] = entry.get("value", "")

        # --- Weight & Dimensions ---
        data["weight_kg"] = ld.get("weightTotal", {}).get("value", "")
        data["length_mm"] = ld.get("depth", {}).get("value", "")   # schema.org uses "depth" for length
        data["width_mm"]  = ld.get("width", {}).get("value", "")
        data["height_mm"] = ld.get("height", {}).get("value", "")

        # --- Cargo ---
        for entry in ld.get("cargoVolume", []):
            if entry.get("valueReference", {}).get("unitText") == "Trunk/Boot Space":
                data["cargo_l"] = entry.get("value", "")

        break  # Only one Car JSON-LD block per page

    return data


# ---------------------------------------------------------------------------
# Step 2b: Extract the 3 fields NOT in JSON-LD from the HTML directly
# ---------------------------------------------------------------------------
def extract_html_fields(html: str) -> dict:
    """
    Extract WLTP range, AC charging speed, and DC charging speed from
    the rendered HTML using stable CSS class names.
    """
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    # --- WLTP Range ---
    # HTML: <span class="value metric"> 581<i> km</i></span>
    # The range label anchor contains "Range (WLTP)" in its text
    for p in soup.find_all("p"):
        label = p.find("span", class_="label")
        if label and "Range (WLTP)" in label.get_text():
            value_span = p.find("span", class_="value metric")
            if value_span:
                # Extract only the numeric part (strip the <i> km tag)
                raw = value_span.get_text(separator=" ").strip()
                data["range_wltp_km"] = re.sub(r"[^\d]", "", raw.split()[0])
            break

    # --- AC Charging ---
    # HTML: <li class="ac-standard"><span class="label">...<span class="value"> 11<span class="unit"> kW</span>
    ac_li = soup.find("li", class_="ac-standard")
    if ac_li:
        value_span = ac_li.find("span", class_="value")
        if value_span:
            raw = value_span.get_text().strip()
            data["ac_charging_kw"] = re.sub(r"[^\d.]", "", raw)

    # --- DC Fast Charging ---
    # HTML: <li class="dc-max"><span class="label">...<span class="value"> 258...
    dc_li = soup.find("li", class_="dc-max")
    if dc_li:
        value_span = dc_li.find("span", class_="value")
        if value_span:
            raw = value_span.get_text().strip()
            data["dc_charging_kw"] = re.sub(r"[^\d.]", "", raw)

    return data


# ---------------------------------------------------------------------------
# Helper: normalise drivetrain string to FWD / RWD / AWD
# ---------------------------------------------------------------------------
def _map_drivetrain(raw: str) -> str:
    mapping = {
        "front": "FWD",
        "rear":  "RWD",
        "all":   "AWD",
        "four":  "AWD",
    }
    return mapping.get(raw.lower(), raw)


# ---------------------------------------------------------------------------
# Step 3: Scrape a single variant page and return a merged row dict
# ---------------------------------------------------------------------------
def scrape_variant(brand: str, model_name: str, variant_url: str, source: str = "evspecs") -> Optional[dict]:
    """
    Fetch a variant spec page, extract all fields, and return a flat dict
    ready to be written as a CSV row.
    """
    # Build a safe filename from the URL path
    slug = variant_url.rstrip("/").replace("https://www.evspecs.org/tech-specs/", "").replace("https://www.ultimatespecs.com/", "")
    filename = slug.replace("/", "_")

    try:
        html = fetch_html(variant_url, filename)
    except requests.RequestException as e:
        print(f"  [error] Failed to fetch {variant_url}: {e}")
        return None

    if source == "evspecs":
        jsonld_data  = extract_jsonld(html)
        html_data    = extract_html_fields(html)
        extracted    = {**jsonld_data, **html_data}
    else:
        # ultimatespecs fallback: basic HTML extraction only
        extracted = extract_ultimatespecs(html)

    if not extracted:
        print(f"  [warn] No data extracted from {variant_url}")
        return None

    # Build the final flat row, normalising field names to our schema
    row = {
        "brand":                 brand,
        "model":                 model_name,
        "variant":               extracted.get("variant", ""),
        "year":                  extracted.get("year", ""),
        "body_type":             extracted.get("body_type", ""),
        "drivetrain":            extracted.get("drivetrain", ""),
        "seats":                 extracted.get("seats", ""),
        "battery_kwh":           extracted.get("battery_kwh", ""),
        "range_wltp_km":         extracted.get("range_wltp_km", ""),
        "ac_charging_kw":        extracted.get("ac_charging_kw", ""),
        "dc_charging_kw":        extracted.get("dc_charging_kw", ""),
        "acceleration_0_100mph_s": extracted.get("acceleration_0_100mph_s", ""),
        "top_speed_kmh":         extracted.get("top_speed_kmh", ""),
        "cargo_l":               extracted.get("cargo_l", ""),
        "length_mm":             extracted.get("length_mm", ""),
        "width_mm":              extracted.get("width_mm", ""),
        "height_mm":             extracted.get("height_mm", ""),
        "weight_kg":             extracted.get("weight_kg", ""),
        "base_price_eur":        MSRP_EUR.get((brand, model_name), ""),
        "source_url":            variant_url,
    }

    return row


# ---------------------------------------------------------------------------
# Ultimatespecs fallback parser (for IONIQ 9)
# Extracts specs from ultimatespecs.com HTML structure
# ---------------------------------------------------------------------------
def extract_ultimatespecs(html: str) -> dict:
    """
    Basic HTML extraction for ultimatespecs.com pages.
    The site uses <div class="techspec-row"> with label/value pairs.
    """
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    # ultimatespecs wraps each spec in a table with th (label) and td (value)
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).lower()
            value = cells[1].get_text(strip=True)

            if "0-100" in label and "km/h" not in label:
                data["acceleration_0_100mph_s"] = re.sub(r"[^\d.]", "", value)
            elif "top speed" in label:
                data["top_speed_kmh"] = re.sub(r"[^\d.]", "", value)
            elif "range" in label and "wltp" in label:
                data["range_wltp_km"] = re.sub(r"[^\d]", "", value.split()[0])
            elif "battery" in label and ("usable" in label or "useable" in label or "net" in label):
                data["battery_kwh"] = re.sub(r"[^\d.]", "", value)
            elif "ac" in label and "charg" in label:
                data["ac_charging_kw"] = re.sub(r"[^\d.]", "", value)
            elif "dc" in label and "charg" in label:
                data["dc_charging_kw"] = re.sub(r"[^\d.]", "", value)
            elif "cargo" in label or "boot" in label or "trunk" in label:
                data["cargo_l"] = re.sub(r"[^\d]", "", value.split()[0])
            elif "seats" in label or "seating" in label:
                data["seats"] = re.sub(r"[^\d]", "", value)
            elif "weight" in label and "kerb" in label:
                data["weight_kg"] = re.sub(r"[^\d]", "", value)
            elif "length" in label:
                data["length_mm"] = re.sub(r"[^\d]", "", value)
            elif "width" in label:
                data["width_mm"] = re.sub(r"[^\d]", "", value)
            elif "height" in label:
                data["height_mm"] = re.sub(r"[^\d]", "", value)

    # Try to get body type and drivetrain from page title / header
    h1 = soup.find("h1")
    if h1:
        data["name"] = h1.get_text(strip=True)

    data["body_type"] = "SUV"      # IONIQ 9 is an SUV
    data["drivetrain"] = "AWD"     # AWD variant
    data["year"] = "2025"
    data["variant"] = "AWD"

    return data


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Manual entries — models not on evspecs.org, verified from official sources
# IONIQ 9: ultimatespecs.com (Long Range AWD, 2025)
# ---------------------------------------------------------------------------
MANUAL_ENTRIES = [
    {
        "brand": "Hyundai", "model": "IONIQ 9", "variant": "Long Range AWD", "year": "2025",
        "body_type": "SUV", "drivetrain": "AWD", "seats": "7",
        "battery_kwh": "110.3", "range_wltp_km": "600",
        "ac_charging_kw": "11", "dc_charging_kw": "260",
        "acceleration_0_100mph_s": "",  # only 0-100 km/h available: 6.7s (converted in cleaning)
        "top_speed_kmh": "200",
        "cargo_l": "620", "length_mm": "5060", "width_mm": "1980", "height_mm": "1791",
        "weight_kg": "2657",
        "base_price_eur": MSRP_EUR.get(("Hyundai", "IONIQ 9"), ""),
        "source_url": "https://www.ultimatespecs.com/car-specs/Hyundai/149495/Hyundai-Ioniq-9-Long-Range-AWD.html",
    },
]

CSV_FIELDS = [
    "brand", "model", "variant", "year",
    "body_type", "drivetrain", "seats",
    "battery_kwh", "range_wltp_km",
    "ac_charging_kw", "dc_charging_kw",
    "acceleration_0_100mph_s", "top_speed_kmh",
    "cargo_l", "length_mm", "width_mm", "height_mm", "weight_kg",
    "base_price_eur", "source_url",
]


def main():
    print("=" * 60)
    print("OttO — EV Specs Scraper")
    print(f"Output: {OUTPUT_CSV}")
    print("=" * 60)

    rows = []

    for model in MODELS:
        brand      = model["brand"]
        model_name = model["model"]
        source     = model.get("source", "evspecs")

        print(f"\n[{brand} {model_name}]")

        # --- Fetch index page and find variant URLs ---
        index_filename = f"index_{brand.lower()}_{model_name.lower().replace(' ', '_').replace('.', '')}"

        if model.get("single_page"):
            variant_urls = [model["index_url"]]
        else:
            try:
                index_html = fetch_html(model["index_url"], index_filename)
            except requests.RequestException as e:
                print(f"  [error] Could not fetch index: {e}")
                continue
            variant_urls = get_variant_urls(model, index_html)

        if not variant_urls:
            print(f"  [skip] No variants found — skipping {brand} {model_name}")
            continue

        # --- Scrape each selected variant ---
        for url in variant_urls:
            print(f"  Scraping: {url.split('/')[-1]}")
            row = scrape_variant(brand, model_name, url, source=source)
            if row:
                rows.append(row)
                print(f"  [ok] battery={row['battery_kwh']} kWh | range={row['range_wltp_km']} km | ac={row['ac_charging_kw']} kW | dc={row['dc_charging_kw']} kW")

    # --- Inject manual entries ---
    for entry in MANUAL_ENTRIES:
        rows.append(entry)
        print(f"\n[manual] Injected: {entry['brand']} {entry['model']} {entry['variant']}")

    # --- Write CSV ---
    print(f"\n{'=' * 60}")
    print(f"Writing {len(rows)} rows to {OUTPUT_CSV}")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done. CSV saved: {OUTPUT_CSV}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
