---
name: data-io
description: Bulk data operations — export to csv/json, import, migrate from legacy CSV, and reset.
---

# warehouse · data-io

Bulk data and lifecycle operations on the warehouse DB. All are subcommands of
`scripts/inventory.py`; use absolute paths (`<modules>` = the modules root from
the "Active Modules" prompt section).

## Export

Dump items or the movement ledger to stdout, or to a file with `--out`:

```
python <modules>/warehouse/scripts/inventory.py export --format csv --out backup.csv
python <modules>/warehouse/scripts/inventory.py export --table movements --format json
```

`--table` is `items` (default) or `movements`; `--format` is `json` (default) or
`csv`.

## Import

Bulk-load items from CSV or JSON. A CSV needs the same columns as the `items`
table (`sku,name,location,quantity,unit_price,reorder_level`). New SKUs are
inserted (logged as `add`); existing SKUs are updated (a quantity change logs a
`recount`). `--replace` clears all items first:

```
python <modules>/warehouse/scripts/inventory.py import --file new_stock.csv --format csv
python <modules>/warehouse/scripts/inventory.py import --file seed.json --format json --replace
```

## Migrate

One-shot import from a legacy `data/inventory.csv` if one is present (the DB
also auto-migrates from it on first creation):

```
python <modules>/warehouse/scripts/inventory.py migrate
```

## Reset

Empty both the `items` and `movements` tables (destructive — confirm with the
user first):

```
python <modules>/warehouse/scripts/inventory.py reset
```
