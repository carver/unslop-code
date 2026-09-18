"""Per-hit locations from scb-check.

scb-check's JSON report only has totals; the human report prints every hit with its
file and lines. `load` runs the pinned checker inside a snapshot, keeps the text in a cache
directory and returns the hits:

    {"kind": "ast" | "wrapper" | "erosion" | "cog_erosion" | "clone", "rule": ..., "message": ...,
     "spans": [{"file", "start", "end"}], "test": bool, "complexity": int (erosion only)}

Clones carry one span per instance. `test` is true when every span sits in a test file.
"""
import hashlib
import re
import subprocess
from pathlib import Path

SCB_CHECK_VERSION = "0.1.3"  # the version the harness scores with
KINDS = {"warning": "ast", "trivial-wrapper": "wrapper", "erosion": "erosion", "cog_erosion": "cog_erosion",
         "duplicate-structure": "clone"}

HEADER = re.compile(rf"^(?P<kind>{'|'.join(KINDS)})(\[(?P<rule>[\w-]+)\])?: (?P<message>.*)$")
LOCATION = re.compile(r"^\s+┌─ (?P<path>\S+?):(?P<line>\d+)")
SOURCE_LINE = re.compile(r"^\s*(?P<number>\d+) │")
COMPLEXITY = re.compile(r"^\s+= complexity: (?P<cc>\d+)")
TEST_FILE = re.compile(r"(^|/)((tests?|testing)/|test[^/]*\.py$|conftest\.py$|[^/]*_test\.py$)")


def is_test_file(path):
    return bool(TEST_FILE.search(path))


def parse_report(text):
    hits, hit, span = [], None, None
    for line in text.splitlines():
        if m := HEADER.match(line):
            hit = {"kind": KINDS[m["kind"]], "rule": m["rule"] or m["kind"], "message": m["message"], "spans": []}
            hits.append(hit)
            span = None
        elif hit is None:
            continue
        elif m := LOCATION.match(line):
            span = {"file": m["path"], "start": int(m["line"]), "end": int(m["line"])}
            hit["spans"].append(span)
        elif (m := SOURCE_LINE.match(line)) and span:
            span["end"] = max(span["end"], int(m["number"]))
        elif m := COMPLEXITY.match(line):
            hit["complexity"] = int(m["cc"])
    for hit in hits:
        if hit["kind"] in ("ast", "wrapper"):  # the report prints one line of context after the match
            for span in hit["spans"]:
                span["end"] = max(span["start"], span["end"] - 1)
        hit["test"] = all(is_test_file(span["file"]) for span in hit["spans"])
    return hits


def run_scb_check(snapshot):
    # Run inside the snapshot so the report names files relative to it.
    command = ["uvx", f"scb-check=={SCB_CHECK_VERSION}", "check", "--include-all", "."]
    return subprocess.run(command, cwd=snapshot, capture_output=True, text=True, check=True).stdout


def load(snapshot, cache_dir, check=run_scb_check):
    key = hashlib.sha256(f"{SCB_CHECK_VERSION}:{snapshot}".encode()).hexdigest()[:16]
    cached = Path(cache_dir) / f"{key}.txt"
    if not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(check(snapshot))
    return parse_report(cached.read_text())
