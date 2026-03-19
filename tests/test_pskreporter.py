"""Unit tests for pskreporter.py"""

import csv
import io
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
import pskreporter


@pytest.fixture(autouse=True)
def isolated_state(tmp_path):
    """Redirect the state file to a temp directory for every test."""
    state_file = tmp_path / "state.json"
    with patch("pskreporter._state_path", return_value=state_file):
        yield state_file


SAMPLE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<receptionReports>
  <receptionReport
    senderCallsign="N1DQ"
    senderLocator="FN42"
    receiverCallsign="W1AW"
    receiverLocator="FN31"
    frequency="14074000"
    flowStartSeconds="1700000100"
    mode="FT8"
    sNR="-10"
    receiverDXCC="United States"
    receiverDXCCCode="K"
  />
  <receptionReport
    senderCallsign="N1DQ"
    senderLocator="FN42"
    receiverCallsign="VK2XY"
    receiverLocator="QF56"
    frequency="14074000"
    flowStartSeconds="1700000000"
    mode="FT8"
    sNR="-15"
    receiverDXCC="Australia"
    receiverDXCCCode="VK"
  />
  <receptionReport
    senderCallsign="N1DQ"
    senderLocator="FN42"
    receiverCallsign="G3XYZ"
    receiverLocator="IO91"
    frequency="7074000"
    flowStartSeconds="1699999900"
    mode="FT4"
    sNR="5"
    receiverDXCC="England"
    receiverDXCCCode="G"
  />
</receptionReports>
"""

EMPTY_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<receptionReports>
</receptionReports>
"""

MALFORMED_RECORD_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<receptionReports>
  <receptionReport
    senderCallsign="N1DQ"
    frequency="bad_freq"
    flowStartSeconds="not_a_number"
    mode="FT8"
  />
</receptionReports>
"""


# ---------------------------------------------------------------------------
# freq_to_band
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("freq_hz,expected_band", [
    (1_800_000,   "160"),
    (3_573_000,   "80"),
    (7_074_000,   "40"),
    (10_136_000,  "30"),
    (14_074_000,  "20"),
    (18_100_000,  "17"),
    (21_074_000,  "15"),
    (24_915_000,  "12"),
    (28_074_000,  "10"),
    (50_313_000,  "6"),
    (144_174_000, "2"),
])
def test_freq_to_band_known(freq_hz, expected_band):
    assert pskreporter.freq_to_band(freq_hz) == expected_band


def test_freq_to_band_edge_inclusive():
    assert pskreporter.freq_to_band(14_000_000) == "20"
    assert pskreporter.freq_to_band(14_350_000) == "20"


@pytest.mark.parametrize("freq_hz", [0, 15_000_000, 999_999_999])
def test_freq_to_band_out_of_band(freq_hz):
    assert pskreporter.freq_to_band(freq_hz) == ""


# ---------------------------------------------------------------------------
# build_url
# ---------------------------------------------------------------------------

def test_build_url_default_uses_callsign_param():
    url = pskreporter.build_url("N1DQ")
    assert "callsign=N1DQ" in url
    assert "senderCallsign" not in url
    assert "receiverCallsign" not in url


def test_build_url_callsign_uppercased():
    assert "callsign=N1DQ" in pskreporter.build_url("n1dq")


def test_build_url_tx_only():
    url = pskreporter.build_url("N1DQ", tx_only=True)
    assert "senderCallsign=N1DQ" in url
    assert "callsign=" not in url


def test_build_url_rx_only():
    url = pskreporter.build_url("N1DQ", rx_only=True)
    assert "receiverCallsign=N1DQ" in url
    assert "callsign=" not in url


def test_build_url_no_hours_omits_flow_start():
    assert "flowStartSeconds" not in pskreporter.build_url("N1DQ")


def test_build_url_hours_adds_flow_start():
    assert "flowStartSeconds=-21600" in pskreporter.build_url("N1DQ", hours=6)


def test_build_url_fractional_hours():
    assert "flowStartSeconds=-1800" in pskreporter.build_url("N1DQ", hours=0.5)


def test_build_url_starts_with_api_base():
    assert pskreporter.build_url("W1AW").startswith(pskreporter.API_BASE)


def test_build_url_default_limit():
    assert "rptlimit=10" in pskreporter.build_url("N1DQ")


def test_build_url_slash_callsign():
    url = pskreporter.build_url("NO0T/P")
    assert "callsign=NO0T%2FP" in url


# ---------------------------------------------------------------------------
# parse_reports
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_reports():
    return pskreporter.parse_reports(SAMPLE_XML)


def test_parse_reports_count(sample_reports):
    assert len(sample_reports) == 3


def test_parse_reports_all_fields_present(sample_reports):
    for field in pskreporter.CSV_FIELDS:
        assert field in sample_reports[0]


def test_parse_reports_frequency_is_int(sample_reports):
    assert isinstance(sample_reports[0]["frequency_hz"], int)
    assert sample_reports[0]["frequency_hz"] == 14_074_000


def test_parse_reports_band_assigned(sample_reports):
    assert sample_reports[0]["band_m"] == "20"
    assert sample_reports[2]["band_m"] == "40"


def test_parse_reports_timestamp_format(sample_reports):
    datetime.strptime(sample_reports[0]["timestamp_utc"], "%Y-%m-%d %H:%M:%S")


def test_parse_reports_snr_preserved(sample_reports):
    assert sample_reports[0]["snr_db"] == "-10"


def test_parse_reports_empty_xml():
    assert pskreporter.parse_reports(EMPTY_XML) == []


def test_parse_reports_malformed_frequency_defaults_to_zero():
    reports = pskreporter.parse_reports(MALFORMED_RECORD_XML)
    assert len(reports) == 1
    assert reports[0]["frequency_hz"] == 0


def test_parse_reports_malformed_timestamp_defaults_to_empty():
    reports = pskreporter.parse_reports(MALFORMED_RECORD_XML)
    assert reports[0]["timestamp_utc"] == ""


# ---------------------------------------------------------------------------
# apply_filters
# ---------------------------------------------------------------------------

def test_apply_filters_by_mode(sample_reports):
    result = pskreporter.apply_filters(sample_reports, mode="FT8", band=None)
    assert len(result) == 2
    assert all(r["mode"] == "FT8" for r in result)


def test_apply_filters_mode_case_insensitive(sample_reports):
    assert len(pskreporter.apply_filters(sample_reports, mode="ft8", band=None)) == 2


def test_apply_filters_by_band(sample_reports):
    result = pskreporter.apply_filters(sample_reports, mode=None, band="40")
    assert len(result) == 1
    assert result[0]["band_m"] == "40"


def test_apply_filters_mode_and_band(sample_reports):
    result = pskreporter.apply_filters(sample_reports, mode="FT8", band="20")
    assert len(result) == 2


def test_apply_filters_no_match(sample_reports):
    assert pskreporter.apply_filters(sample_reports, mode="PSK31", band=None) == []


def test_apply_filters_none(sample_reports):
    assert len(pskreporter.apply_filters(sample_reports, mode=None, band=None)) == 3


# ---------------------------------------------------------------------------
# write_csv
# ---------------------------------------------------------------------------

def test_write_csv_header(sample_reports):
    buf = io.StringIO()
    pskreporter.write_csv(sample_reports, buf)
    buf.seek(0)
    assert csv.DictReader(buf).fieldnames == pskreporter.CSV_FIELDS


def test_write_csv_row_count(sample_reports):
    buf = io.StringIO()
    pskreporter.write_csv(sample_reports, buf)
    buf.seek(0)
    assert len(list(csv.DictReader(buf))) == 3


def test_write_csv_empty():
    buf = io.StringIO()
    pskreporter.write_csv([], buf)
    buf.seek(0)
    assert list(csv.DictReader(buf)) == []


def test_write_csv_values_round_trip(sample_reports):
    buf = io.StringIO()
    pskreporter.write_csv(sample_reports, buf)
    buf.seek(0)
    row = list(csv.DictReader(buf))[0]
    assert row["sender_callsign"] == "N1DQ"
    assert row["mode"] == "FT8"
    assert row["band_m"] == "20"


# ---------------------------------------------------------------------------
# write_json
# ---------------------------------------------------------------------------

def test_write_json_is_valid_json(sample_reports):
    buf = io.StringIO()
    pskreporter.write_json(sample_reports, buf)
    data = json.loads(buf.getvalue())
    assert isinstance(data, list)
    assert len(data) == 3


def test_write_json_fields_present(sample_reports):
    buf = io.StringIO()
    pskreporter.write_json(sample_reports, buf)
    row = json.loads(buf.getvalue())[0]
    for field in pskreporter.CSV_FIELDS:
        assert field in row


def test_write_json_values(sample_reports):
    buf = io.StringIO()
    pskreporter.write_json(sample_reports, buf)
    row = json.loads(buf.getvalue())[0]
    assert row["sender_callsign"] == "N1DQ"
    assert row["mode"] == "FT8"
    assert row["frequency_hz"] == 14_074_000


def test_write_json_empty():
    buf = io.StringIO()
    pskreporter.write_json([], buf)
    assert json.loads(buf.getvalue()) == []


# ---------------------------------------------------------------------------
# main — dry-run / --test flag
# ---------------------------------------------------------------------------

def test_main_test_flag_prints_url(capsys):
    with patch("sys.argv", ["pskreporter.py", "N1DQ", "--test"]):
        pskreporter.main()
    out = capsys.readouterr().out.strip()
    assert "N1DQ" in out
    assert pskreporter.API_BASE in out


def test_main_hours_adds_flow_start(capsys):
    with patch("sys.argv", ["pskreporter.py", "N1DQ", "--hours", "6", "--test"]):
        pskreporter.main()
    assert "flowStartSeconds=-21600" in capsys.readouterr().out


def test_main_no_hours_omits_flow_start(capsys):
    with patch("sys.argv", ["pskreporter.py", "N1DQ", "--test"]):
        pskreporter.main()
    assert "flowStartSeconds" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main — error handling
# ---------------------------------------------------------------------------

def test_main_fetch_failure_exits_1():
    with patch("sys.argv", ["pskreporter.py", "N1DQ"]):
        with patch("pskreporter.fetch_xml", side_effect=OSError("connection refused")):
            with pytest.raises(SystemExit) as exc:
                pskreporter.main()
    assert exc.value.code == 1


def test_main_parse_error_exits_1():
    with patch("sys.argv", ["pskreporter.py", "N1DQ"]):
        with patch("pskreporter.fetch_xml", return_value="<<not xml>>"):
            with pytest.raises(SystemExit) as exc:
                pskreporter.main()
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# main — file output
# ---------------------------------------------------------------------------

def test_main_writes_csv_to_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        path = f.name
    try:
        with patch("sys.argv", ["pskreporter.py", "N1DQ", "-o", path]):
            with patch("pskreporter.fetch_xml", return_value=SAMPLE_XML):
                pskreporter.main()
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 3
        assert rows[0]["sender_callsign"] == "N1DQ"
    finally:
        os.unlink(path)


def test_main_output_sorted_newest_first():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        path = f.name
    try:
        with patch("sys.argv", ["pskreporter.py", "N1DQ", "-o", path]):
            with patch("pskreporter.fetch_xml", return_value=SAMPLE_XML):
                pskreporter.main()
        with open(path, newline="", encoding="utf-8") as f:
            timestamps = [r["flow_start_seconds"] for r in csv.DictReader(f)]
        assert timestamps == sorted(timestamps, reverse=True)
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# main — --json flag
# ---------------------------------------------------------------------------

def test_main_json_stdout(capsys):
    with patch("sys.argv", ["pskreporter.py", "N1DQ", "--json"]):
        with patch("pskreporter.fetch_xml", return_value=SAMPLE_XML):
            pskreporter.main()
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 3
    assert data[0]["sender_callsign"] == "N1DQ"


def test_main_json_to_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        with patch("sys.argv", ["pskreporter.py", "N1DQ", "--json", "-o", path]):
            with patch("pskreporter.fetch_xml", return_value=SAMPLE_XML):
                pskreporter.main()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 3
        assert data[0]["mode"] == "FT8"
    finally:
        os.unlink(path)


def test_main_json_sorted_newest_first(capsys):
    with patch("sys.argv", ["pskreporter.py", "N1DQ", "--json"]):
        with patch("pskreporter.fetch_xml", return_value=SAMPLE_XML):
            pskreporter.main()
    data = json.loads(capsys.readouterr().out)
    timestamps = [r["flow_start_seconds"] for r in data]
    assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# rate limiting — check_rate_limit / record_query
# ---------------------------------------------------------------------------

def test_check_rate_limit_no_state_file_passes(isolated_state):
    # No state file exists yet — should not raise or exit
    assert not isolated_state.exists()
    pskreporter.check_rate_limit()  # must not raise or call sys.exit


def test_record_query_creates_state_file(isolated_state):
    pskreporter.record_query()
    assert isolated_state.exists()
    data = json.loads(isolated_state.read_text())
    assert "last_query" in data
    assert abs(data["last_query"] - time.time()) < 5


def test_check_rate_limit_blocks_within_cooldown(isolated_state, capsys):
    # Write a timestamp that is only 60 seconds old
    isolated_state.write_text(json.dumps({"last_query": time.time() - 60}))
    with pytest.raises(SystemExit) as exc:
        pskreporter.check_rate_limit()
    assert exc.value.code == 0
    assert "wait" in capsys.readouterr().err.lower()


def test_check_rate_limit_allows_after_cooldown(isolated_state):
    # Write a timestamp that is older than the cooldown
    isolated_state.write_text(
        json.dumps({"last_query": time.time() - pskreporter.COOLDOWN_SECONDS - 1})
    )
    pskreporter.check_rate_limit()  # must not raise or call sys.exit


def test_check_rate_limit_warning_includes_time_remaining(isolated_state, capsys):
    isolated_state.write_text(json.dumps({"last_query": time.time() - 60}))
    with pytest.raises(SystemExit):
        pskreporter.check_rate_limit()
    err = capsys.readouterr().err
    # Should mention minutes and seconds
    assert "m " in err and "s" in err


def test_check_rate_limit_survives_corrupt_state_file(isolated_state):
    isolated_state.write_text("not valid json {{{")
    pskreporter.check_rate_limit()  # must not raise


def test_main_records_query_on_successful_fetch(isolated_state):
    with patch("sys.argv", ["pskreporter.py", "N1DQ"]):
        with patch("pskreporter.fetch_xml", return_value=SAMPLE_XML):
            pskreporter.main()
    assert isolated_state.exists()


def test_main_test_flag_skips_rate_limit(isolated_state):
    # --test exits before touching the state file
    with patch("sys.argv", ["pskreporter.py", "N1DQ", "--test"]):
        pskreporter.main()
    assert not isolated_state.exists()


def test_main_blocked_by_rate_limit(isolated_state, capsys):
    isolated_state.write_text(json.dumps({"last_query": time.time() - 30}))
    with patch("sys.argv", ["pskreporter.py", "N1DQ"]):
        with patch("pskreporter.fetch_xml", return_value=SAMPLE_XML) as mock_fetch:
            with pytest.raises(SystemExit) as exc:
                pskreporter.main()
    assert exc.value.code == 0
    mock_fetch.assert_not_called()
