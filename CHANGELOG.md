# Changelog

## 0.2.0 - 2026-11-06

### Changed defaults

- `logs --follow` prints rows in the order they arrive in ClickHouse, using
  the table's `InsertedAt` column, so late rows are shown instead of skipped.
  Output trails the server clock by about two seconds. Tables without
  `InsertedAt` keep the event-time cursor, with a note on stderr.
- `logs -f table` prints one line per row with a marker, time, severity
  glyph, host, source, service and message; no header or borders. `--full`
  and `--raw` keep the rich table, as do all other commands.
- `logs -t` windows end at `now()`; rows stamped in the future are hidden
  unless `--include-future` is given.
- `query` without `--utc` renders `DateTime` values in the profile's
  `default_timezone` (was the server zone).
- Unexpected crashes are reported to Sentry with the command reduced to
  command and flag names. Configuration, usage, connection and SQL errors
  are not reported. `sentry_dsn = ""` disables it.

### Fixed

- A log line containing square brackets such as `[/var/lib/data /]` no
  longer crashes table output or ends a `--follow` run.
- `--follow` output reaches a pipe as it arrives; `--follow | head` exits
  cleanly.
- `query "SQL"` works from cron, CI and agent shells with an open, unwritten
  stdin.
- `-f json` output no longer fails on `Date`, `Decimal`, `UUID` or IP values.
- The Sentry release tag matches the package version.

### Added

- `logs`: `--interval`, `--include-future`, `--by-event-time`, `--wrap`,
  `--no-glyphs`, `--full-timestamps`.
- `query`: `--utc`.
- `CLICKHOUSE_TOOL_FORCE_CRASH=1` raises at startup to verify crash reporting.
- Late and future-stamped rows: `lag_s` in `json`/`ndjson`/`toon` output and
  markers in the line layout; thresholds `late_after_s` (124) and
  `future_after_s` (5) in the config.
- Config keys `sentry_dsn`, `aws_profile`, `aws_region` (top level, per
  profile, and on an SSM reference as `aws_region`), `late_after_s`,
  `future_after_s`, `[layout.widths]`.
- `config` shows the Sentry DSN (masked), the AWS profile and region, and
  where each came from.
- SSM failures name the AWS profile and region used and their sources.

## 0.1.1

Initial public release.
