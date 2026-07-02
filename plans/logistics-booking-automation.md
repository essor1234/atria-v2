# Plan: Logistics Booking Automation for Atria

## Context

The user runs a Vietnamese truck-delivery business (in/around Ho Chi Minh City). Today the owner
manages fleet/driver data in Excel ("DKI" and "DKI 2" sheets) and takes customer bookings by hand
over **Zalo** and **Email**, mentally applying a large body of domain rules (truck capacity vs.
registration limits, CBM per truck type, traffic/time bans by district, per-customer ops, returns
handling). This is slow and error-prone.

Goal: turn that tribal knowledge into an Atria **module** so the agent can take a freeform
booking message and deterministically: look up the vehicle/driver, pick a truck that fits by
capacity + CBM, check whether that truck is legally allowed into the destination at the requested
time, apply the upsell rules, and record the booking — all inside the web chat. Later, ingest
those messages automatically from Zalo/Email.

**Decisions already made (this session):**
- **Phase A first** — build the booking "brain" as a `logistics` module, usable in web chat now.
- **Zalo = Official Account + API** (confirmed) → Phase B Zalo is feasible, but deferred.
- **Email ingestion deferred** — booking text pasted into chat manually for now.
- **Seed data:** the user will provide the real **DKI / DKI 2 .xlsx**; truck-spec/CBM and
  customer/warehouse tables encoded from the manager's notes; scaffold with sample rows until the
  real workbook arrives.

**Why a module (not core changes):** Atria already has everything Phase A needs — `modules/<name>/`
folders with `SKILL.md` auto-injected into the prompt, Python CLI scripts the agent runs via bash,
atomic CSV read/write (`store.py`), Excel→CSV import (`xlsx_convert.py`), and an in-chat editable
grid (`send_editable_table`). Phase A touches **only** the new `modules/logistics/` folder — zero
core changes — and is independently shippable. Reference impl to clone: `modules/warehouse/`.

---

## Phase A — `logistics` domain module (the booking brain)  ← build this

All new files under `D:\[Project]_atriaV2_GoldenPig\modules\logistics\`:

```
modules/logistics/
  SKILL.md                  # when/how to use; rules as guidance to reason over (NO tables — CLAUDE.md)
  manifest.json             # display_name "Logistics", tooltip, icon, dashboard cfg
  icon.svg
  data/
    dki.csv                 # email-booking fleet  (from "DKI" sheet)
    dki2.csv                # message-booking fleet (from "DKI 2" sheet)
    truck_specs.csv         # (weight_class, brand) -> cbm  [+ default TTĐK]
    customers.csv           # per-customer ops profile
    warehouses.csv          # customer -> pickup warehouse(s)
    traffic_bans.csv        # zone + weight threshold + ban/allowed windows
    bookings.csv            # booking line-items (CRUD target)
    *.template.csv          # empty-header reset templates (warehouse pattern)
  scripts/
    fleet.py                # vehicle/driver lookup in DKI/DKI2
    recommend.py            # truck recommender: capacity vs TTĐK vs CBM + 80%/upsell math
    bans.py                 # traffic/time-ban checker
    bookings.py             # booking CRUD (multi-truck)
  dashboard.html            # fleet + today's bookings KPIs (clone warehouse/world_cup dashboard)
  blocks/
    booking_form.html       # optional: push a booking form into chat (clone warehouse push_form)
```

### Data schemas (CSV is the source of truth; per CLAUDE.md, NO matrices in SKILL.md prose)

- **`dki.csv` / `dki2.csv`** (identical columns; two files = email vs. message bookings):
  `vehicle_number, driver_name, phone, national_id, license_id, weight_class, brand, ttdk_capacity, status`
  - `brand` **required** — CBM is keyed by `(weight_class, brand)` (3.5T VINHPHAT=16 vs TERACO=18).
  - `ttdk_capacity` = registration loading capacity (trọng tải đăng kiểm); may be **< rated class**
    (rated 3.5T but TTĐK 1.9T ⇒ max load 1.9T). This column, not `weight_class`, gates load/time bans.
  - `status` = manual GPS proxy: `free | returning | busy` (see GPS note in Open Items).
- **`truck_specs.csv`**: `weight_class, brand, cbm` — encodes the CBM map (2T=10; 3.5T VINHPHAT=16,
  TERACO=18; 5T=20; 8T=30; 15T ISUZU=40; 15T HOWO/CHENLONG/FAW=45).
- **`customers.csv`**: `customer, booking_channel(message|file_plan|email), pack_time_rule,
  progress_update_rule, returns_rule, notes` — free-text cells the LLM reads (FM/ITL photo-of-PGH,
  Pana via TMS, NG-goods flow), not prompt tables.
- **`warehouses.csv`**: `customer, warehouse_name, location_detail, entry_cutoff, notes` — multiple
  rows per customer (Pana → ICD Sóng Thần kho 19&16 / Coyote QL13; Hoà Phát → Cát Lái & Phú Mỹ; etc.).
- **`traffic_bans.csv`**: `zone, weight_threshold_t, ban_windows, allowed_windows, notes` — windows as
  `HH:MM-HH:MM;HH:MM-HH:MM` to model multiple/wrapping windows (HCM inner >2.5T banned 6–22; Biên Hoà
  >5T 6–22 and >2T 6–8,11–13,16–22; KCN Tân Bình allowed 9–16; An Lạc allowed 9–16; ≤2.5T banned 6–9 & 16–20).
- **`bookings.csv`** (line-item, multi-truck): `booking_id, customer, created_at, status,
  destination_zone, requested_weight_t, vehicle_number, driver_name, delivery_time, notes` — one row
  per assigned truck; rows share a `booking_id`.

### Scripts (subcommands; print JSON to stdout; resolve CSVs via `Path(__file__).resolve().parent.parent/"data"` — clone `warehouse/scripts/inventory.py`)

- **`fleet.py`** — `lookup --vehicle <num> [--source dki|dki2]`; `list [--status free|returning] [--json]`;
  `set-status --vehicle <num> --status <s>` (manual GPS proxy).
- **`recommend.py`** — `match --weight <t> --cbm <m3> [--zone <z>] [--new-customer]`: **rank and surface**
  candidates, do **not** hard-filter on capacity. Compute CBM fit from `truck_specs` and tag each truck
  with `ttdk_capacity` vs `weight` (`fits | near_boundary | over`) plus, if `--zone` given, its ban
  status. Surface near-boundary trucks (e.g. a TTĐK **4.9T** truck for a **5T** order) with an
  `over_capacity` / `ban_tradeoff` flag so the LLM sees them — a hard `ttdk >= weight` filter would
  exclude the exact truck the manager says to use for a daytime Biên Hoà 5T order (where TTĐK >5T is
  banned 6–22h). Also apply the **8T→15T 80% upsell numerically** → flags
  `{offer_15t, use_pct_limit:80, overflow_price_class:"15T", new_customer_only:true}`. The LLM picks and
  explains the capacity/ban tradeoff; the script never silently drops a boundary candidate.
- **`bans.py`** — `check --zone <z> --time <HH:MM> --ttdk <t>` → `{allowed, reason, next_allowed_window,
  arrive_before, defer_to_next_day}`. Evaluates per-threshold + wrapping windows from `traffic_bans.csv`.
  **Must normalize Vietnamese diacritics** on `--zone`/warehouse names ("Bien Hoa" == "Biên Hoà").
- **`bookings.py`** — `create --customer --destination --weight` (→ booking_id);
  `add-truck --booking <id> --vehicle <num> --delivery-time <HH:MM>`; `list [--status open] [--json]`;
  `update`; `set-status`; `remove`; `reset`.

### Deterministic (scripts) vs. LLM (SKILL.md prose) — explicit split

- **Deterministic:** DKI/DKI2 vehicle→driver lookup; CBM resolution by `(class, brand)`; capacity-vs-TTĐK
  comparison; the **numeric** 80%/upsell computation; traffic-ban window evaluation + next-legal-window;
  warehouse-mapping lookup; booking CRUD.
- **LLM reasoning:** parsing freeform Vietnamese Zalo/email text into `{customer, weights, destination,
  time}`; the *judgment* half of upsell (new customer? offer the 15T?); arrive-early-and-wait **vs**
  defer-to-next-day (weighing the waiting fee); customer-ops nuances; NG-goods/returns handling. Per
  CLAUDE.md the booking conversation stays LLM-driven — **no hard-coded if/else flow**.

### Reuse vs. build
- **Reuse:** `atria/core/modules/store.py` (`read_dataset`/`write_dataset`) + the `send_editable_table`
  tool (lets the owner edit the fleet as a grid in chat for free); `warehouse/scripts/inventory.py` as
  the CRUD template; `warehouse`/`world_cup` `dashboard.html` + AtriaDash bridge; `warehouse/scripts/
  push_form.py` pattern for `booking_form.html`; `atria/core/modules/xlsx_convert.py::xlsx_to_csvs` to
  seed `dki.csv`/`dki2.csv` from the owner's real workbook.
- **Build:** the four domain scripts + seven CSV schemas + SKILL.md + manifest/icon/dashboard.

### Edge cases
Rated weight vs TTĐK (the 3.5T/1.9T trap — gate ranking on TTĐK, but surface near-boundary trucks like
4.9T-for-5T rather than excluding them — see `recommend.py`); CBM ambiguity when `brand` missing (error,
don't guess); wrapping/multi-threshold ban windows (Biên Hoà, KCN Tân Bình, An Lạc); diacritic
normalization; multi-truck bookings; customers with multiple pickup warehouses (Pana, Hoà Phát,
Daphaco).

**Build order:** scaffold all CSVs with **sample rows now** (from the manager's notes) so scripts +
tests run immediately; **reconcile `dki.csv`/`dki2.csv` columns when the real `.xlsx` arrives** (import
via `xlsx_to_csvs`). The sample-data start means the workbook is not a blocker — it's a later
reconciliation step, not a gate.

---

## Phase B — Ingestion channels (later; not in this build)

Sketch only — depends on core changes. When picked up:
- **B0 (decision):** persist channel identity so repeat customers reuse a session. Either add
  `channel/channel_user_id/thread_id` columns to `conversations` (`schema.sql`; stop squeezing channel
  into `mode[:10]`) **or** a side `channel_sessions` mapping table. Then implement the
  `find_session_by_channel_user` stub (`pg_manager.py:359`, currently `return None`).
- **B1 (wiring):** `MessageRouter` is instantiated **nowhere** today. In the web startup/lifespan,
  construct `MessageRouter(session_manager, agent_executor=<bridge to web agent>)`, `register_adapter`,
  run adapters as background tasks. For `email`/`zalo`, default the workspace + set
  `workspace_confirmed=True` (skip the workspace-pick prompt) and add reset policies in
  `reset_policies.py`.
- **B2 — Email** (lower risk): `atria/core/channels/email.py` — IMAP poll (`imaplib`+`email`, stdlib) →
  `InboundMessage`; SMTP reply with `In-Reply-To`/`References` threading. (Gmail MCP is an alternative.)
- **B3 — Zalo OA** (feasible per user; verify limits): `atria/core/channels/zalo.py` + a
  `POST /api/channels/zalo/webhook` route. **Constraint to confirm before building:** Zalo OA free-form
  replies are limited to the customer-care interaction window after the customer messages first;
  proactive outreach is template-based (ZNS). Acceptable for inbound booking handling; not for arbitrary
  proactive chat.

---

## Open items to confirm with the user before/while building Phase A
1. **Traffic-ban rules review (highest consequence)** — `traffic_bans.csv` is my interpretation of dense
   Vietnamese ban prose; a wrong window means real fines or rejected deliveries. The owner must review the
   encoded windows before the agent acts on them. Same for `customers.csv`/`warehouses.csv` ops cells.
2. **Real DKI workbook** — provide the `.xlsx` to reconcile `dki.csv`/`dki2.csv` columns (build proceeds on
   sample data meanwhile; not a blocker).
3. **GPS** — confirm "truck free/returning" is a **manual `status` column** for now (no live GPS feed exists).
4. **Booking output** — is `bookings.csv` the destination, or should confirmed bookings also write back to
   the owner's Excel / notify a dispatcher? (Assumed: `bookings.csv` only, for now.)

---

## Verification (Phase A)

Per CLAUDE.md, both unit tests **and** real end-to-end are required (OPENAI_API_KEY set).

- **Unit** — `tests/test_logistics_module.py`: subprocess + JSON-parse each script — known vehicle→driver;
  recommender TTĐK gate + CBM + 8T/15T upsell flag; `bans.py` for HCM inner >2.5T at 14:00 (banned, next
  window after 22:00) and Biên Hoà 5T at 07:00; diacritic-insensitive zone match; multi-truck booking
  CRUD round-trip. Run: `uv run pytest tests/test_logistics_module.py -q`.
- **End-to-end** — start the stack (`run-backend.ps1` + `run-frontend.ps1`, Postgres up), open a chat,
  paste a Vietnamese booking (e.g. "2 xe 8T đi Biên Hoà giao 14h"); confirm the agent runs
  `fleet.py`/`recommend.py`/`bans.py` and returns driver assignment + ban advice + upsell note; edit
  `dki.csv` via `send_editable_table` and confirm `.bak` backup + hot reload.
- **Module load** — confirm the new module's SKILL.md appears in the agent's active-modules block and the
  "Logistics" tile shows in the web UI after restart/reload.
