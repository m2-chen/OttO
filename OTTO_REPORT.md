# OttO — AI Voice Agent for EV Land
## Project Summary Report | Wednesday Demo Presentation

---

## 1. Project Overview

### What is OttO?

OttO is a real-time AI voice agent built to handle inbound phone calls for a modern electric-vehicle dealership — fully autonomously, 24 hours a day. When a customer calls, OttO picks up instantly, understands what they need, and helps them — whether they want to explore vehicles, book a test drive, check their service history, or find a part. No hold music. No call queue. No after-hours voicemail.

The problem it solves is real and costly: dealerships lose customers every day because phones go unanswered, callers get bounced between departments, and evening or weekend calls are missed entirely. OttO eliminates all of that.

### What is EV Land?

EV Land is the fictional dealership OttO serves — a premium, multi-brand electric-vehicle-only retailer based in Paris. It was designed to reflect the real European EV market in 2025: BEV market share has crossed 20%, SUVs dominate new-car sales at 59%, and multi-brand dealers (like the real-world SUMA Auto) are a growing format.

EV Land sells 100% battery-electric vehicles across seven carefully selected brands, covering every price segment from affordable urban hatchbacks to luxury executive saloons and French performance cars. No ICE. No PHEV. No Tesla (direct-sales model, incompatible with a dealership format). The focused scope is intentional — it creates a clean, defensible knowledge boundary for the AI.

| Brand | Segment | Price Range |
|---|---|---|
| Renault | Budget / Urban | €25k – €47k |
| Volkswagen | Volume Mainstream | €35k – €65k |
| Kia | Korean Value-Premium | €36k – €75k |
| Hyundai | Korean Mid-Premium | €35k – €78k |
| Audi | Premium German | €47k – €90k |
| Mercedes-Benz | Luxury Flagship | €50k – €110k |
| Alpine | French Performance | €38k – €58k |

---

## 2. Phase 1 — Data Foundation

Before a single line of agent code was written, the data layer was built and validated. Phase 1 produced two distinct data layers: scraped EV technical specifications, and a full set of synthetic dealership operational data.

### EV Vehicle Specs Dataset

- **24 models**, **48 variants** (base + top trim per model), across **6 brands**
- Scraped from evspecs.org (primary source), with ultimatespecs.com as fallback
- 14 fields per variant: battery capacity, WLTP range, AC/DC charging speeds, 0-100 acceleration, top speed, cargo volume, dimensions, weight, drivetrain, body type, seats, and European base price
- Cleaned via a dedicated normalization script: WLTP range imputed from battery capacity where missing, brand names normalized to a 6-value controlled vocabulary, duplicate variants deduplicated, non-EUR prices filtered out

Why evspecs.org over official manufacturer sites? Manufacturer websites use JavaScript-heavy React frontends with Cloudflare bot protection, requiring six separate scrapers with Playwright. evspecs.org is EV-dedicated, consistently structured, and less aggressively protected — one scraper covers all 24 models.

### 6 Synthetic Dealership Datasets

Real CRM data is proprietary and unavailable. All dealership-specific data was generated using structured LLM prompts with Pydantic schema validation, with realistic noise deliberately injected to make the dataset academically honest.

| Table | Description | Row Count |
|---|---|---|
| `vehicles` | 48 EV variants with full specs and pgvector embeddings | 48 rows |
| `inventory` | Stock entries per variant (color, dealer price, availability) | ~200 rows |
| `staff` | 8 EV Land employees across Sales, Maintenance, Parts, Management | 8 rows |
| `customers` | CRM profiles with owned vehicle and contact details | 150 rows |
| `appointments` | 45-day booking calendar (Mon–Sat, business hours, no lunch gap) | ~400 rows |
| `service_history` | 18 months of past maintenance records | ~500 rows |
| `parts` | EV-specific parts catalog with compatibility arrays and lead times | ~120 rows |

**Noise injection** — what makes this dataset realistic rather than clean:
- 8% of inventory records: `stock_count = 0` (sold out)
- 5% of service records: `cost_eur = null` (invoice pending)
- 12% of appointment slots: `status = blocked` (technician unavailable)
- 3% of parts: `lead_time_days = null` (supplier lead time unknown)
- No weekend appointments; lunch gap 12:00–13:30 blocked in the calendar

### PostgreSQL + pgvector in Docker

The database runs on PostgreSQL 16 with the pgvector extension, containerized via Docker. pgvector enables semantic similarity search — a customer saying "family SUV under 50k with long range" can be matched against vehicle spec embeddings (1536-dimensional vectors via OpenAI's embedding model), not just exact SQL filters. The Docker setup includes a named volume for data persistence and a health check for orchestrated startup.

---

## 3. Architecture

### How the System Works End to End

```
Customer speaks into browser microphone
         │
         │  PCM16 audio (binary WebSocket frames)
         ▼
┌─────────────────────────────────────────┐
│           FastAPI Backend               │
│         /ws/voice  WebSocket            │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │         RealtimeSession          │   │
│  │  ┌────────────────────────────┐  │   │
│  │  │  _client_to_openai()       │  │   │  ──► PCM16 audio ──►
│  │  │  _openai_to_client()       │  │   │  ◄── PCM16 audio ◄──
│  │  │  _execute_tool()           │  │   │        OpenAI Realtime API
│  │  └────────────────────────────┘  │   │        (gpt-realtime-1.5)
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
         │
         │  Tool call intercepted (function_call_arguments.done)
         ▼
┌─────────────────────────────────────────┐
│           Tool Layer (10 functions)     │
│                                         │
│  sales.py     booking.py               │
│  maintenance.py   parts.py             │
└─────────────────────────────────────────┘
         │
         │  SQLAlchemy queries
         ▼
┌─────────────────────────────────────────┐
│       PostgreSQL 16 + pgvector          │
│       (Docker container: otto_db)       │
└─────────────────────────────────────────┘
```

Audio flows in real time in both directions over a single WebSocket. When OttO decides to call a tool, the `RealtimeSession` class intercepts the `function_call_arguments.done` event, executes the matching Python function against the live database, serializes the result to JSON, and returns it to the OpenAI Realtime API — which then speaks the answer. The round-trip tool execution is invisible to the caller.

### Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Voice AI | OpenAI Realtime API (`gpt-realtime-1.5`) | True voice-to-voice, no STT/TTS pipeline overhead, sub-second latency |
| Backend | FastAPI (Python, async) | Async-native, lightweight, WebSocket support, easy Docker integration |
| Database | PostgreSQL 16 + pgvector | Relational queries for inventory/bookings + vector search for semantic EV matching |
| Containerization | Docker + docker-compose | One-command reproducible deployment |
| Frontend | Static HTML + JavaScript | Lightweight browser client for demo; microphone capture and audio playback |

### Key Architectural Decision: Single Agent Over Multi-Agent

The original project specification called for a multi-agent system — a Receptionist routing to four specialist agents via LangGraph. During implementation, this architecture was deliberately collapsed into a single agent.

**Why the change was the right call:**

The OpenAI Realtime API is a voice-to-voice system with a persistent session context. Routing to a separate specialist agent would require either (a) ending and starting a new Realtime session — which resets all conversation context and introduces a multi-second gap the caller would notice, or (b) injecting conversation state across sessions, adding fragile serialization code for no real benefit.

More importantly, the reason for splitting agents — to prevent retrieval context conflicts — is solved more cleanly by tool design than by agent separation. Each domain has its own isolated tool functions (`sales.py`, `booking.py`, `maintenance.py`, `parts.py`). OttO knows which tool to call based on the conversation context. The system prompt enforces domain boundaries. The result is simpler, faster, more reliable, and just as capable.

A single agent with 10 well-defined tools beats four agents with 2-3 tools each in a voice context. Handoff latency is the enemy of a good phone call.

### Why Voice-First From Day One

Most AI assistant projects start in text and bolt on voice later. OttO was built voice-first, for a deliberate reason: voice changes everything about how the system must behave.

A text chatbot can return bullet points, numbered lists, and tables. A voice agent cannot. The system prompt, the tool output format, the response length constraints — all of these were designed around spoken conversation, not written text. Starting voice-first meant the constraints were built in from the beginning, not retrofitted at the end.

---

## 4. Phase 2 — Voice Agent

### 10 Tool Functions Across 4 Domains

| Domain | Function | What It Does |
|---|---|---|
| **Sales** | `search_vehicles()` | Filter inventory by price, range, brand, body type, seats, drivetrain — returns up to 5 matches with dealer pricing |
| **Sales** | `get_vehicle_details()` | Full technical specs for a specific model, including available colors and total stock |
| **Sales** | `compare_vehicles()` | Side-by-side comparison of 2–3 vehicles by ID (range, battery, charging, price, cargo) |
| **Booking** | `list_available_slots()` | Open appointment slots for the next N days, filtered by type and optionally by vehicle brand/model |
| **Booking** | `book_slot()` | Reserve a slot with row-level locking to prevent double-booking — returns confirmation with staff name |
| **Booking** | `cancel_slot()` | Cancel a booking, verified by customer phone number |
| **Maintenance** | `get_customer_service_history()` | Look up a customer's full service history by phone or name — last 10 records |
| **Maintenance** | `get_next_service_recommendation()` | Rule-based logic: days since last service → urgency rating and recommended next action |
| **Parts** | `find_parts()` | Search parts catalog by keyword, category, or compatible vehicle (brand/model arrays) |
| **Parts** | `check_part_stock()` | Real-time stock count and lead time for a specific part — returns human-readable availability string |

### System Prompt Design and Guardrails

The system prompt (`src/agent/prompts.py`) is the behavioral contract OttO operates within. It covers five areas:

**1. Voice-first constraints.** OttO is explicitly told it is speaking, not writing. Maximum 2 sentences per turn. No enumeration. No spec sheets. Every response ends with a question to keep the conversation moving.

**2. Domain playbooks.** Each domain (Sales, Booking, Maintenance, Parts) has a specific behavioral script. Sales: diagnose before recommending, never pitch before understanding the customer. Booking: ask about availability before showing slots. Maintenance: never speculate, only report what the records say. Parts: answer immediately with name, price, and availability.

**3. Catalogue boundary enforcement.** OttO is instructed never to confirm or deny vehicle availability from memory. Every vehicle query must go through `search_vehicles()` or `get_vehicle_details()`. If the tool returns nothing, the vehicle is not stocked — and OttO suggests a similar alternative it does carry. This eliminates hallucination at the catalogue level.

**4. Out-of-scope guardrails.** A defined list of topics is redirected to a human advisor: specific loan calculations, insurance, legal matters, complaints, technical repairs beyond service records, personal data changes. The redirect pattern is always: acknowledge briefly, explain it needs a human, offer to book a callback — never a dead end.

**5. Financing knowledge.** OttO can explain EV Land's four acquisition options (outright purchase, LOA personal leasing, LLD long-term rental, partnered bank loan) in plain language, but is explicitly prohibited from quoting monthly figures or interest rates. Those always go to an advisor.

### Real-Time WebSocket Bridge

The `RealtimeSession` class (`src/agent/session.py`) is the core of the voice system. It manages three concurrent async tasks:

- `_client_to_openai()`: receives raw PCM16 audio bytes from the browser WebSocket and forwards them to the OpenAI Realtime API as base64-encoded `input_audio_buffer.append` events
- `_openai_to_client()`: receives events from OpenAI and makes real-time routing decisions — audio deltas go straight to the browser as binary frames; transcript events are forwarded as JSON text; `function_call_arguments.done` events trigger tool execution
- `_execute_tool()`: parses tool arguments, calls the matching Python function, serializes the result (handling `Decimal`, `date`, and `datetime` types for JSON compatibility), and returns it to OpenAI via `conversation.item.create`

OttO initiates the greeting automatically on session start — a `response.create` event is sent immediately after `session.update` configures the voice, prompt, and tools. The caller hears OttO speak first, exactly like a human receptionist picking up the phone.

### Model Selection Journey

The model used evolved through testing:

1. **`gpt-4o-realtime-preview`** — initial choice; capable but cost and latency were higher than needed for a dealership use case
2. **`gpt-realtime-1.5`** — the current production model; better suited to tool-calling voice workloads, more predictable response cadence, lower per-minute cost
3. **`gpt-4o-mini-realtime`** — evaluated as a cost-reduction option; response quality on nuanced sales conversations was noticeably degraded

The final choice (`gpt-realtime-1.5`) balances quality and cost for the demo scenario.

### Voice Selection

OttO uses the **shimmer** voice — chosen for its calm, warm, and slightly formal tone. The name fits the brand: assured, not aggressive. The voice impression tests were run against all available Realtime API voices; shimmer consistently conveyed the "trusted advisor" personality defined in the system prompt, without the louder energy of `alloy` or the flatness of `echo`.

### VAD Tuning

Voice Activity Detection (VAD) is configured server-side via OpenAI's `server_vad` mode with deliberate parameter choices:

- `threshold: 0.8` — high sensitivity threshold, making OttO less likely to trigger on background noise (keyboard, ambient room sound)
- `silence_duration_ms: 800` — OttO waits 800ms of silence before considering a turn complete; this prevents premature cutoffs when customers pause mid-sentence to think
- `prefix_padding_ms: 300` — captures the first 300ms before speech is detected, preventing clipped word starts

---

## 5. Current Capabilities

### What OttO Can Do Today

**Sales Domain**
- Search the full catalogue of 48 EV variants by any combination of price ceiling, minimum range, brand, model, body type, seat count, or drivetrain
- Return the top 5 matches ordered by price, with dealer pricing and stock status
- Retrieve full technical specs for any specific model (battery, range, charging speeds, cargo, dimensions, colors in stock)
- Compare 2–3 vehicles side-by-side and articulate the key differences in spoken language

**Booking Domain**
- Check real-time appointment availability for test drives, maintenance, and parts fitting over any time window up to 45 days ahead
- Filter test drive slots by specific vehicle brand and model
- Book a slot with the customer's name and phone number, with row-level database locking to prevent race conditions
- Cancel an existing booking, verified by phone number
- Confirm the appointment in a single spoken sentence: date, time, and advisor name

**Maintenance Domain**
- Look up a customer's full service history by phone number or name (last 10 records, ordered by date)
- Recommend the next service action based on days elapsed since last service, with urgency classification (overdue / due soon / optional)
- Refuse to speculate on mechanical issues — answers are grounded exclusively in what the database records show

**Parts Domain**
- Search the parts catalog by part name keyword, category (battery, brakes, charging, etc.), or compatible vehicle (brand and/or model)
- Filter to in-stock parts only by default, with option to include orderable items
- Return part name, price, stock count, and lead time in a single breath
- Confirm real-time availability with human-readable status: "in stock", "order required — 7 day lead time", or "contact supplier for availability"

**Financing Knowledge**
- Explain all four acquisition options (outright purchase, LOA, LLD, partnered bank loan) in plain spoken language
- Never quote specific monthly figures, interest rates, or eligibility criteria — always defer to an advisor
- Offer to arrange an advisor callback to keep the customer engaged

**Guardrails and Out-of-Scope Handling**
- Firmly redirects: loan calculations, insurance, legal queries, complaints, personal data changes, medical or political topics
- Every redirect follows the same pattern: acknowledge, explain, offer a callback — never a conversational dead end
- Does not repeat the test-drive suggestion more than once per conversation
- Does not ask the same question twice
- Never asks more than one question at a time

**Catalogue Boundary Enforcement**
- Will not confirm or deny any vehicle from memory — every answer is tool-grounded
- If a model is not in the database, OttO acknowledges it warmly and suggests the closest match it does carry
- No hallucinated specs, prices, or stock levels — ever

---

## 6. Key Engineering Decisions

### Single Agent vs Multi-Agent

**Decision:** Collapse five agents (Receptionist + four specialists) into one unified voice agent.

**Reasoning:** The OpenAI Realtime API maintains a persistent, stateful voice session. Routing to a different agent mid-call would require tearing down and re-establishing the session, which resets conversation history and introduces an audible pause. A single agent with 10 well-scoped tool functions delivers equivalent capability with zero handoff latency. Domain separation is achieved through tool design, not agent boundaries.

**Trade-off acknowledged:** A true multi-agent system would be more natural to extend independently. But for a real-time voice context where latency and continuity are non-negotiable, the single-agent approach is the right engineering call.

### Voice-First vs Text-First

**Decision:** Build entirely for voice from day one — no text fallback mode.

**Reasoning:** Voice changes the constraints fundamentally. System prompt length, response sentence count, tool output verbosity, follow-up question design — all of these must be designed for ears, not eyes. Building text-first and converting later would have required a full rewrite of the behavioral layer. Building voice-first meant the constraints were load-bearing from the start.

### Tool-Grounded Answers (No Hallucination)

**Decision:** OttO never answers from model memory on any factual domain question. Every spec, price, availability, service record, and parts query goes through a tool function hitting the live database.

**Reasoning:** Language models have stale training data. They hallucinate prices, specs, and stock status. In a sales context, a hallucinated price or an invented spec is not just embarrassing — it is a liability. The catalogue boundary rule in the system prompt enforces this: if the tool returns nothing, the answer is "we don't carry that model" plus a real alternative from the database.

### VAD Tuning

**Decision:** Set VAD threshold high (0.8) and silence duration long (800ms).

**Reasoning:** The default OpenAI VAD settings are tuned for studio conditions. Real callers have background noise — open-plan offices, car interiors, kitchens. A high threshold reduces false triggers. A longer silence duration prevents OttO from cutting off customers who pause naturally mid-thought. The 300ms prefix padding prevents the first syllable of a response from being clipped.

### Model and Voice Selection

**Decision:** `gpt-realtime-1.5` model, `shimmer` voice.

**Reasoning:** `gpt-realtime-1.5` delivers consistent tool-calling behavior and natural response cadence for a structured dealership use case without the cost overhead of `gpt-4o-realtime`. The `shimmer` voice matches the "calm, warm, trusted advisor" personality defined in the system prompt — validated through direct A/B listening tests against all available voice options.

---

## 7. Live Demo Script

The following five scenarios are recommended for the Wednesday demo. Each is short, flows naturally, and showcases a distinct capability. Run them in order — the arc builds from simple to complex.

---

### Scenario 1 — Warm Greeting and Vehicle Discovery (2 min)

**Goal:** Show OttO's personality and consultative sales approach.

**Script:**
> "Hi, I'm looking for an electric car but I'm not really sure where to start."

OttO will not immediately dump a list of vehicles. It will ask a smart discovery question — usage pattern, charging situation, or family needs. Allow it to ask 2–3 questions, then answer:
> "It's mainly for commuting, about 60km a day. I have charging at home."

OttO will call `search_vehicles()` and present one strong match with a clear rationale. This is the advisory, non-pushy sales mode working as designed.

**What to highlight:** The system listens before it recommends. It picks up on details and uses them.

---

### Scenario 2 — Specific Model Lookup and Stock Check (1.5 min)

**Goal:** Show catalogue boundary enforcement and real-time inventory data.

**Script:**
> "Can you tell me about the Kia EV6?"

OttO will call `get_vehicle_details()` and speak the key specs naturally — range, price, charging speed. Then ask:
> "Do you have it in white?"

OttO will report what the database says about available colors. Then try a model EV Land does not carry:
> "What about the Tesla Model 3?"

OttO will acknowledge warmly that it does not carry Tesla and suggest the closest real alternative — for example the Hyundai IONIQ 6 in the same segment.

**What to highlight:** OttO never invents an answer. If the tool returns nothing, it says so and pivots constructively.

---

### Scenario 3 — Test Drive Booking End-to-End (2 min)

**Goal:** Show the booking flow with real-time slot availability and confirmation.

**Script:**
> "I'd like to book a test drive for the Volkswagen ID.4."

OttO will ask about availability preference first ("any days or times that work better for you?"). Answer:
> "I'm free Thursday or Friday morning."

OttO will call `list_available_slots()` filtered to test drives and present two options matching the preference. Choose one. OttO will ask for name and phone number, call `book_slot()` with row-level locking, and confirm in a single spoken sentence: date, time, and advisor name.

**What to highlight:** The entire booking — slot query, reservation, confirmation — happens in the same conversation, in real time, against the live database.

---

### Scenario 4 — Service History and Maintenance Recommendation (1.5 min)

**Goal:** Show the maintenance domain and how OttO handles existing customers.

**Script:**
> "Hi, I wanted to check when my last service was. My number is 06 12 34 56 78."

OttO will call `get_customer_service_history()` and summarise the most recent record in one sentence. Then:
> "Is there anything I should be getting done soon?"

OttO will call `get_next_service_recommendation()` and return the urgency-classified recommendation — for example: "Your last annual service was 14 months ago, so you're overdue — want me to book that in?"

**What to highlight:** OttO identifies the customer from a phone number, reads live records, and gives a concrete, actionable recommendation without speculating.

---

### Scenario 5 — Out-of-Scope Guardrail (1 min)

**Goal:** Show that OttO handles edge cases gracefully without breaking.

**Script:**
> "Can you calculate what my monthly payments would be if I financed an IONIQ 5 over 48 months?"

OttO will explain the financing options briefly (LOA, LLD, bank loan) and then clearly decline to quote specific figures — redirecting to an advisor and offering to book a callback. It does not say "I don't know." It acknowledges, explains, and keeps the customer engaged.

**What to highlight:** Guardrails are soft, not hard stops. The customer is never left with a dead end.

---

## 8. What's Next — Roadmap

The current system is a complete, working voice agent. The roadmap extends it in four directions:

**Email Confirmation Agent**
After a booking is made, trigger an async confirmation email to the customer with appointment details, address, and a calendar invite attachment. This adds a tangible post-call artifact and closes the loop on the customer experience.

**Customer Recognition**
At call start, look up the caller's phone number against the `customers` table. If a match is found, OttO greets them by name and has their owned vehicle and service history loaded as context before the first word is spoken. Transforms a generic call into a personalized experience.

**Post-Call CRM Logging**
At session end, write a structured summary to a `call_log` table: caller identity (if recognized), intent, tools called, outcome (resolved / escalated / booked), and transcript. Gives the dealership team visibility into every call without listening to recordings.

**LiveKit Integration**
Replace the direct browser WebSocket with a LiveKit session layer. LiveKit handles WebRTC negotiation, audio codec selection, and session lifecycle with a Python Agents SDK built for AI voice. More critically, it enables real phone number integration — calls from any phone, not just a browser tab. This is the step that makes OttO a real telephony product.

**Dealership Website (Next.js)**
A three-page frontend: homepage with brand filter and vehicle grid, vehicle detail page with full specs, and a demo page with a "Call EV Land" button that triggers the WebRTC session. The vehicle data is served directly from the FastAPI backend. This makes the demo self-contained and presentable to an end customer.

---

*Report generated March 2026 — OttO v0.1.0*
