---
name: data-management
description: Bulk data + resource pool config — data export, data reset, resource set/add/retire.
---

# item_flow_tracking · data-management

Bulk data and resource-pool lifecycle operations. All are subcommands of
`scripts/flow.py`; use absolute paths (`<modules>` = the modules root from the
"Active Modules" prompt section).

## Export

Dump a table to stdout, or to a file with `--out`. `--table` is one of
`orders` (default), `lots`, `resources`, `events`; `--format` is `json`
(default) or `csv`:

```
python <modules>/item_flow_tracking/scripts/flow.py data export --table lots --format csv --out lots.csv
python <modules>/item_flow_tracking/scripts/flow.py data export --table events --format json
```

## Reset

Empty all orders/lots/events and re-seed the default resource pool
(destructive — confirm with the user first):

```
python <modules>/item_flow_tracking/scripts/flow.py data reset
```

## Configure the resource pool

Mark a resource out of service, or grow/shrink the pool. `resource add` appends
N of a kind (ids continue after the current max); `resource retire` removes a
free resource (refuses if occupied):

```
python <modules>/item_flow_tracking/scripts/flow.py resource set --resource washer-3 --status maintenance
python <modules>/item_flow_tracking/scripts/flow.py resource add --kind bin --count 5
python <modules>/item_flow_tracking/scripts/flow.py resource retire --resource bin-15
```
