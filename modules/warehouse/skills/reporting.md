---
name: reporting
description: Filtered listing, summary KPIs, low-stock, valuation, movement history, and read-only SQL queries.
---

# warehouse · reporting

Read-only views over the warehouse DB. All are subcommands of
`scripts/inventory.py`; use absolute paths (`<modules>` = the modules root from
the "Active Modules" prompt section). Append `--json` to any of these for
machine-readable output.

## Filtered listing

Filters combine; sort by `sku` / `name` / `quantity` / `value` / `updated`:

```
python <modules>/warehouse/scripts/inventory.py list --query widget
python <modules>/warehouse/scripts/inventory.py list --location A1 --low-only
python <modules>/warehouse/scripts/inventory.py list --min-price 5 --max-price 50 --sort value
```

`--query` matches sku/name substrings; `--location` matches the location
substring; `--low-only` keeps items at or below their reorder level.

## Summary KPIs

Distinct SKUs, total units, total inventory value, low-stock count, and value
broken down by location:

```
python <modules>/warehouse/scripts/inventory.py summary
```

## Low stock

Just the items at or below their reorder level:

```
python <modules>/warehouse/scripts/inventory.py low-stock
```

## Valuation

Inventory value grouped by location (or by sku):

```
python <modules>/warehouse/scripts/inventory.py valuation --by location
python <modules>/warehouse/scripts/inventory.py valuation --by sku
```

## Movement history

The audit ledger, newest first. Omit `--sku` for the whole warehouse:

```
python <modules>/warehouse/scripts/inventory.py history --limit 50
python <modules>/warehouse/scripts/inventory.py history --sku SKU-001 --limit 20
```

## Read-only query

Run an arbitrary **single `SELECT`/`WITH` statement** against the DB. Writes and
multi-statement input are rejected and the connection is opened read-only:

```
python <modules>/warehouse/scripts/inventory.py query \
  --sql "SELECT location, SUM(quantity) AS units FROM items GROUP BY location"
```
