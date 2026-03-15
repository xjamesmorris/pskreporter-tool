# pskreporter-tool

A command-line tool that fetches reception reports for an amateur radio callsign from [pskreporter.info](https://pskreporter.info) and outputs them as CSV.

No external dependencies — pure Python standard library only.

## Requirements

Python 3.10+

## Usage

```
python pskreporter.py <CALLSIGN> [options]
```

**Options:**

| Flag | Description |
|------|-------------|
| `-o, --output FILE` | Write CSV to file (default: stdout) |
| `-t, --hours HOURS` | Look back this many hours (default: 6, max 6) |
| `-m, --mode MODE` | Filter by mode, e.g. `FT8`, `FT4`, `PSK31` |
| `--band METRES` | Filter by band in metres, e.g. `40`, `20`, `10` |
| `--test` | Dry-run: print the request URL and exit without fetching |
| `--version` | Show version and exit |

**Examples:**

```bash
# Print all reports for N1DQ to stdout
python pskreporter.py N1DQ

# Save FT8 reports on 20m to a file
python pskreporter.py W1AW --mode FT8 --band 20 -o reports.csv

# Fetch only the last 2 hours
python pskreporter.py VK2ABC --hours 2

# Preview the URL that would be fetched
python pskreporter.py N1DQ --test
```

## Output

CSV with columns: `timestamp_utc`, `sender_callsign`, `sender_locator`, `receiver_callsign`, `receiver_locator`, `frequency_hz`, `band_m`, `mode`, `snr_db`, `receiver_dxcc`, `receiver_dxcc_code`, `flow_start_seconds`

Reports are sorted newest-first, capped at 100 (the API maximum).

## Rate limiting

pskreporter.info requests at least 5 minutes between queries. This tool enforces that limit using a local state file at `~/.pskreporter/state.json`. If you run it too soon, it will print a warning and exit without making a request.

## Running the tests

Install [pytest](https://pytest.org), then run from the project root:

```bash
pip install pytest
pytest
```

All tests are in `tests/test_pskreporter.py` and use only the standard library plus pytest (no network calls).
