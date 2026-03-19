# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Tool

```bash
python pskreporter.py <CALLSIGN> [options]
```

Options:
- `-o, --output FILE` — write CSV to file (default: stdout)
- `-t, --hours HOURS` — lookback window in hours (omit for no time limit; API supports up to 24h)
- `-m, --mode MODE` — filter by mode (e.g., FT8, FT4, PSK31)
- `--band BAND` — filter by band in metres (e.g., 40, 20, 10)
- `--json` — output as JSON array instead of CSV
- `--test` — dry-run: print the request URL to stdout and exit without fetching

No external dependencies — pure Python stdlib only.

## Platform Compatibility

All code must run identically on Linux, macOS, and Windows. Concretely:
- Use `pathlib.Path` or `os.path` for file paths, never hardcoded `/` separators
- Use `os.linesep` or the `newline=` parameter on `open()` consciously — the CSV writer already uses `newline=""` as required
- Avoid shell-specific syntax or POSIX-only stdlib calls
- Do not assume a particular Python launcher name (`python` vs `python3`) in documentation examples

## Architecture

Single-file script (`pskreporter.py`) implementing a linear pipeline:

```
CLI args → build_url() → fetch_xml() → parse_reports() → apply_filters() → sort/cap → write_csv()
```

**Key design decisions:**
- Info/errors go to stderr; CSV data to stdout — follows Unix convention for pipeline composability
- Filtering (`--mode`, `--band`) is client-side after fetching full results from the API
- Default behaviour: no time filter, `rptlimit=10` sent to API; `--hours` adds `flowStartSeconds`
- Band assignment uses hardcoded `BAND_EDGES_HZ` frequency ranges
- `parse_reports()` does frequency→int, epoch→UTC ISO, and band computation all in one pass
- API requests use a custom User-Agent; the API endpoint is `API_BASE` at the top of the file
- 5-minute rate limit enforced client-side via `~/.pskreporter/state.json`

**Error handling:**
- Network errors: caught, reported to stderr, exit code 1
- Malformed XML records: skipped with debug output rather than aborting
- Invalid timestamps: treated as empty strings

## PSKReporter API Notes

Endpoint: `https://retrieve.pskreporter.info/query`

- **Callsigns with `/`** (portable/mobile/beacon, e.g. `NO0T/P`) work with standard percent-encoding (`%2F`); the API accepts both forms.
- `flowStartSeconds` is optional; omitting it returns the most recent N reports (no time bound). Max lookback is 24 hours (`-86400`).
- `rptlimit` controls how many records the server returns (hard cap 100).
- `rronly=1` — reception reports only; `noactive=1` — suppresses active receiver list. Both are safe and do not filter out reception reports.
- `frange=lower-upper` (Hz) enables server-side frequency filtering — a possible future replacement for client-side `--band`.
