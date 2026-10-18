"""Tests for the queue-total formatting helpers in base.html.

These are plain JavaScript functions shared by the Home and Queue pages, so the
only honest way to test them is to run them. The functions are lifted straight
out of the template (no copy to drift out of date) and executed with Node or
Deno. Skipped when neither is installed.
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

BASE_HTML = Path(__file__).resolve().parents[2] / "pikaraoke" / "templates" / "base.html"

# Where the helpers start and stop inside the template's inline script.
START = "// Whole seconds as"
END = "function showNotification"

RUNTIME = shutil.which("node") or shutil.which("deno")
pytestmark = pytest.mark.skipif(RUNTIME is None, reason="needs Node or Deno to run the helpers")

# (function, argument as JavaScript source, expected result)
CASES = [
    # formatDuration: whole seconds as 42m 18s
    ("formatDuration", "0", "0s"),
    ("formatDuration", "1", "1s"),
    ("formatDuration", "45", "45s"),
    ("formatDuration", "59", "59s"),
    ("formatDuration", "60", "1m 00s"),
    ("formatDuration", "61", "1m 01s"),
    ("formatDuration", "599", "9m 59s"),
    ("formatDuration", "600", "10m 00s"),
    ("formatDuration", "2538", "42m 18s"),
    ("formatDuration", "3599", "59m 59s"),
    ("formatDuration", "3600", "1h 00m 00s"),
    ("formatDuration", "3661", "1h 01m 01s"),
    ("formatDuration", "5681", "1h 34m 41s"),
    ("formatDuration", "36000", "10h 00m 00s"),
    ("formatDuration", "-5", "0s"),
    ("formatDuration", "NaN", "0s"),
    ("formatDuration", "null", "0s"),
    ("formatDuration", "undefined", "0s"),
    ("formatDuration", "'abc'", "0s"),
    ("formatDuration", "'120'", "2m 00s"),
    ("formatDuration", "59.6", "1m 00s"),
    ("formatDuration", "2537.5", "42m 18s"),
    # formatSongLength: one song as 4:34
    ("formatSongLength", "0", "0:00"),
    ("formatSongLength", "5", "0:05"),
    ("formatSongLength", "59", "0:59"),
    ("formatSongLength", "60", "1:00"),
    ("formatSongLength", "274", "4:34"),
    ("formatSongLength", "415", "6:55"),
    ("formatSongLength", "599", "9:59"),
    ("formatSongLength", "3600", "1:00:00"),
    ("formatSongLength", "3723", "1:02:03"),
    ("formatSongLength", "-1", "0:00"),
    ("formatSongLength", "null", "0:00"),
    # summarizeQueue: what a queue adds up to
    ("summarizeQueue", "[]", {"songs": 0, "seconds": 0, "unknown": 0}),
    (
        "summarizeQueue",
        "[{duration:100},{duration:200}]",
        {"songs": 2, "seconds": 300, "unknown": 0},
    ),
    (
        "summarizeQueue",
        "[{duration:100},{duration:null}]",
        {"songs": 2, "seconds": 100, "unknown": 1},
    ),
    ("summarizeQueue", "[{duration:100},{}]", {"songs": 2, "seconds": 100, "unknown": 1}),
    ("summarizeQueue", "[{duration:0}]", {"songs": 1, "seconds": 0, "unknown": 1}),
    # A negative length is nonsense: it must not be subtracted from the total.
    (
        "summarizeQueue",
        "[{duration:100},{duration:-50}]",
        {"songs": 2, "seconds": 100, "unknown": 1},
    ),
    # A string is not a length: only real numbers are trusted.
    ("summarizeQueue", "[{duration:'100'}]", {"songs": 1, "seconds": 0, "unknown": 1}),
    # formatQueueTotal: the headline figure
    ("formatQueueTotal", "{seconds:2538,unknown:0}", "42m 18s"),
    ("formatQueueTotal", "{seconds:2538,unknown:2}", "42m 18s+"),
    ("formatQueueTotal", "{seconds:0,unknown:3}", ""),
    ("formatQueueTotal", "{seconds:5681,unknown:0}", "1h 34m 41s"),
    # formatSongCount
    ("formatSongCount", "0", "0 songs"),
    ("formatSongCount", "1", "1 song"),
    ("formatSongCount", "2", "2 songs"),
    ("formatSongCount", "10", "10 songs"),
]


def _helpers_from_template() -> str:
    source = BASE_HTML.read_text(encoding="utf-8")
    start, end = source.index(START), source.index(END)
    assert start < end, "the helpers moved: update START/END in this test"
    return source[start:end]


@pytest.fixture(scope="module")
def results() -> list:
    """Run every case in one go, since starting a JS engine per case is slow."""
    cases = json.dumps([{"fn": fn, "arg": arg} for fn, arg, _ in CASES])
    script = f"""
const window = {{ translations: {{ songCountOne: "1 song", songCountMany: "SONG_COUNT songs" }} }};
{_helpers_from_template()}
const fns = {{ formatDuration, formatSongLength, summarizeQueue, formatQueueTotal, formatSongCount }};
const cases = {cases};
const out = cases.map((c) => fns[c.fn](new Function("return " + c.arg)()));
console.log(JSON.stringify(out));
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "check.js"
        path.write_text(script, encoding="utf-8")
        command = (
            [RUNTIME, "run", str(path)]
            if "deno" in Path(RUNTIME).name.lower()
            else [RUNTIME, str(path)]
        )
        done = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("index", range(len(CASES)), ids=[f"{fn}({arg})" for fn, arg, _ in CASES])
def test_helper(results, index):
    _fn, _arg, expected = CASES[index]
    assert results[index] == expected


def test_the_helpers_are_still_where_the_test_expects():
    """If these move, the tests would silently check nothing."""
    text = _helpers_from_template()
    for name in (
        "formatDuration",
        "formatSongLength",
        "summarizeQueue",
        "formatQueueTotal",
        "formatSongCount",
    ):
        assert re.search(rf"function {name}\(", text), name
