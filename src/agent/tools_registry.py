"""
src/agent/tools_registry.py
Maps every tool to:
  1. Its OpenAI function schema (what the Realtime API sees)
  2. Its Python implementation (what we call when the API fires it)
"""

from src.tools.sales import search_vehicles, get_vehicle_details, compare_vehicles
from src.tools.booking import list_available_slots, book_slot, cancel_slot
from src.tools.maintenance import get_customer_service_history, get_next_service_recommendation
from src.tools.parts import find_parts, check_part_stock
# ── TRIAL: web search — remove the next line to disable ──────────────────────
from src.tools.web_search import search_web

# ---------------------------------------------------------------------------
# Python callables — keyed by function name
# ---------------------------------------------------------------------------
TOOL_IMPLEMENTATIONS: dict = {
    "search_vehicles":                search_vehicles,
    "get_vehicle_details":            get_vehicle_details,
    "compare_vehicles":               compare_vehicles,
    "list_available_slots":           list_available_slots,
    "book_slot":                      book_slot,
    "cancel_slot":                    cancel_slot,
    "get_customer_service_history":   get_customer_service_history,
    "get_next_service_recommendation": get_next_service_recommendation,
    "find_parts":                     find_parts,
    "check_part_stock":               check_part_stock,
    # ── TRIAL: web search — remove the next line to disable ──────────────────
    "search_web":                     search_web,
}

# ---------------------------------------------------------------------------
# OpenAI Realtime API tool schemas
# ---------------------------------------------------------------------------
TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "name": "search_vehicles",
        "description": "Search available EVs matching the customer's criteria (price, range, brand, body type, seats, drivetrain).",
        "parameters": {
            "type": "object",
            "properties": {
                "max_price_eur":  {"type": "integer", "description": "Maximum base price in EUR"},
                "min_range_km":   {"type": "integer", "description": "Minimum WLTP range in km"},
                "brand":          {"type": "string",  "description": "Brand name e.g. Volkswagen, Kia, Renault"},
                "model":          {"type": "string",  "description": "Model name e.g. EV6, ID.4, IONIQ 5"},
                "body_type":      {"type": "string",  "description": "Body style: hatchback, suv, sedan, mpv, coupe"},
                "min_seats":      {"type": "integer", "description": "Minimum number of seats"},
                "drivetrain":     {"type": "string",  "description": "FWD, RWD, or AWD"},
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "get_vehicle_details",
        "description": "Get full technical specs and inventory details for a specific vehicle model.",
        "parameters": {
            "type": "object",
            "properties": {
                "brand": {"type": "string", "description": "Brand name"},
                "model": {"type": "string", "description": "Model name e.g. ID.4, EV6, IONIQ 5"},
            },
            "required": ["brand", "model"],
        },
    },
    {
        "type": "function",
        "name": "compare_vehicles",
        "description": "Compare two or three vehicles side by side using their IDs.",
        "parameters": {
            "type": "object",
            "properties": {
                "vehicle_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of vehicle IDs to compare (2-3 max)",
                },
            },
            "required": ["vehicle_ids"],
        },
    },
    {
        "type": "function",
        "name": "list_available_slots",
        "description": "List open appointment slots for test drives, maintenance, or parts fitting.",
        "parameters": {
            "type": "object",
            "properties": {
                "appointment_type": {
                    "type": "string",
                    "enum": ["test_drive", "maintenance", "parts_fitting"],
                    "description": "Type of appointment",
                },
                "brand":      {"type": "string",  "description": "Filter by vehicle brand for test drives"},
                "model":      {"type": "string",  "description": "Filter by vehicle model for test drives"},
                "days_ahead": {"type": "integer", "description": "How many days ahead to search (default 7)"},
            },
            "required": ["appointment_type"],
        },
    },
    {
        "type": "function",
        "name": "book_slot",
        "description": "Book an appointment slot for a customer.",
        "parameters": {
            "type": "object",
            "properties": {
                "slot_id":        {"type": "integer", "description": "The slot ID to book"},
                "customer_name":  {"type": "string",  "description": "Full name of the customer"},
                "customer_phone": {"type": "string",  "description": "Customer phone number"},
            },
            "required": ["slot_id", "customer_name", "customer_phone"],
        },
    },
    {
        "type": "function",
        "name": "cancel_slot",
        "description": "Cancel an existing booking by slot ID, verified by customer phone.",
        "parameters": {
            "type": "object",
            "properties": {
                "slot_id":        {"type": "integer", "description": "The slot ID to cancel"},
                "customer_phone": {"type": "string",  "description": "Phone number used at booking time"},
            },
            "required": ["slot_id", "customer_phone"],
        },
    },
    {
        "type": "function",
        "name": "get_customer_service_history",
        "description": "Look up a customer's vehicle service history by phone or name.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_phone": {"type": "string", "description": "Customer phone number"},
                "customer_name":  {"type": "string", "description": "Customer full or partial name"},
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "get_next_service_recommendation",
        "description": "Based on service history, recommend what maintenance is due next.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_phone": {"type": "string", "description": "Customer phone number"},
            },
            "required": ["customer_phone"],
        },
    },
    {
        "type": "function",
        "name": "find_parts",
        "description": "Search the parts catalog by name, category, or compatible vehicle.",
        "parameters": {
            "type": "object",
            "properties": {
                "part_name":    {"type": "string",  "description": "Part name or keyword"},
                "category":     {"type": "string",  "description": "Part category e.g. battery, brakes, charging"},
                "brand":        {"type": "string",  "description": "Compatible vehicle brand"},
                "model":        {"type": "string",  "description": "Compatible vehicle model"},
                "in_stock_only":{"type": "boolean", "description": "Only return parts currently in stock (default true)"},
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "check_part_stock",
        "description": "Check real-time stock and lead time for a specific part by ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "part_id": {"type": "integer", "description": "The part ID to check"},
            },
            "required": ["part_id"],
        },
    },
    # ── TRIAL: web search — remove this entire block to disable ──────────────
    {
        "type": "function",
        "name": "search_web",
        "description": (
            "Search the web for EV and car knowledge NOT found in the dealership database. "
            "Use ONLY for: infotainment features, safety ratings, trim options, charging "
            "compatibility, real-world range, warranty terms, or any specific model feature "
            "the customer asks about. Do NOT use for vehicle availability, pricing, or "
            "anything the database tools already cover."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A specific, focused search query e.g. 'Mercedes EQB screen size infotainment 2025'",
                },
            },
            "required": ["query"],
        },
    },
    # ─────────────────────────────────────────────────────────────────────────
]
