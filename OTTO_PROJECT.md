# OttO — AI Voice Agent for EV Dealerships
> Capstone Project | Autonomous Voice AI System

---

## 1. Project Overview

**OttO** is a real-time AI voice agent that handles inbound calls for a premium electric-vehicle dealership, fully autonomously, 24 hours a day. When a customer calls, OttO picks up instantly, understands what they need, and helps them — whether they want to explore vehicles, book a test drive, check their service history, or find a part. No hold music. No call queue. No after-hours voicemail.

### The Dealership — "EV Land"
A fictional multi-brand EV-only dealership inspired by real European dealers. EV Land sells exclusively battery-electric vehicles from 7 brands covering every price segment of the European EV market. No ICE. No PHEV. The focused scope creates a clean, defensible knowledge boundary for the AI.

**Market context:** BEV market share crossed 20% in Europe in 2025. SUVs dominate new-car sales at 59%. Multi-brand EV dealerships are a growing format. The catalog directly mirrors this reality.

### Key Architectural Decision: Single Agent over Multi-Agent
The original specification called for a multi-agent system — a Receptionist routing to four specialist agents via LangGraph. During implementation this was deliberately collapsed into a single agent.

**Why:** The OpenAI Realtime API maintains a persistent, stateful voice session. Routing mid-call to a separate agent requires either (a) tearing down and restarting the session — which resets all context and introduces an audible gap — or (b) fragile cross-session state serialization. Domain separation is achieved more cleanly through tool design: each domain has its own isolated tool functions. One agent with 12 well-scoped tools beats four agents with 3 tools each in a voice context. Handoff latency is the enemy of a good phone call.

---

## 2. Vehicle Catalog

### 7 Brands — 22 Models — 100% Battery Electric

| Brand | Segment | Models | Price range |
|---|---|---|---|
| **Renault** | Budget / Urban | R5 E-Tech, R4 E-Tech, Mégane E-Tech, Scenic E-Tech | €25k–€47k |
| **Volkswagen** | Volume Mainstream | ID.3, ID.4, ID.7, ID.Buzz | €35k–€65k |
| **Kia** | Korean Value-Premium | EV3, EV6, EV9 | €36k–€75k |
| **Hyundai** | Korean Mid-Premium | KONA Electric, IONIQ 5, IONIQ 6, IONIQ 9 | €35k–€78k |
| **Audi** | Premium German | Q6 e-tron, A6 e-tron | €67k–€90k |
| **Mercedes-Benz** | Luxury Flagship | EQA, EQB, EQS | €50k–€110k |
| **Alpine** | French Performance | A290, A390 | €40k–€60k |

---

## 3. Architecture

### How It Works End to End

```
Browser (WebRTC mic)
        │  PCM16 audio (binary WebSocket frames)
        ▼
┌─────────────────────────────────────────────┐
│           FastAPI Backend                   │
│                                             │
│   RealtimeSession                           │
│   ├── _client_to_openai()  ← audio bridge  │
│   ├── _openai_to_client()  ← event bridge  │
│   └── _execute_tool()      ← tool runner   │
└──────────────────┬──────────────────────────┘
                   │  WebSocket (WSS)
                   ▼
        OpenAI Realtime API
        (gpt-realtime-1.5, ash voice)
```

Audio flows in real time over a single WebSocket in both directions. When OttO decides to call a tool, `RealtimeSession` intercepts the `function_call_arguments.done` event, executes the matching Python function against the live database, serializes the result, and returns it to the OpenAI Realtime API which then speaks the answer.

OttO initiates the greeting automatically — a `response.create` event fires immediately after session configuration. The caller hears OttO speak first, exactly like a receptionist picking up the phone.

### Resilience
- **Browser disconnect:** closing the browser immediately triggers a close on the OpenAI WebSocket, so both coroutines exit cleanly. No 34-second zombie wait for OpenAI's keepalive ping timeout.
- **Malformed frames:** `onmessage` JSON parsing is wrapped in try/catch so a corrupted message never kills the WebSocket connection.
- **Session traces:** written to disk incrementally after every turn and tool call — never lost on hard shutdown.

---

## 4. Tech Stack

| Layer | Technology |
|---|---|
| Voice I/O | OpenAI Realtime API (`gpt-realtime-1.5`, `ash` voice) |
| Backend API | FastAPI + Uvicorn (async Python) |
| Database | PostgreSQL 16 + pgvector (Docker) |
| RAG — Text | pgvector cosine similarity on catalog PDF embeddings (`text-embedding-3-small`) |
| RAG — Photos | pgvector cosine similarity on GPT-4o Vision photo captions |
| Evaluation | `claude-sonnet-4-6` as LLM judge + Streamlit dashboard |
| Email Agent | `claude-sonnet-4-6` for post-call transcript analysis and customer profiling |
| Frontend | Single-page HTML + Vanilla JS (WebAudio API, WebSocket) |
| Containerization | Docker + docker-compose |

---

## 5. Tools — 12 Functions Across 5 Domains

| Tool | Domain | What it does |
|---|---|---|
| `search_vehicles()` | Sales | Filter inventory by brand, body type, budget, range, seats, drivetrain. Returns top 5 matches with stock and dealer price |
| `get_vehicle_details()` | Sales | Full detail on a specific model: stock count, dealer price, colors, marketing description |
| `search_knowledge_base()` | Sales | Semantic RAG search over 22 official PDF catalogs (pgvector). Returns matching page excerpts |
| `search_catalog_photos()` | Sales | Semantic photo search over 890 captioned catalog images (pgvector on GPT-4o captions) |
| `search_web()` | Sales / Maintenance | Web search fallback for info not in the catalog — reviews, incentives, real-world range, warning light explanations |
| `list_available_slots()` | Booking | Real-time appointment availability filtered by type, brand, model, and time window |
| `book_slot()` | Booking | Reserve a slot with row-level DB locking. Returns confirmation with advisor name |
| `request_email_input()` | Booking | Triggers on-screen email modal in the browser UI — used before booking confirmation |
| `get_customer_service_history()` | Maintenance | Look up a customer's last 10 service records by phone number |
| `get_next_service_recommendation()` | Maintenance | Urgency-classified recommendation based on time since last service |
| `find_parts()` | Parts | Search parts catalog by name, category, or compatible model |
| `check_part_stock()` | Parts | Real-time stock and lead time for a specific part |

---

## 6. Data Strategy

### Layer 1 — EV Technical Specifications (Scraped)

**Source:** `evspecs.org` (primary), `ultimatespecs.com` (fallback)

**Fields per variant:** battery capacity, WLTP range, AC/DC charging speeds, 0-100 acceleration, top speed, cargo volume, dimensions, weight, drivetrain, body type, seats, European base price.

**Scripts:**
- `01_scrape_ev_specs.py` — BeautifulSoup scraper, 2s crawl delay, raw HTML saved before parsing
- `02_clean_normalize.py` — WLTP imputation, brand normalization, deduplication, price filtering
- `03_generate_synthetic.py` — LLM-generated dealership data (inventory, customers, appointments, service history, parts) with Pydantic validation and realistic noise injection

### Layer 2 — Catalog Knowledge Base (RAG)

22 official PDF catalogs processed through an 18-script pipeline:

```
07_parse_documents.py       ← PDF → structured JSON (PyMuPDF)
08_render_pages.py          ← PDF pages → PNG images
12_index_text_embeddings.py ← Page text → pgvector (text-embedding-3-small)
16_extract_catalog_photos.py ← Extract photos from PDFs
18_caption_photos.py        ← GPT-4o Vision captions → pgvector
15_batch_pipeline.py        ← Orchestrates the full pipeline
```

**Result:**
- `document_pages_text` table: 22 models × avg 30 pages = ~600 embedded pages
- `catalog_photos` table: 890 photos with semantic captions and embeddings

### Noise Injection (Synthetic Data)
- 8% of inventory: `stock_count = 0` (sold out)
- 5% of service records: `cost_eur = null` (invoice pending)
- 12% of appointment slots: `status = blocked` (technician unavailable)
- 3% of parts: `lead_time_days = null` (supplier unknown)
- No weekend appointments; lunch gap 12:00–13:30 blocked

---

## 7. Database Schema

```sql
-- Vehicle specs from scraper
CREATE TABLE vehicles (
    id              SERIAL PRIMARY KEY,
    brand           VARCHAR(50)  NOT NULL,
    model           VARCHAR(100) NOT NULL,
    variant         VARCHAR(100),
    body_type       VARCHAR(50),
    seats           INTEGER,
    battery_kwh     DECIMAL(5,1),
    range_wltp_km   INTEGER,
    ac_charging_kw  DECIMAL(4,1),
    dc_charging_kw  INTEGER,
    acceleration_s  DECIMAL(4,1),
    top_speed_kmh   INTEGER,
    cargo_l         INTEGER,
    weight_kg       INTEGER,
    drivetrain      VARCHAR(10),
    base_price_eur  INTEGER
);

-- Dealership inventory
CREATE TABLE inventory (
    id              SERIAL PRIMARY KEY,
    vehicle_id      INTEGER REFERENCES vehicles(id),
    color           VARCHAR(50),
    stock_count     INTEGER DEFAULT 0,
    is_demo_car     BOOLEAN DEFAULT FALSE,
    dealer_price_eur INTEGER,
    available_from  DATE,
    marketing_description TEXT
);

-- Appointment calendar
CREATE TABLE appointments (
    id              SERIAL PRIMARY KEY,
    slot_datetime   TIMESTAMP NOT NULL,
    duration_min    INTEGER,
    type            VARCHAR(30),   -- test_drive | maintenance | parts_fitting
    status          VARCHAR(20) DEFAULT 'available',
    customer_name   VARCHAR(100),
    customer_phone  VARCHAR(20),
    customer_email  VARCHAR(100),
    vehicle_brand   VARCHAR(50),
    vehicle_model   VARCHAR(100),
    advisor_name    VARCHAR(100)
);

-- Service history
CREATE TABLE service_history (
    id              SERIAL PRIMARY KEY,
    customer_id     INTEGER REFERENCES customers(id),
    vehicle_id      INTEGER REFERENCES vehicles(id),
    service_type    VARCHAR(50),
    service_date    DATE,
    cost_eur        DECIMAL(8,2),
    technician_name VARCHAR(100),
    notes           TEXT,
    status          VARCHAR(20)
);

-- Parts catalog
CREATE TABLE parts (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100),
    category        VARCHAR(50),
    compatible_brands VARCHAR[],
    compatible_models VARCHAR[],
    price_eur       DECIMAL(8,2),
    stock_count     INTEGER,
    lead_time_days  INTEGER,
    is_ev_specific  BOOLEAN DEFAULT TRUE
);

-- Customers
CREATE TABLE customers (
    id              SERIAL PRIMARY KEY,
    first_name      VARCHAR(50),
    last_name       VARCHAR(50),
    phone           VARCHAR(20),
    email           VARCHAR(100),
    owned_vehicle_id INTEGER REFERENCES vehicles(id)
);

-- RAG — catalog page text embeddings
CREATE TABLE document_pages_text (
    id          SERIAL PRIMARY KEY,
    brand       TEXT,
    model       TEXT,
    doc_type    TEXT,
    page_num    INTEGER,
    page_text   TEXT,
    image_path  TEXT,
    embedding   VECTOR(1536),
    created_at  TIMESTAMP DEFAULT NOW()
);

-- RAG — catalog photo embeddings
CREATE TABLE catalog_photos (
    id          SERIAL PRIMARY KEY,
    brand       TEXT,
    model       TEXT,
    page_num    INTEGER,
    photo_path  TEXT,
    caption     TEXT,
    embedding   VECTOR(1536),
    created_at  TIMESTAMP DEFAULT NOW()
);
```

---

## 8. System Prompt Design

`src/agent/prompts.py` is OttO's behavioral contract. Key sections:

1. **Language rule** — always English, no exceptions
2. **Voice-first rule** — speaking not writing, no lists, no spec sheets. Default is silence after an answer — no reflexive follow-up questions
3. **Domain playbooks** — Sales, Booking, Maintenance, Parts each have explicit behavioral scripts
4. **RAG rules** — always call `search_knowledge_base()` before answering product questions. If 0 pages returned → MUST call `search_web()`. Never answer from model memory. Never state a spec without a tool source
5. **Catalog boundary** — never confirm availability from memory, always go through DB tools. If tool returns nothing, the vehicle is not stocked
6. **Safety rule** — smoke, fire, battery warning → immediate safety instructions override everything
7. **Customer profiling** — passive signal detection (price sensitivity, urgency, decision authority) built into every conversation as a by-product
8. **Guardrails** — loan calculations, insurance, legal → redirect to human advisor with callback offer

---

## 9. Evaluation System

### LLM-as-a-Judge
`claude-sonnet-4-6` evaluates every session independently on 7 dimensions:

| Dimension | Weight | What it measures |
|---|---|---|
| Tool routing | 20% | Did OttO call the right tool type for each situation? |
| Response discipline | 20% | Voice-first compliance, no lists, no fabrication |
| Tool selection | 15% | Correct parameter passing, right sequence |
| RAG faithfulness | 15% | Did spoken answers match tool results? |
| Discovery quality | 10% | Quality of follow-up questions during exploration |
| Guardrail adherence | 10% | Boundary enforcement, no out-of-scope claims |
| Conversation arc | 10% | Did the conversation flow naturally toward resolution? |

### Session Trace
Every session produces a structured JSON trace at `data/session_traces/session_<timestamp>.json`:
- Full transcript (customer + OttO turns with timestamps)
- Every tool call: name, args, result summary, latency_ms
- Written incrementally after every event — never lost on shutdown

### Synthetic Scenarios
34 scripted scenarios across 8 categories in `evaluation/scenarios/scenarios.json`:
sales_vague, sales_direct, comparison, booking, maintenance_existing, maintenance_non_customer, guardrails_edge_cases, rag_quality

### Dashboard
Streamlit dashboard (`scripts/eval_dashboard.py`) with:
- Global view: KPI cards, score history, verdict distribution, radar chart
- Session view: dimension scores, flagged turns with severity, 3-paragraph plain-English summary

**Run via:** `Evaluate Session.command` on the Desktop

---

## 10. Email Agent

After a successful booking, `src/agent/email_agent.py` fires asynchronously:

1. **Customer email** — booking confirmation with date, time, advisor name, dealership address
2. **Advisor briefing email** — full customer profile extracted from the conversation transcript:
   - Detected budget range and price sensitivity
   - Family situation and use case
   - Financing preference signals
   - Technical knowledge level
   - Urgency and decision timeline
   - Key objections raised during the call

Both emails sent via SendGrid. Customer email address collected via on-screen modal triggered by `request_email_input()`.

---

## 11. Project Structure

```
AGI/
├── OTTO_PROJECT.md                ← This file
├── docker-compose.yml
├── requirements.txt
├── .env
│
├── data/
│   ├── raw/                       ← Raw scraped HTML (committed)
│   └── rag/                       ← Parsed PDFs, photos, embeddings (gitignored)
│       ├── parsed/                ← JSON extracted from PDFs
│       ├── photos/                ← Extracted catalog images
│       └── session_traces/        ← Per-session evaluation JSON (gitignored)
│
├── evaluation/
│   ├── scenarios/
│   │   └── scenarios.json         ← 34 synthetic test scenarios
│   └── results/                   ← Judge output JSONs (gitignored)
│
├── scripts/
│   ├── 01_scrape_ev_specs.py
│   ├── 02_clean_normalize.py
│   ├── 03_generate_synthetic.py
│   ├── 07_parse_documents.py      ← PDF → JSON
│   ├── 08_render_pages.py         ← PDF → PNG
│   ├── 12_index_text_embeddings.py ← Text → pgvector
│   ├── 15_batch_pipeline.py       ← Full RAG pipeline orchestrator
│   ├── 16_extract_catalog_photos.py
│   ├── 18_caption_photos.py       ← GPT-4o Vision → captions → pgvector
│   ├── judge_session.py           ← LLM-as-a-Judge evaluation script
│   └── eval_dashboard.py          ← Streamlit evaluation dashboard
│
├── src/
│   ├── agent/
│   │   ├── prompts.py             ← OttO system prompt
│   │   ├── session.py             ← RealtimeSession WebSocket bridge
│   │   ├── session_trace.py       ← Per-session structured trace recorder
│   │   ├── tools_registry.py      ← Tool schemas + implementations map
│   │   └── email_agent.py         ← Post-booking email + advisor briefing
│   │
│   ├── tools/
│   │   ├── sales.py               ← search_vehicles, get_vehicle_details
│   │   ├── knowledge_base.py      ← search_knowledge_base (RAG)
│   │   ├── photo_search.py        ← search_catalog_photos
│   │   ├── booking.py             ← list_available_slots, book_slot, request_email_input
│   │   └── maintenance.py         ← get_customer_service_history, get_next_service_recommendation
│   │
│   └── api/
│       ├── main.py                ← FastAPI app, WebSocket endpoint
│       └── data_routes.py         ← Catalog photo serving endpoint
│
└── frontend/
    └── otto.html                  ← Single-page UI with WebAudio + WebSocket
```

---

## 12. Environment Variables

```
# AI
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Database
DB_HOST=localhost
DB_PORT=5434
DB_NAME=otto
DB_USER=otto
DB_PASSWORD=otto

# Email
SENDGRID_API_KEY=
SENDGRID_FROM_EMAIL=
```

---

## 13. VAD Configuration

Voice Activity Detection runs server-side via OpenAI's `server_vad` mode:

| Parameter | Value | Reason |
|---|---|---|
| `threshold` | 0.8 | High — reduces false triggers from background noise |
| `silence_duration_ms` | 800 | Prevents cutoffs when customer pauses mid-sentence |
| `prefix_padding_ms` | 300 | Captures word starts before VAD fires |

---

## 14. Phase Status

### Phase 1 — Data Foundation ✅
- PostgreSQL schema + Docker environment
- Scraper for 22 EV models (evspecs.org)
- Data cleaning and normalization
- Synthetic dealership data generation (inventory, customers, appointments, service history, parts)
- Database load and validation

### Phase 2 — Voice Agent ✅
- Single-agent architecture (collapsed from 5-agent LangGraph design)
- 12 tool functions across 5 domains
- OpenAI Realtime API WebSocket bridge
- System prompt with guardrails, domain playbooks, RAG rules
- Custom HTML frontend with WebAudio API

### Phase 3 — RAG Pipeline ✅
- 22 PDF catalogs parsed and embedded (pgvector text search)
- 890 catalog photos extracted, captioned with GPT-4o Vision, embedded (pgvector photo search)
- RAG quality filters: similarity threshold 0.35, garbled OCR page detection

### Phase 4 — Evaluation System ✅
- Session trace recorder (incremental, crash-safe)
- LLM-as-a-Judge with 7 scoring dimensions and plain-English session summary
- 34 synthetic scenarios
- Streamlit evaluation dashboard
- Desktop launchers: `OttO.command`, `Evaluate Session.command`

### Phase 5 — Resilience & Post-Call ✅
- Email agent: customer confirmation + advisor profiling briefing
- WebSocket resilience: immediate cleanup on disconnect
- Session trace bug fixed (wrong key causing judge to always see 0 RAG pages)
- RAG fallback rule hardened in system prompt

### Phase 6 — Report ⏳
- Updated technical report (in progress post-demo)
