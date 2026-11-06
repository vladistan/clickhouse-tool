# clickhouse-tool

A command-line client for querying and inspecting ClickHouse, over both
the native protocol (port 9000) and HTTP (port 8123).

`clickhouse-tool` provides porcelain commands (`logs`, `hosts`, `services`)
for browsing OTel-shaped log data, plus low-level verbs (`query`, `list`,
`lift`, `config`) for direct inspection of any table. Output renders as a
table, JSON, NDJSON, or the compact TOON format, with pinned typed exit
codes for scripting.

## Install

```
pip install clickhouse-tool[native]   # native protocol (port 9000)
pip install clickhouse-tool[http]     # HTTP protocol (port 8123)
pip install clickhouse-tool[all]      # both
```

## Configuration

Copy `config.example.toml` to `./clickhouse-tool.toml` or
`~/.config/clickhouse-tool/config.toml` and fill in a profile for your
cluster. See that file for the full set of options.

## Commands

`logs` queries log rows. Filters: `--host/-h`, `--service`, `--namespace`,
`--container`, `--level/-l` (minimum severity), `--time-range/-t` (e.g.
`15m`, `2h`, `1d`), `--search/-s`. Shape: `--limit/-n`, `--sort`
(e.g. `@timestamp:desc`), `--count`, `--full` / `--raw` (every column,
nested output). Follow: `--follow`, `--interval`, `--by-event-time`.
Display: `--format/-f` (`table`, `json`, `ndjson`, `toon`), `--utc`,
`--include-future`, `--wrap`, `--no-glyphs`, `--full-timestamps`.

`query "SQL"` runs raw SQL (or reads it from stdin). `--param name=value`
binds a named parameter, repeatable. `--utc` renders `DateTime` values in
UTC.

Every command takes `--profile` (named connection profile), `--format/-f`
and `--verbose/-v`. Other commands: `hosts`, `services`, `list`, `lift`,
`tables`, `config`, and the `metrics` group.

## Log lines on a terminal

`logs -f table` prints one line per row, with no header or borders:

```
 🐢 14:18:55 🔔   win-ds5          Security       otelcol-edge       │ late warning
    14:20:52 ℹ    web-1            ingress-nginx  controller         │ HealthProbe
    14:21:03 🔥   db-1             pgbouncer-1    docker             │ login failed
```

Columns: marker, time, severity, host, source, service, message.

- Marker: 🐢 a row inserted late, 🔮 a row stamped in the future (`>` and `<` when piped).
- Severity from `SeverityNumber`: 🔬 TRACE, 🐛 DEBUG, ℹ INFO, 🔔 WARN, 🔥 ERROR, 💥💥 FATAL
  (`T D I W E F` when piped). `--no-glyphs` prints the words.
- Time is `HH:MM:SS` under `--follow`; the full date otherwise, when piped, for a
  row from another day, or with `--full-timestamps`.
- Host without its domain; service without `.service`; source is the Kubernetes
  namespace, the container name, the Windows event channel, or the log source
  (`journald`, `syslog`). Long values keep their first 4 characters and their tail.
- The message is cut at the terminal edge; `--wrap` wraps it instead. Piped output
  prints the whole message on one line. Control characters print as `\xNN`.
- On terminals narrower than 100 columns the service, then source, then host
  columns are dropped.

Column widths can be set in the config under `[layout.widths]` (`host`, `source`,
`service`). `--full` and `--raw` keep the rich table, as do all other commands.

## AWS settings for SSM secrets

A profile's `user` and `password` can point at AWS SSM parameters:
`password = { ssm = "/path/to/parameter" }`. The AWS profile and region
used for the lookup come from, highest first:

1. the SSM reference itself: `{ ssm = "...", aws_profile = "...", aws_region = "..." }`
2. the environment: `AWS_PROFILE`, then `AWS_REGION` or `AWS_DEFAULT_REGION`
3. the connection profile: `aws_profile` and `aws_region` keys
4. the top of the config file: the same keys

Each key falls back on its own. With nothing set, boto3's default chain
applies. `clickhouse-tool config` shows the values in effect and where
each came from, and an SSM failure names the profile and region it used.

## Usage notes

- `logs -t 2h` shows rows stamped between two hours ago and now. Rows
  stamped in the future, from a host with a bad clock, are hidden unless
  you pass `--include-future`.
- `logs --follow` prints rows in the order they arrive in ClickHouse,
  using the table's `InsertedAt` column, so a row delivered late still
  shows up. Output trails the server clock by about two seconds. A table
  without `InsertedAt` is followed by event time instead, with a note on
  stderr; `--by-event-time` asks for that on any table. Polls run every
  2 seconds (`--interval SECONDS`); a full batch is followed by an
  immediate poll. Output is flushed after every poll, so
  `--follow | grep X` shows lines as they arrive.
- A row inserted more than `late_after_s` seconds after its event time
  (default 124), or stamped more than `future_after_s` seconds ahead of
  it (default 5), is flagged. `json` and `ndjson` output carry `lag_s`
  on flagged rows only; `toon` has a `lag_s` column that is `-` elsewhere.
  Both thresholds are top-level keys in the config file.
- `query "SELECT 1"` works from cron, CI and agent shells; stdin is read
  only when something was actually piped in.
- `query --utc` renders `DateTime` values in UTC. Without it the
  profile's `default_timezone` applies (ClickHouse 23.6 or later).

## Crash reporting

`clickhouse-tool` reports unexpected crashes to the maintainer's Sentry
project. Reporting is on by default.

A report is sent only when the tool hits a bug it did not anticipate.
Configuration errors, usage errors, failed connections, and rejected SQL
are not reported.

A report holds the stack trace, the tool version, the Python and OS
versions, and the command line reduced to command and flag names. It
holds no argument values, no SQL text, no local variable values, and no
query history.

To turn it off, set an empty DSN in the config file or the environment:

```
sentry_dsn = ""                        # in the TOML config
export CLICKHOUSE_TOOL_SENTRY_DSN=""   # or per shell
```

To report to your own Sentry project, set either one to your DSN. The
environment variable wins over the config file. `clickhouse-tool config`
shows which DSN is in effect, with its key masked.

To check delivery, force one crash: `CLICKHOUSE_TOOL_FORCE_CRASH=1
clickhouse-tool config` raises at startup, reports it, and exits 1.
