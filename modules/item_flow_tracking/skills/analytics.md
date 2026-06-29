---
name: analytics
description: Read-only views — order show, customer history by phone, resource status, and the dashboard payload.
---

# item_flow_tracking · analytics

Read-only lookups. All are subcommands of `scripts/flow.py`; use absolute paths
(`<modules>` = the modules root from the "Active Modules" prompt section). Add
`--json` for machine-readable output.

## One order and its parts

```
python <modules>/item_flow_tracking/scripts/flow.py order show --order DH-20260626-001
```

## Customer history (by phone number)

```
python <modules>/item_flow_tracking/scripts/flow.py customer history --phone 0901234567
```

## Resource status

List the pool, optionally filtered; busy resources show their occupant:

```
python <modules>/item_flow_tracking/scripts/flow.py resource list
python <modules>/item_flow_tracking/scripts/flow.py resource list --kind washer --status busy
```

## Reconcile declared vs counted items

Compares what was declared at intake (`--item TYPE:QTY`) with what was counted
via `order count`. Output is grouped by customer and item type: declared qty,
counted qty, owed (declared − counted when counted < declared), and extra
(counted − declared when counted > declared), plus per-customer totals. Omit
`--phone` to reconcile all customers:

```
python <modules>/item_flow_tracking/scripts/flow.py report reconcile --phone 0901234567
python <modules>/item_flow_tracking/scripts/flow.py report reconcile
```

## Full dashboard payload

Returns resources (with occupants), active orders with parts, and parts bucketed
by step (work-in-progress per stage):

```
python <modules>/item_flow_tracking/scripts/flow.py dashboard --json
```
