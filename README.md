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
