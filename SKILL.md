# clickhouse-tool

CLI to query and inspect ClickHouse, over both the native protocol
(port 9000) and HTTP (port 8123). Invoked as `clickhouse-tool`.

## When to Use / When NOT to Use

| Use clickhouse-tool for | Do NOT use for |
|--------------------------|-----------------|
| Browsing OTel-shaped logs with a `logs`/`hosts`/`services` porcelain | Writes or DDL (the tool is read-only by design) |
| Counting hosts/services over logs or metrics activity | Detailed metric values/time series (`hosts`/`services` only count activity, not metric values) |
| Inspecting any allow-listed table's rows/columns | Cluster administration (node/shard management, replication control) |
| Running direct SQL against the cluster | |
| Scripting against pinned exit codes | |

## Quick Reference

```bash
clickhouse-tool logs --service payments -l error -t 1h    # recent error logs for a service
clickhouse-tool logs --follow --host k8s-3                # tail new rows continuously
clickhouse-tool hosts -t 15m                              # host counts, last 15 minutes
clickhouse-tool services --unbounded                      # every service, no cap
clickhouse-tool metrics names -n 10                       # most active metric names
clickhouse-tool metrics status k8s.node.memory -t 1h       # min/max/avg/stddev per metric
clickhouse-tool metrics histogram system.cpu.utilization -t 1h  # time-bucketed stats
clickhouse-tool tables                                     # every table list/lift/query may target
clickhouse-tool list otel.otel_logs -n 5                  # peek at raw rows
clickhouse-tool lift otel.otel_logs                        # describe columns
clickhouse-tool query "SELECT count() FROM otel.otel_logs" # raw SQL
clickhouse-tool config                                     # show resolved profile, no AWS needed
```

## Commands

### `logs` — the baseline verb

```bash
clickhouse-tool logs [--host/-h HOST] [--service SERVICE] [--namespace NS]
                      [--container C] [--level/-l LEVEL] [-t/--time-range 15m|2h|1d]
                      [--search/-s TERM] [--sort SORT] [--full] [--raw]
                      [--count] [--follow] [--utc] [-n/--limit N]
                      [-f/--format table|json|ndjson|toon]
```

- `--count` returns a single row count instead of rows.
- `--full`/`--raw` select every column and switch to nested output — the only
  verb that may stream (via the `ndjson` formatter).
- `--follow` polls continuously for new rows, oldest first, until Ctrl-C.
  `-t` seeds the starting point (how far back the first batch reaches);
  after that, only rows newer than the last one seen are printed. Not
  compatible with `--count` or `--sort` (follow mode always orders
  ascending by time).
- The `ts` column renders in local time by default; `--utc` shows UTC
  instead. The profile's `default_timezone` sets the non-`--utc` default
  (`local`, `UTC`, or any IANA zone name — `local` resolves to the
  machine's own zone). `--full`/`--raw` show the raw server value
  unconverted, since they select `*` directly, not the `ts` alias.
- Time window defaults to the profile's `default_window` (`2h` in the
  example config) when `-t` is omitted.

### `hosts` / `services` — grouped counts

```bash
clickhouse-tool hosts    [--namespace NS] [--container C] [--level/-l LEVEL]
                          [-t/--time-range WINDOW] [--search/-s TERM]
                          [--stream logs|metrics] [-n/--limit N] [--unbounded]
                          [-f/--format ...]
clickhouse-tool services [same flags]
```

- Grouped by host or service, ordered by count descending, capped at 200
  rows unless `--unbounded`. Each row also shows `last_seen`, rendered as a
  relative time (`2h 20m ago`) -- a second unit only above a 10 threshold,
  seconds is the finest granularity shown.
- `--stream metrics` (default) counts metric datapoints -- useful since not
  every host/service that emits metrics also emits logs. `--stream logs`
  counts log rows instead. Metrics mode only supports `-t`/`--time-range`;
  `--namespace`, `--container`, `--level`, `--search` all raise `ConfigError`
  (exit 3) on that stream, since metrics carry none of those attributes.

### `metrics` — metric names, stats, values, and histograms

```bash
clickhouse-tool metrics names   [-t/--time-range WINDOW] [-n/--limit N] [--unbounded] [-f/--format ...]
clickhouse-tool metrics status  <name> [--host H] [--service S] [-t/--time-range WINDOW]
                                 [--split-by host,service] [-f/--format ...]
clickhouse-tool metrics values  <name> [--host H] [--service S] [-t/--time-range WINDOW]
                                 [--follow] [-n/--limit N] [-f/--format ...]
clickhouse-tool metrics histogram <name> [--host H] [--service S] [-t/--time-range WINDOW]
                                   [--bucket WIDTH] [--split-by host,service] [-f/--format ...]
```

- `<name>` matches an exact metric name (`k8s.node.filesystem.capacity`) or a
  dotted stem matching every child metric (`k8s.node.memory`).
- `names` groups by metric name over the metrics stream, ordered by
  datapoint count descending, capped at 200 unless `--unbounded`. Same
  `last_seen` column as `hosts`/`services`.
- `status` reports `min`/`max`/`avg`/`stddev` per matched metric name.
  `--split-by host,service` breaks the summary out per host and/or
  service instead of merging them.
- `values` returns raw datapoints oldest-first, capped at 1000 unless
  `-n` overrides. `--follow` polls continuously starting from the most
  recent matching datapoint (not `-n`-compatible), same semantics as
  `logs --follow`.
- `histogram` buckets datapoints by time, reporting `min`/`max`/`avg`/`count`
  per bucket per matched metric name. `--bucket` sets the width explicitly
  (`5m`, `1h`, ...); omitted, it's sized automatically from the time window
  to land around 36 buckets, snapped to a round duration (seconds through
  weeks). `--split-by host,service` breaks each metric's buckets out per
  host and/or service instead of merging them.

### `list` / `lift` — low-level table inspection

```bash
clickhouse-tool list <table> [-n/--limit N] [-f/--format ...]   # raw rows
clickhouse-tool lift <table> [-f/--format ...]                  # column metadata
```

- `<table>` must be allow-listed: any `otel.<identifier>`, or one of
  `system.parts`, `.errors`, `.tables`, `.columns`, `.metrics`,
  `.asynchronous_metrics`, `.query_log`.
- `lift` defaults to `json` output (nested-friendly), not the profile's
  `default_format`.

### `query` — raw SQL

```bash
clickhouse-tool query "SELECT ... " [--param name=value ...] [-f/--format ...]
echo "SELECT 1" | clickhouse-tool query
```

- SQL comes from the positional argument, or from stdin if no argument is
  given and stdin is not a TTY — never both at once.
- `--param` is repeatable, binds named parameters as strings.
- Bypasses the query builder entirely: no table allow-list, no column
  validation. Read-only safety comes **solely** from the server-side
  `readonly=2` setting, not from anything this tool parses. Server errors
  (including malformed SQL) echo back verbatim — the caller wrote the query.

### `config` — show the resolved profile

```bash
clickhouse-tool config [--profile NAME]
```

- Never touches AWS SSM and never opens a connection — works with zero AWS
  credentials present. Secrets print as unresolved references
  (`(unresolved, ssm:<path>)`), never as values.

### `tables` — list what `list`/`lift`/`query` may target

```bash
clickhouse-tool tables [--profile NAME] [-f/--format ...]
```

- Combines the profile's `otel.*` tables (queried live from the cluster)
  with the seven fixed `system.*` tables the allow-list also accepts.
  Unlike `config`, this connects to the cluster.

## Profiles and Connection

- `--profile NAME` on any command selects a named profile from config.
- Config precedence, highest first: CLI flag > `CLICKHOUSE_TOOL_*` env var >
  selected profile > project-local `./clickhouse-tool.toml` > user
  `~/.config/clickhouse-tool/config.toml` > built-in defaults.
- Copy `config.example.toml` to get started; it ships a `pilot` (native,
  port 9000) and `pilot-http` (HTTP, port 8123) profile pointed at the same
  cluster, with credentials resolved lazily from AWS SSM (`user`/`password`
  as `{ ssm = "<path>" }`).
- Secrets are resolved lazily — only verbs that actually connect touch SSM.
  `config` never does.

## Output Formats

| Flag | Use case |
|------|----------|
| `-f json` | Agent processing, or nested output (`lift`, `--full`, `--raw`) — buffered array, Map columns kept nested |
| `-f ndjson` | Streaming large result sets row-by-row — never buffers the full set |
| `-f table` | Presenting results to a human in a terminal — rich table, null renders `-` |
| `-f toon` | Default format — compact `name[N]{fields}` dialect, cheapest to read/grep |

Format defaults to the profile's `default_format` (`toon` in the example
config) when `-f` is omitted, except `lift`, which defaults to `json`.

`-f table` humanizes numbers and timestamps; every other format renders raw
values, unaffected by any of the flags below:
- Numbers get a k/m/g suffix once the scaled value would read 10 or
  higher (`1024` stays `1024`, `10000` becomes `10k`), rounded to 2
  decimal places by default -- override with `--decimals N` (`metrics
  status`/`values`/`histogram`).
- Timestamps drop their seconds component once the queried time window
  exceeds 3 hours, showing whole seconds below that. `--ts-decimals N`
  (`metrics values`/`histogram`) forces second-level display with `N`
  fractional digits, overriding the window-based default.

## Error Handling

| Exit code | Meaning | Agent action |
|-----------|---------|---------------|
| 0 | Success | Proceed |
| 1 | General/unexpected error | Report — no documented outcome maps here |
| 2 | Usage error | Fix command syntax |
| 3 | Config error (bad profile, unknown column/table/sort, malformed `--param`, missing driver, bad `--stream` value) | Check flags/profile, fix and retry |
| 4 | Connection failed | Cluster unreachable — check host/port/transport |
| 5 | Auth failed | Check credentials / SSM refs |
| 6 | Query timeout | Narrow the query or raise `query_timeout` in the profile |
| 7 | Result too large | Narrow the time window or add a `--limit` |
| 8 | Server resource error | Cluster is under memory/resource pressure — retry later |
| 9 | Permission denied | Check the ClickHouse user's grants |
| 10 | Schema error | Table/column doesn't exist as named — check `lift` |
| 11 | Unsupported filter (e.g. `--container` on a key that doesn't exist) | The container-preflight check failed — verify the filter value |
| 12 | Server error (unmapped ClickHouse code) | Server returned an error code with no local mapping — report the message |

Every typed error prints its message to stderr; stdout is reserved for
data only. `BrokenPipeError` (e.g. piping into `head`) exits 0 quietly,
no traceback.

## Global Options

| Flag | Purpose |
|------|---------|
| `--profile NAME` | Select connection profile |
| `-f/--format table\|json\|ndjson\|toon` | Output format |
| `-v/--verbose` | Enable debug logging |
| `--help` | Show help (note: `-h` is reserved for `--host` on `logs`, not help) |

## Known Limitations

- No cluster administration commands (node/shard/replication management)
  — use ClickHouse's own tooling for that.
- `hosts --stream metrics` / `services --stream metrics` only enumerate
  activity against `otel_metrics_gauge`; the other metrics tables
  (`otel_metrics_sum`, `otel_metrics_histogram`, etc. — see `tables`) have
  no porcelain support yet — use `list`/`query` directly against them.
