#!/usr/bin/env python3
"""
pskreporter.py — Fetch reception reports for a callsign from pskreporter.info

Usage:
    python pskreporter.py <CALLSIGN> [options]

Options:
    -o, --output FILE       Write CSV to FILE instead of stdout
    -t, --hours HOURS       Look back this many hours (default: 6, max enforced by API)
    -m, --mode MODE         Filter by mode (e.g. FT8, FT4, PSK31)
    --band BAND             Filter by band in metres (e.g. 40, 20, 10)
    --test                  Dry-run: print the request URL to stdout and exit
    -h, --help              Show this help message

Examples:
    python pskreporter.py N1DQ
    python pskreporter.py W1AW --mode FT8 -o reports.csv
    python pskreporter.py VK2ABC --hours 2 --band 20

Notes:
    - Makes a single HTTP request; please do not run more often than every 5 minutes.
    - Returns up to 100 reception reports (API maximum for this endpoint).
    - The API returns XML; this script converts it to CSV.
"""

import argparse
import csv
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Band edges in Hz for common amateur bands
BAND_EDGES_HZ = {
    "160": (1_800_000,   2_000_000),
    "80":  (3_500_000,   4_000_000),
    "60":  (5_330_500,   5_405_000),
    "40":  (7_000_000,   7_300_000),
    "30":  (10_100_000, 10_150_000),
    "20":  (14_000_000, 14_350_000),
    "17":  (18_068_000, 18_168_000),
    "15":  (21_000_000, 21_450_000),
    "12":  (24_890_000, 24_990_000),
    "10":  (28_000_000, 29_700_000),
    "6":   (50_000_000, 54_000_000),
    "2":   (144_000_000, 148_000_000),
}

CSV_FIELDS = [
    "timestamp_utc",
    "sender_callsign",
    "sender_locator",
    "receiver_callsign",
    "receiver_locator",
    "frequency_hz",
    "band_m",
    "mode",
    "snr_db",
    "receiver_dxcc",
    "receiver_dxcc_code",
    "flow_start_seconds",
]

__version__ = "0.1"

API_BASE = "https://retrieve.pskreporter.info/query"
USER_AGENT = (
    "pskreporter-cli/1.0 "
    "(python fetch script; single query; "
    "contact: user of this script)"
)


def freq_to_band(freq_hz: int) -> str:
    """Return the amateur band (in metres) for a given frequency in Hz."""
    for band, (low, high) in BAND_EDGES_HZ.items():
        if low <= freq_hz <= high:
            return band
    return ""


def build_url(callsign: str, hours: float) -> str:
    flow_start = -int(hours * 3600)
    params = {
        "senderCallsign": callsign.upper(),
        "flowStartSeconds": str(flow_start),
        "rronly": "1",       # reception reports only (no active monitor list)
        "noactive": "1",     # suppress active callsign list
    }
    return f"{API_BASE}?{urllib.parse.urlencode(params)}"


def fetch_xml(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_reports(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    reports = []
    for rr in root.iter("receptionReport"):
        freq_str = rr.get("frequency", "")
        try:
            freq_hz = int(freq_str)
        except ValueError:
            freq_hz = 0

        flow_str = rr.get("flowStartSeconds", "")
        try:
            flow_ts = int(flow_str)
            ts_utc = datetime.fromtimestamp(flow_ts, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except (ValueError, OSError, OverflowError):
            ts_utc = ""
            flow_ts = flow_str

        reports.append(
            {
                "timestamp_utc": ts_utc,
                "sender_callsign": rr.get("senderCallsign", ""),
                "sender_locator": rr.get("senderLocator", ""),
                "receiver_callsign": rr.get("receiverCallsign", ""),
                "receiver_locator": rr.get("receiverLocator", ""),
                "frequency_hz": freq_hz,
                "band_m": freq_to_band(freq_hz),
                "mode": rr.get("mode", ""),
                "snr_db": rr.get("sNR", ""),
                "receiver_dxcc": rr.get("receiverDXCC", ""),
                "receiver_dxcc_code": rr.get("receiverDXCCCode", ""),
                "flow_start_seconds": flow_ts,
            }
        )
    return reports


def apply_filters(
    reports: list[dict], mode: str | None, band: str | None
) -> list[dict]:
    if mode:
        mode_upper = mode.upper()
        reports = [r for r in reports if r["mode"].upper() == mode_upper]
    if band:
        reports = [r for r in reports if r["band_m"] == band]
    return reports


def write_csv(reports: list[dict], dest) -> None:
    writer = csv.DictWriter(dest, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(reports)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch reception reports for a callsign from pskreporter.info",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("callsign", help="Sender callsign to look up (e.g. N1DQ)")
    parser.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Write CSV to FILE (default: stdout)",
    )
    parser.add_argument(
        "-t", "--hours",
        type=float,
        default=6.0,
        metavar="HOURS",
        help="Look back this many hours (default: 6; API caps at 6 anyway)",
    )
    parser.add_argument(
        "-m", "--mode",
        metavar="MODE",
        help="Filter by mode, e.g. FT8, FT4, PSK31",
    )
    parser.add_argument(
        "--band",
        metavar="METRES",
        help="Filter by band in metres, e.g. 40, 20, 10",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Dry-run: print the request URL to stdout and exit without fetching",
    )
    args = parser.parse_args()

    # Clamp hours to API's 6-hour maximum
    hours = min(max(args.hours, 0.1), 6.0)
    if hours != args.hours:
        print(
            f"[info] Hours clamped to {hours} (API maximum is 6 hours)",
            file=sys.stderr,
        )

    url = build_url(args.callsign, hours)

    if args.test:
        print(url)
        return

    print(f"[info] Fetching: {url}", file=sys.stderr)

    try:
        xml_text = fetch_xml(url)
    except Exception as exc:
        print(f"[error] Failed to fetch data: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        reports = parse_reports(xml_text)
    except ET.ParseError as exc:
        print(f"[error] Failed to parse XML response: {exc}", file=sys.stderr)
        print("[debug] Raw response (first 500 chars):", file=sys.stderr)
        print(xml_text[:500], file=sys.stderr)
        sys.exit(1)

    total_before_filter = len(reports)
    reports = apply_filters(reports, args.mode, args.band)

    # Sort newest-first
    reports.sort(key=lambda r: r["flow_start_seconds"] or 0, reverse=True)

    # Honour the 100-report cap (API usually does this, but be safe)
    reports = reports[:100]

    print(
        f"[info] {total_before_filter} reports received; "
        f"{len(reports)} after filtering",
        file=sys.stderr,
    )

    if args.output:
        try:
            with open(args.output, "w", newline="", encoding="utf-8") as fh:
                write_csv(reports, fh)
            print(f"[info] CSV written to {args.output}", file=sys.stderr)
        except OSError as exc:
            print(f"[error] Could not write output file: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        write_csv(reports, sys.stdout)


if __name__ == "__main__":
    main()
