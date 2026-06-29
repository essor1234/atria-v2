---
name: stock-ops
description: Create/update/remove items and move stock — add, update, remove, receive, ship, adjust, move, set-reorder.
---

# warehouse · stock-ops

Mutating operations on the warehouse DB. All are subcommands of
`scripts/inventory.py`; use absolute paths (`<modules>` = the modules root from
the "Active Modules" prompt section). Every stock change is recorded in the
`movements` audit ledger automatically.

## Create / edit items

Add a new item (fails if the SKU exists; logs an `add` movement):

```
python <modules>/warehouse/scripts/inventory.py add \
  --sku SKU-001 --name "Widget" --location A1-03 \
  --quantity 50 --unit-price 9.99 --reorder-level 10
```

Update an existing item — only the flags you pass change. A quantity change is
logged as a `recount` movement:

```
python <modules>/warehouse/scripts/inventory.py update --sku SKU-001 --unit-price 10.49
python <modules>/warehouse/scripts/inventory.py update --sku SKU-001 --name "Widget v2"
```

Remove an item (logs a `remove` movement):

```
python <modules>/warehouse/scripts/inventory.py remove --sku SKU-001
```

## Stock movements

Receive incoming stock (positive movement; `--reference` records a PO/order,
`--reason` a free-text note):

```
python <modules>/warehouse/scripts/inventory.py receive --sku SKU-001 --qty 25 --reference PO-1042
```

Ship stock out (negative movement; refuses to go below zero):

```
python <modules>/warehouse/scripts/inventory.py ship --sku SKU-001 --qty 5 --reference ORD-77
```

Adjust by a raw signed delta — for corrections (e.g. damage, recounts):

```
python <modules>/warehouse/scripts/inventory.py adjust --sku SKU-001 --delta -2 --reason damaged
```

Relocate an item, or change its reorder threshold:

```
python <modules>/warehouse/scripts/inventory.py move --sku SKU-001 --location B3-09
python <modules>/warehouse/scripts/inventory.py set-reorder --sku SKU-001 --level 15
```

Use `receive`/`ship` for normal in/out flow (they capture intent + reference);
reserve `adjust` for corrections that aren't a true receipt or shipment.
