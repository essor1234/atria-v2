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

## Full dashboard payload

Returns resources (with occupants), active orders with parts, and parts bucketed
by step (work-in-progress per stage):

```
python <modules>/item_flow_tracking/scripts/flow.py dashboard --json
```
