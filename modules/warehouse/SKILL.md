# warehouse

Lightweight warehouse / inventory management backed by a single CSV file,
plus a UI block that pushes a pre-filled item form into the chat.

## When to use

- The user asks to add, update, remove, or list warehouse stock.
- The user wants to "fill the form" / "open the item form" for a SKU.
- The user wants to bootstrap a fresh inventory file from the template.

## Data model

CSV at `<modules>/warehouse/data/inventory.csv`. Columns:

- `sku` (string, unique key)
- `name` (string)
- `location` (string, e.g. `A1-03`)
- `quantity` (int)
- `unit_price` (float)
- `reorder_level` (int)
- `updated_at` (ISO-8601 UTC, written automatically)

`data/inventory.template.csv` is the empty template — copy it if the live
file is missing or corrupted.

## How to use

Bash CWD is the chat workspace, not the modules root. Use absolute paths.
Replace `<modules>` with the absolute modules root announced at the top of
the "Active Module Skills" prompt section above.

List stock (optionally filter by SKU/name substring):

```
python <modules>/warehouse/scripts/inventory.py list
python <modules>/warehouse/scripts/inventory.py list --query widget
```

Add a new item (fails if SKU exists):

```
python <modules>/warehouse/scripts/inventory.py add \
  --sku SKU-001 --name "Widget" --location A1-03 \
  --quantity 50 --unit-price 9.99 --reorder-level 10
```

Update an existing item (only the flags you pass are changed):

```
python <modules>/warehouse/scripts/inventory.py update --sku SKU-001 --quantity 42
```

Adjust stock by a delta (positive = receive, negative = ship):

```
python <modules>/warehouse/scripts/inventory.py adjust --sku SKU-001 --delta -5
```

Remove an item:

```
python <modules>/warehouse/scripts/inventory.py remove --sku SKU-001
```

Reset the inventory to the empty template:

```
python <modules>/warehouse/scripts/inventory.py reset
```

Push the item-form block into the chat. With no `--sku`, opens an empty
form for creating a new item. With `--sku`, pre-fills from the current
CSV row so the user can edit + submit:

```
python <modules>/warehouse/scripts/push_form.py
python <modules>/warehouse/scripts/push_form.py --sku SKU-001
```

When the user clicks Save inside the form, the block does NOT call back
through a typed RPC. Instead it injects a plain chat message that names
the exact `inventory.py add|update --sku ... --name ...` command to run.
Treat that injected message like any other user prompt: parse it, run
the suggested command, and confirm the result. Clicking Cancel injects a
short "no changes to apply" message.

`push_form.py` scans the CSV before pushing and injects autocomplete
suggestions (distinct `sku`, `name`, `location` values) so the user gets
a native `<datalist>` dropdown on those fields. In create mode the form
also blocks duplicate SKUs client-side using that list.

`push_form.py` reads `$ATRIA_SESSION_ID` and `$ATRIA_API_BASE` from the
bash env (both exported automatically) — do not set them manually.

## Files

- `SKILL.md` — this file.
- `data/inventory.template.csv` — empty template with the header row.
- `data/inventory.csv` — live inventory (auto-created from template).
- `scripts/inventory.py` — CSV CRUD CLI (list / add / update / adjust / remove / reset).
- `scripts/push_form.py` — pushes `blocks/item_form.html` via `push_block`.
- `blocks/item_form.html` — sandboxed iframe form for an inventory item.
