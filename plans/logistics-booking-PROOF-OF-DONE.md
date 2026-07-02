# Proof of Done — Logistics Booking Module (Phase A)

**Date:** 2026-06-20  **Branch:** `work/goldenpig-session`
**Scope delivered:** Phase A of `plans/logistics-booking-automation.md` — the booking "brain"
as a self-contained Atria module. Phase B (Zalo OA + Email ingestion) is **not** in this build.

## What was built
New module `modules/logistics/` (zero core-code changes), discovered by the registry as
**"Logistics"** (16 files):

- **Data (CSV, seeded with sample rows from the manager's notes):** `dki.csv`, `dki2.csv`
  (fleet → driver, with `ttdk_capacity` + `brand` + `status`), `truck_specs.csv` (CBM by
  class+brand), `customers.csv`, `warehouses.csv`, `traffic_bans.csv`, `bookings.csv` (+ template).
- **Scripts (Python CLIs, JSON stdout):** `fleet.py` (vehicle→driver lookup, loose plate match,
  set-status), `recommend.py` (rank-and-surface trucks: capacity-vs-TTĐK, CBM, 80% upsell flags —
  never hard-filters), `bans.py` (cấm tải/cấm giờ window evaluation + diacritic-insensitive zones),
  `bookings.py` (multi-truck CRUD).
- **UI:** `SKILL.md` (rules as LLM guidance, no tables, points to scripts), `manifest.json`,
  `icon.svg`, `dashboard.html` (fleet + bookings KPIs via AtriaDash bridge).
- **Tests:** `tests/test_logistics_module.py` (13 tests, run scripts against an isolated copy).

## Evidence

**1. Unit/script tests — 13/13 pass**
```
$ uv run pytest tests/test_logistics_module.py -q
13 passed, 8 warnings in 4.78s
```

**2. Critical domain rule — the 4.9T-for-5T / Biên Hoà case (the manager's explicit instruction)**
```
$ bans.py check --zone "Bien Hoa" --time 14:00 --ttdk 4.9   → allowed=true,  must_exit_before=16:00
$ bans.py check --zone "Bien Hoa" --time 07:00 --ttdk 4.9   → allowed=false (>2T 6-8h ban), next 08:00-11:00
$ bans.py check --zone "Noi thanh HCM" --time 14:00 --ttdk 7.8 → allowed=false, next 22:00-06:00, defer suggested
```
`recommend.py match --weight 5 --cbm 18 --zone "Bien Hoa" --time 14:00` →
recommends the TTĐK 4.9T truck (`51C-123.45`, `near_boundary` + `ban_tradeoff_candidate`);
the 15T trucks (TTĐK >5) are correctly flagged `banned_at_time`.

**3. Upsell rule** — `recommend.py match --weight 8 --cbm 28 --new-customer` flags 15T trucks
`upsell_bigger_truck` with `{use_pct_limit: 80, new_customer_only: true, overflow_price_class:"15T"}`.

**4. Diacritic-insensitivity** — `"Bien Hoa"` and `"Biên Hoà"` resolve to the same zone/verdict (test).

**5. Multi-truck booking round-trip** — create → add 2 trucks (loose plate `51D33344`→`51D-333.44`,
driver auto-resolved) → list shows both → set-status → remove; unknown vehicle rejected (exit 1).

**6. Module discovery + SKILL block rendering**
```
$ list_modules('modules') → logistics | manifest: Logistics | files: 16
$ build_skill_block(registry) → "## Active Modules" header injects the absolute root
  "Modules root: D:\[Project]_atriaV2_GoldenPig\modules"; logistics SKILL.md renders in full.
```
The `<modules>` placeholder is **not** machine-substituted — it survives literally and the agent
is told the absolute root in the header (to mentally substitute). This is the **identical convention
the shipped `warehouse` module uses**, so logistics is consistent with the proven-working pattern.

## Live agent-in-the-loop run — PASSED (with a provider-quota caveat)
Brought up the real stack (Dockerized Postgres 16 + backend on :8080) and drove a Vietnamese booking
through the chat API (login → new session → `POST /api/chat/query`), approving only read-only
logistics scripts via a scoped WebSocket approver. NOTE: this fork's `atria` CLI is web-server-only
(no `atria -p`), so this is the required path.

Evidence (backend log + WS approver, session id 2):
- The agent **autonomously chose the logistics module** and invoked **all four scripts** with
  well-formed args parsed from the Vietnamese text, e.g.:
  - `recommend.py match --weight 8 --zone "Biên Hoà" --time 14:00`
  - `bans.py check --zone "Biên Hoà" ...`
  - `fleet.py list --status free` / `--status returning`
  - (tried `bookings.py create …` → correctly **denied** by the scoped approver as mutating)
- The `<modules>` placeholder **resolved to the real absolute path**
  (`D:\[Project]_atriaV2_GoldenPig\modules\logistics\scripts\…`) — confirming concerns about SKILL
  triggering, path resolution, and VN→arg parsing. 19 approvals handled across the run.
- **Caveat:** the agent's *final natural-language summary* was cut off by an OpenAI
  `429 insufficient_quota` (the provider key ran out of quota mid-run) — an environment/billing limit,
  **not** a module defect. Re-run with a funded key to capture the final advice text and to exercise
  `send_editable_table(module="logistics", file="dki.csv")` round-trip.

## Open items needing the owner (carried from the plan)
1. **Review `traffic_bans.csv`** (highest consequence — wrong window = fines/rejected delivery).
   Also review `customers.csv` / `warehouses.csv` ops cells.
2. **Provide the real DKI / DKI 2 `.xlsx`** to reconcile `dki.csv`/`dki2.csv` columns (built on
   sample data meanwhile via the inferred schema).
3. **GPS** is a manual `status` column for now (no live feed).
4. **Booking output** currently `bookings.csv` only.

## Git note
`modules/*` and `*.csv` are gitignored (`.gitignore:195,198`); the existing `warehouse`/`world_cup`
reference modules are in the repo only via force-add. To track `modules/logistics/`, it must be
added the same way (`git add -f modules/logistics`). Not committed — awaiting your go-ahead.

## Test status caveat
`tests/test_modules_prompt.py::test_block_contains_header_and_each_module_sorted` fails, but this is
**pre-existing and unrelated** (it builds its own temp registry and asserts header
`"## Active Module Skills"` while the code emits `"## Active Modules"`). Not caused by this work.
