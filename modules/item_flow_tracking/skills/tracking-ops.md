---
name: tracking-ops
description: Move parts through steps and finish orders — lot move, lot count, lot redo, lot deliver, order deliver, order cancel.
---

# item_flow_tracking · tracking-ops

Mutating operations on orders and parts. All are subcommands of
`scripts/flow.py`; use absolute paths (`<modules>` = the modules root from the
"Active Modules" prompt section). Every change is recorded in the `lot_events`
ledger.

## Move a part (step is inferred from the resource)

Moving into a machine/area sets the step automatically (washer→giặt, dryer→sấy,
fold→gấp, count→kiểm đếm); moving into a bin just relocates it and keeps the
step. Fails if the target is busy unless `--force`.

Pick the part to move by its lot id (`--lot`) **or** by the resource it
currently occupies (`--from`) — exactly one is required. `--from` resolves the
single active lot in that resource, so you can move by the physical bin the
operator names without looking up the lot id first:

```
python <modules>/item_flow_tracking/scripts/flow.py lot move --from bin-1 --to washer-3
python <modules>/item_flow_tracking/scripts/flow.py lot move --lot DH-20260626-001-P1 --to bin-5
```

`--from` errors if the resource holds no active lot, or (only possible after a
`--force` double-occupancy) if it holds more than one — then use `--lot`.

## Count a part (sums into the order total)

```
python <modules>/item_flow_tracking/scripts/flow.py lot count --lot DH-20260626-001-P1 --items 24
```

## Redo ("làm lại") — send a part back

Defaults back to `giat`; pass `--to` for another step:

```
python <modules>/item_flow_tracking/scripts/flow.py lot redo --lot DH-20260626-001-P1 --notes "còn vết bẩn"
python <modules>/item_flow_tracking/scripts/flow.py lot redo --lot DH-20260626-001-P1 --to say
```

## Deliver / cancel

`order deliver` requires every part to be counted; `lot deliver` finishes one
part (and completes the order when it's the last):

```
python <modules>/item_flow_tracking/scripts/flow.py lot deliver --lot DH-20260626-001-P1
python <modules>/item_flow_tracking/scripts/flow.py order deliver --order DH-20260626-001
python <modules>/item_flow_tracking/scripts/flow.py order cancel --order DH-20260626-001 --reason "khách hủy"
```
