# OttO — AI Voice Agent Framework for EV Dealerships
> Capstone Project | Multi-Agent Autonomous System

---

## 1. Project Vision

**OttO** is an autonomous multi-agent framework that handles inbound phone calls for a European
electric-vehicle-only dealership. When a customer calls, OttO's voice AI picks up instantly,
understands the caller's intent, and routes them to the right specialist agent — all without
human intervention.

The system targets a real, underserved pain point: car dealerships lose customers daily because
phones go unanswered, callers are bounced between departments, and after-hours calls are missed
entirely. OttO solves this with always-on, voice-native AI.

### The Dealership — "EV Land"
A fictional multi-brand EV-only dealership inspired by real European multi-brand dealers (e.g.
SUMA Auto). EV Land sells exclusively battery-electric vehicles from 6 carefully selected
brands covering every price segment of the European EV market.

**Why EV-only?**
- Focused knowledge base — agents never handle ICE/hybrid questions
- Reflects the fastest-growing segment of the European auto market (20% BEV market share in 2025)
- Clean, defensible scope for a capstone project

**Demo scenario (for oral presentation):**
A customer calls EV Land. OttO's receptionist answers in natural speech within 800ms, identifies
the caller wants to book a test drive for a Volkswagen ID.4. The receptionist hands off to the
Booking Agent, which checks real-time availability in the database, confirms a slot, and sends a
confirmation — all within one phone call, zero human involvement.

---

## 2. Vehicle Catalog

### 6 Brands — 24 Models — 100% Battery Electric

All brands selected based on 2025 European BEV market data. No Tesla (direct-sales only model,
not compatible with dealership format). No ICE or PHEV models.

| Brand | Segment | Models | Price range |
|---|---|---|---|
| **Renault** | Budget / Urban | R5 E-Tech, R4 E-Tech, Mégane E-Tech, Scenic E-Tech | €25k–€47k |
| **Volkswagen** | Volume Mainstream | ID.3, ID.4, ID.7, ID. Buzz | €35k–€65k |
| **Kia** | Korean Value-Premium | EV3, EV6, EV9 | €36k–€75k |
| **Hyundai** | Korean Mid-Premium | KONA Electric, IONIQ 5, IONIQ 6, IONIQ 9 | €35k–€78k |
| **Audi** | Premium German | Q4 e-tron, Q6 e-tron, A6 e-tron | €47k–€90k |
| **Mercedes-Benz** | Luxury Flagship | EQA, EQB, EQS, CLA BEV | €50k–€110k |

### Body Type Coverage (diversity validation)
- **Hatchback**: Renault 5, Renault 4, Mégane E-Tech, VW ID.3
- **SUV / Crossover**: Scenic E-Tech, ID.4, EV3, EV6, KONA Electric, IONIQ 5, Q4 e-tron, Q6 e-tron, EQA, EQB
- **Large 7-seat SUV**: EV9, IONIQ 9, EQB
- **Sedan / Executive**: VW ID.7, IONIQ 6, A6 e-tron, EQS, CLA BEV
- **MPV / Van**: ID. Buzz

> **Market justification**: SUVs account for 59% of European new car sales in 2025 (Dataforce /
> Automotive News Europe). The SUV-heavy catalog directly mirrors the real European market — this
> is a feature, not a limitation.

---

## 3. Architecture Overview

```
Inbound Call (browser WebRTC via LiveKit)
        │
        ▼
┌─────────────────────────────────┐
│      LiveKit Session Layer      │  ← WebRTC, audio codec, session lifecycle
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│       Receptionist Agent        │  ← OpenAI Realtime API (GPT-4o voice-to-voice)
│   (Voice Interface + Router)    │    Greets caller, detects intent, triggers handoff
└──────────────┬──────────────────┘
               │  LangGraph state handoff (typed ConversationState)
               ▼
┌──────────────────────────────────────────────────────────┐
│                   LangGraph Orchestrator                  │
│         Graph-based routing with conditional edges        │
└──────┬──────────────┬──────────────┬──────────────┬──────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
  Sales Agent   Maintenance    Parts Agent    Booking Agent
  (inventory,    Agent         (catalog,      (appointments,
  specs,        (service,      compatibility, test drives,
  comparisons)  warranty,      pricing)       calendar)
                repairs)
```

### Agent Responsibilities

| Agent | Role | Key Tools |
|---|---|---|
| **Receptionist** | Answers call, greets, detects intent, routes to specialist | OpenAI Realtime API, LiveKit, intent classifier |
| **Sales Agent** | EV model info, pricing, availability, comparisons across 24 models | `inventory_search`, `ev_specs_lookup`, `compare_models` |
| **Maintenance Agent** | Service inquiries, warranty questions, repair status | `service_history_lookup`, `warranty_check`, `technician_availability` |
| **Parts Agent** | Parts availability, EV-specific compatibility, pricing, lead times | `parts_catalog_search`, `compatibility_check`, `stock_level` |
| **Booking Agent** | Schedule test drives and service appointments, send confirmations | `slot_availability`, `create_booking`, `send_confirmation` |

### Why 5 agents and not fewer?
Each agent maps to a distinct dealership department with its own knowledge base and tool set:
- **Receptionist** must stay lightweight — voice latency is critical, it cannot carry full domain logic
- **Sales vs Maintenance** — completely different knowledge graphs (product specs vs service procedures)
- **Parts vs Maintenance** — Parts handles catalog/stock queries; Maintenance handles labor/diagnostics
- Merging any two specialist agents creates conflicting retrieval contexts and degrades accuracy

### LangGraph State Schema (shared across all agents)
```python
class ConversationState(TypedDict):
    call_id: str
    caller_name: Optional[str]
    caller_phone: Optional[str]
    intent: Optional[str]            # sales | maintenance | parts | booking | unknown
    current_agent: str
    messages: List[BaseMessage]
    vehicle_context: Optional[dict]  # model/brand being discussed
    booking_context: Optional[dict]  # appointment details in progress
    resolved: bool
    escalate_to_human: bool
```

---

## 4. Tech Stack

| Layer | Technology | Justification |
|---|---|---|
| Voice I/O | OpenAI Realtime API (GPT-4o) | True voice-to-voice, sub-800ms latency, no STT/TTS pipeline overhead |
| Session / WebRTC | LiveKit Agents (Python SDK) | Industry standard for real-time audio, purpose-built for AI voice agents |
| Agent Orchestration | LangGraph | Graph-based state machine, typed state handoff, conditional routing edges |
| LLM (specialist agents) | GPT-4o via OpenAI API | Function calling, consistent with voice layer |
| Backend API | FastAPI (Python) | Async-native, lightweight, easy Docker integration |
| Database | PostgreSQL + pgvector | Relational inventory/bookings + vector similarity for semantic EV search |
| Frontend | Next.js + Tailwind CSS | Clean dealership UI, "Call Now" WebRTC button as demo centrepiece |
| Data pipeline | Python (BeautifulSoup4, pandas, SQLAlchemy) | Scraping, cleaning, transformation, DB loading |
| Containerization | Docker + docker-compose | One-command reproducible deployment (rubric requirement) |

---

## 5. Data Strategy

### 5.1 Two-Layer Approach

#### Layer 1 — Web Scraping: evspecs.org (EV Technical Specs)

**Primary source:** `https://www.evspecs.org`
**Fallback source:** `https://www.ultimatespecs.com` (used if any model is missing from evspecs.org)

**Why evspecs.org over official manufacturer sites:**
- EV-dedicated site — every model is electric, no filtering needed across irrelevant ICE variants
- Single consistent HTML structure across all 6 brands — one scraper handles all 24 models
- Smaller, less aggressively protected than large aggregators — lower risk of IP blocking with polite scraping
- Official manufacturer sites (renault.com, mercedes.com) use JavaScript-heavy React frontends
  requiring Selenium/Playwright, with Cloudflare bot protection and inconsistent multilingual layouts
- Data originates from manufacturer specs — academically citable as such

**Why ultimatespecs.com as fallback:**
- Broader coverage — any model missing from evspecs.org will be present here
- Same consistent structure, same one-scraper approach
- Both scrapers share identical field mapping logic — switching is trivial

**Fields scraped per model:**
```
- brand, model, year, variant/trim
- battery_capacity_kwh (usable)
- range_wltp_km
- ac_charging_kw (max onboard charger)
- dc_charging_kw (max fast charge)
- acceleration_0_100_s
- top_speed_kmh
- cargo_volume_l
- dimensions (length x width x height mm)
- weight_kg
- drivetrain (FWD / RWD / AWD)
- body_type
- seats
- base_price_eur (European market)
```

**Scraping script:** `scripts/01_scrape_ev_specs.py`
- Uses `requests` + `BeautifulSoup4`
- Respects crawl-delay: 1 request per 2 seconds
- Saves raw HTML to `data/raw/` before parsing (never re-scrapes if raw exists)
- Outputs `data/interim/ev_specs_raw.csv`

#### Layer 2 — Synthetic Generation: Dealership-Specific Data

Real dealership CRM data is proprietary and unavailable. This layer is generated with LLM
assistance using realistic distributions, injected noise, and domain-specific business logic.

**Generated datasets:**

```
inventory.csv
├── vehicle_id, brand, model, variant, color
├── stock_count           (0–15, with 8% out-of-stock probability)
├── is_demo_car           (bool)
├── dealer_price_eur      (MSRP + 4–8% dealer margin, randomised per unit)
└── available_from_date

service_history.csv
├── record_id, customer_id, vehicle_id
├── service_type          (annual_service / battery_check / tire_rotation / repair / recall)
├── date                  (past 18 months, realistic frequency distribution)
├── technician_id, duration_hours
├── cost_eur              (5% missing — invoice not yet processed)
└── status                (completed / pending / cancelled)

appointments.csv
├── slot_id, slot_datetime  (next 45 days, business hours Mon–Sat, no lunch 12:00–13:30)
├── duration_minutes        (30 test drive / 60–120 service)
├── appointment_type        (test_drive / maintenance / parts_fitting)
├── status                  (available / booked / blocked)
├── customer_name, customer_phone  (if booked)
└── vehicle_id              (if applicable)

parts_catalog.csv
├── part_id, part_name, part_category
├── compatible_brands[]    (array — some parts cross-brand)
├── compatible_models[]
├── price_eur, stock_count
├── lead_time_days         (0 = in stock | 3 / 7 / 14 / 21 | null = supplier unknown)
└── is_ev_specific         (bool — battery modules, charging cables, heat pumps, etc.)

customers.csv  (fully anonymised — no real personal data)
├── customer_id, first_name, last_name
├── phone, email
├── owned_vehicle_id       (FK, nullable)
└── preferred_language     (fr / en / de / es)
```

**Noise injection — makes the pipeline academically interesting:**
- 8% of inventory records: `stock_count = 0` (sold out)
- 5% of service records: `cost_eur = null` (invoice pending)
- 12% of appointment slots: `status = blocked` (technician unavailable)
- 3% of parts: `lead_time_days = null` (supplier unknown)
- No weekend appointments; lunch gap 12:00–13:30 blocked

**Generation script:** `scripts/03_generate_synthetic.py`
- Structured LLM prompts with JSON output mode
- Pydantic schema validation before writing to CSV
- Generation parameters logged for reproducibility

### 5.2 Data Pipeline

```
scripts/
├── 01_scrape_ev_specs.py       ← BeautifulSoup scraper → data/raw/ + data/interim/
├── 02_clean_normalize.py       ← Standardise units, handle nulls, deduplicate variants
├── 03_generate_synthetic.py    ← LLM-assisted synthetic data → data/synthetic/
├── 04_load_database.py         ← PostgreSQL ingestion via SQLAlchemy
└── 05_validate_data.py         ← Stats, distributions, completeness report

data/
├── raw/          ← Raw HTML pages saved from scraper (committed to git)
├── interim/      ← Parsed CSVs, pre-cleaning
├── processed/    ← Final cleaned tables ready for DB load
└── synthetic/    ← Generated dealership data
```

### 5.3 Cleaning Steps (documented for technical report)

| Issue | Field | Treatment |
|---|---|---|
| Missing WLTP range | `range_wltp_km` | Impute from `battery_kwh` via linear regression |
| Inconsistent brand names | `brand` | Normalise to 6-value controlled vocabulary |
| Price in non-EUR markets | `base_price_eur` | Filter to European market entries only |
| Multiple trims per model | `variant` | Keep base + top trim only (2 rows per model max) |
| Missing DC charging speed | `dc_charging_kw` | Fill with brand average for model year |
| Duplicate model entries | all | Deduplicate on (brand, model, year, variant) |

---

## 6. Database Schema

```sql
CREATE TABLE vehicles (
    id               SERIAL PRIMARY KEY,
    brand            VARCHAR(50)  NOT NULL,
    model            VARCHAR(100) NOT NULL,
    year             INTEGER,
    variant          VARCHAR(100),
    body_type        VARCHAR(50),
    seats            INTEGER,
    battery_kwh      DECIMAL(5,1),
    range_wltp_km    INTEGER,
    ac_charging_kw   DECIMAL(4,1),
    dc_charging_kw   INTEGER,
    acceleration_s   DECIMAL(4,1),
    top_speed_kmh    INTEGER,
    cargo_l          INTEGER,
    weight_kg        INTEGER,
    drivetrain       VARCHAR(10),
    base_price_eur   INTEGER,
    specs_embedding  VECTOR(1536)   -- pgvector for semantic search
);

CREATE TABLE inventory (
    id               SERIAL PRIMARY KEY,
    vehicle_id       INTEGER REFERENCES vehicles(id),
    color            VARCHAR(50),
    stock_count      INTEGER DEFAULT 0,
    is_demo_car      BOOLEAN DEFAULT FALSE,
    dealer_price_eur INTEGER,
    available_from   DATE
);

CREATE TABLE appointments (
    id               SERIAL PRIMARY KEY,
    slot_datetime    TIMESTAMP NOT NULL,
    duration_min     INTEGER,
    type             VARCHAR(30),   -- test_drive | maintenance | parts_fitting
    status           VARCHAR(20) DEFAULT 'available',
    customer_name    VARCHAR(100),
    customer_phone   VARCHAR(20),
    vehicle_id       INTEGER REFERENCES vehicles(id)
);

CREATE TABLE service_history (
    id               SERIAL PRIMARY KEY,
    customer_id      INTEGER REFERENCES customers(id),
    vehicle_id       INTEGER REFERENCES vehicles(id),
    service_type     VARCHAR(50),
    service_date     DATE,
    cost_eur         DECIMAL(8,2),
    notes            TEXT,
    status           VARCHAR(20)
);

CREATE TABLE parts (
    id               SERIAL PRIMARY KEY,
    name             VARCHAR(100),
    category         VARCHAR(50),
    compatible_brands  VARCHAR[],
    compatible_models  VARCHAR[],
    price_eur        DECIMAL(8,2),
    stock_count      INTEGER,
    lead_time_days   INTEGER,
    is_ev_specific   BOOLEAN DEFAULT TRUE
);

CREATE TABLE customers (
    id               SERIAL PRIMARY KEY,
    first_name       VARCHAR(50),
    last_name        VARCHAR(50),
    phone            VARCHAR(20),
    email            VARCHAR(100),
    owned_vehicle_id INTEGER REFERENCES vehicles(id),
    preferred_language VARCHAR(5) DEFAULT 'fr'
);
```

---

## 7. Project Structure

```
otto/
├── README.md                      ← Setup, install, run instructions
├── OTTO_PROJECT.md                ← This file (master project spec for Claude Code)
├── docker-compose.yml
├── requirements.txt
├── .env.example
│
├── data/
│   ├── raw/                       ← Raw scraped HTML (committed for reproducibility)
│   ├── interim/                   ← Parsed, pre-cleaning CSVs
│   ├── processed/                 ← Final clean tables
│   └── synthetic/                 ← Generated dealership data
│
├── scripts/                       ← Standalone runnable pipeline scripts
│   ├── 01_scrape_ev_specs.py
│   ├── 02_clean_normalize.py
│   ├── 03_generate_synthetic.py
│   ├── 04_load_database.py
│   └── 05_validate_data.py
│
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── receptionist.py        ← OpenAI Realtime API + LiveKit session handler
│   │   ├── sales.py
│   │   ├── maintenance.py
│   │   ├── parts.py
│   │   └── booking.py
│   │
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── graph.py               ← LangGraph StateGraph definition
│   │   ├── nodes.py               ← Node functions (one per agent)
│   │   ├── edges.py               ← Conditional routing logic
│   │   └── state.py               ← ConversationState TypedDict
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── inventory.py           ← search_inventory(), get_vehicle_specs()
│   │   ├── booking.py             ← get_available_slots(), create_booking()
│   │   ├── service.py             ← lookup_service_history(), check_warranty()
│   │   └── parts.py               ← search_parts(), check_compatibility()
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py              ← SQLAlchemy ORM models
│   │   ├── connection.py          ← DB session + connection pool
│   │   └── queries.py             ← Typed query functions
│   │
│   └── api/
│       ├── __init__.py
│       ├── main.py                ← FastAPI app entrypoint
│       └── routes/
│           ├── call.py            ← POST /call/start — initiates LiveKit session
│           ├── inventory.py       ← GET /vehicles — frontend inventory feed
│           └── health.py          ← GET /health — Docker healthcheck
│
├── frontend/                      ← Next.js + Tailwind CSS (3 pages max)
│   ├── pages/
│   │   ├── index.tsx              ← Homepage: brand filter + vehicle grid
│   │   ├── vehicles/[id].tsx      ← Vehicle detail page with specs
│   │   └── call.tsx               ← Demo page: "Call EV Land" WebRTC button
│   ├── components/
│   │   ├── VehicleCard.tsx
│   │   ├── BrandFilter.tsx
│   │   ├── CallButton.tsx         ← Triggers LiveKit WebRTC session
│   │   └── Navbar.tsx
│   └── package.json
│
├── notebooks/                     ← EDA only — NOT production code
│   ├── 01_eda_ev_specs.ipynb
│   ├── 02_data_quality.ipynb
│   └── 03_agent_evaluation.ipynb
│
├── evaluation/
│   ├── scenarios/
│   │   ├── sales_scenarios.json        ← 15 scripted sales call scripts
│   │   ├── maintenance_scenarios.json  ← 12 scripted maintenance calls
│   │   ├── parts_scenarios.json        ← 10 scripted parts calls
│   │   └── booking_scenarios.json      ← 13 scripted booking calls
│   └── run_evaluation.py              ← Automated evaluation runner
│
└── tests/
    ├── test_agents.py
    ├── test_tools.py
    ├── test_api.py
    └── test_scraper.py
```

---

## 8. MLOps Pipeline (Rubric Requirement)

### Problem Definition
**Goal:** Autonomous inbound call handling for a multi-brand EV dealership
**Success metric:** Call resolution rate without human escalation
**Baseline:** Single-agent GPT-4o (all tools, no routing) vs. full 5-agent OttO system

### Data Collection
```bash
python scripts/01_scrape_ev_specs.py    # Scrapes 24 models from ultimatespecs.com
python scripts/03_generate_synthetic.py # Generates dealership operational data
```

### Cleaning
```bash
python scripts/02_clean_normalize.py
```
Key transformations: WLTP range imputation, brand name normalisation, price filtering,
variant deduplication, DC charging null fill.

### Modeling
OttO's "model" is the multi-agent system. Two evaluation dimensions:

**1. Intent Classification Accuracy**
- Input: 50 synthetic call transcripts (labelled ground truth)
- Metric: % correctly routed to the right specialist agent
- Baseline: keyword-matching router (no LLM)

**2. Task Completion Rate**
- Input: 50 scripted call scenarios across all 4 specialist domains
- Metric: % of calls where the agent successfully completes the requested action
- Baseline: single GPT-4o agent with all tools (no routing)

### Evaluation
```bash
python evaluation/run_evaluation.py --scenarios all --output results/eval_report.json
```
Metrics logged per scenario: `routed_correctly`, `task_completed`, `turns_to_resolution`,
`tool_calls_made`, `latency_first_response_ms`, `error_type`.

### Deployment
```bash
docker-compose up   # Starts: PostgreSQL, FastAPI, Next.js, LiveKit
```

---

## 9. Implementation Phases

### Phase 1 — Data Foundation (Week 1–2)
- [ ] Set up PostgreSQL schema + Docker environment
- [ ] Build and run `01_scrape_ev_specs.py` for all 24 models
- [ ] Run `02_clean_normalize.py` — document every cleaning decision
- [ ] Run `03_generate_synthetic.py` — all 5 synthetic datasets
- [ ] Run `04_load_database.py` — verify all tables populated correctly
- [ ] EDA notebook: distributions, missing values, bias check
- [ ] **Gate:** can we query "Audi Q4 e-tron range"? Does inventory show stock levels?

### Phase 2 — Agent Core in Text Mode (Week 3–4)
- [ ] LangGraph state machine: `graph.py`, `state.py`, `edges.py`
- [ ] Implement all 4 tool modules (`inventory`, `booking`, `service`, `parts`)
- [ ] Build all 4 specialist agents — text mode only, no voice yet
- [ ] Build Receptionist intent classifier — text mode
- [ ] Unit tests for every tool function
- [ ] Run 50-scenario evaluation — establish baseline metrics
- [ ] **Gate:** full text conversation resolves correctly end-to-end

### Phase 3 — Voice Integration (Week 5)
- [ ] LiveKit session setup + Python SDK integration
- [ ] OpenAI Realtime API integration in Receptionist agent
- [ ] End-to-end: browser → LiveKit → Receptionist → LangGraph → Specialist
- [ ] Latency profiling: measure time-to-first-voice-response
- [ ] Optimise for < 800ms target
- [ ] **Gate:** live voice call routes correctly and responds naturally

### Phase 4 — Frontend + Demo Polish (Week 6)
- [ ] Next.js site: homepage + vehicle detail + call demo (3 pages, hard cap)
- [ ] Brand filter + vehicle grid connected to FastAPI `/vehicles`
- [ ] "Call EV Land" button triggers LiveKit WebRTC session
- [ ] Demo scenario scripted, rehearsed, timed (10–15 min presentation)
- [ ] docker-compose tested on a clean machine
- [ ] **Gate:** demo works end-to-end on fresh `docker-compose up`

### Phase 5 — Evaluation + Report (Week 7)
- [ ] Final evaluation run: 50 scenarios, log all metrics
- [ ] Error analysis notebook: where does OttO fail and why?
- [ ] Technical report: all sections complete
- [ ] README finalised (title, description, install, run)
- [ ] Code cleanup: comments, remove debug prints, lint

---

## 10. Key Technical Decisions & Justifications

**OpenAI Realtime API over Whisper + LLM + ElevenLabs pipeline**
A traditional STT → LLM → TTS pipeline compounds latency at each step (typically 1.5–3s total).
The Realtime API processes audio natively, targeting sub-800ms responses. Latency above 1.2s
causes callers to assume the line is dead.

**LiveKit for the session layer**
LiveKit handles WebRTC negotiation, audio codec selection, and session lifecycle with a Python
Agents SDK purpose-built for AI voice. For demo purposes, browser WebRTC eliminates the need
for a real phone number.

**LangGraph over CrewAI or pure LiveKit Agents**
LiveKit Agents has no graph-based state management — it cannot maintain typed shared context
across a handoff. LangGraph gives us typed `ConversationState`, conditional routing edges, and
clean checkpointing. CrewAI is too opinionated and not designed for real-time voice.

**evspecs.org (+ ultimatespecs.com fallback) over official manufacturer websites**
Manufacturer sites use JavaScript-heavy frameworks and bot protection requiring 6 separate
scrapers. evspecs.org is EV-dedicated, consistently structured, and less aggressively protected —
one scraper for all 24 models. ultimatespecs.com serves as fallback for any missing models.

**PostgreSQL + pgvector**
Relational schema handles inventory/booking queries. pgvector enables semantic search
("family SUV under 50k with 500km range") by storing vehicle description embeddings alongside
structured data — one database for both query types.

**Synthetic data for the dealership layer**
Real CRM data is unavailable. Synthetic generation with controlled noise injection (out-of-stock
items, scheduling conflicts, missing costs) produces a dataset more interesting than a clean
public download. The generation process — Pydantic-validated, parameter-logged — is a
defensible pipeline contribution.

---

## 11. Evaluation Rubric Mapping

| Rubric Criterion | OttO Implementation |
|---|---|
| **Problem Framing & Business Value** | Autonomous inbound calls; KPI = resolution rate without human escalation |
| **Data Collection** | evspecs.org scraper (24 models, ultimatespecs.com fallback) + synthetic dealership data (5 datasets) |
| **Data Cleaning** | 6 documented cleaning operations in `02_clean_normalize.py` |
| **EDA Graphs** | Range vs price scatter, battery size distribution, body type breakdown, booking heatmap |
| **Modeling & Experimentation** | Multi-agent routing vs. single-agent baseline on 50 scripted scenarios |
| **Baseline Comparison** | Single GPT-4o agent (all tools, no routing) vs. full OttO system |
| **Error Analysis** | Failure modes: wrong routing, tool failure, timeout, ambiguous intent |
| **Interpretability** | Call transcript logging, routing decision explanations, latency breakdown per hop |
| **Ethics** | Routing bias check (non-native speaker accents), no real customer data, carbon impact note |
| **Reproducibility** | Docker + docker-compose, `requirements.txt`, `.env.example`, README |
| **Code Structure** | `src/` modular layout, notebooks separated, no notebook production code |
| **Demo** | Live WebRTC call from browser — not pre-recorded |

---

## 12. Environment Variables (.env.example)

```
# AI / Voice
OPENAI_API_KEY=

# LiveKit
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=

# Database
DATABASE_URL=postgresql://otto:otto@localhost:5432/otto

# App
ENVIRONMENT=development
LOG_LEVEL=INFO
```

---

## 13. Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| OpenAI Realtime API latency > 800ms | Medium | Test in Phase 3 week 1; fallback to Whisper + TTS if needed |
| evspecs.org blocks scraper | Low | Respect crawl-delay; save raw HTML so scraper runs only once; switch to ultimatespecs.com fallback |
| LiveKit Cloud free tier limits | Low | Monitor session minutes; self-host LiveKit as fallback |
| Synthetic data feels unconvincing | Low | Inject realistic noise; document generation methodology in report |
| Frontend scope creep | Medium | Hard cap: 3 pages, no animations, ship fast |
| Demo fails live | Medium | Rehearse 5x before defense; backup = pre-recorded video |
| LangGraph handoff loses voice context | Medium | Test Phase 2 text-mode handoffs before touching voice layer |
