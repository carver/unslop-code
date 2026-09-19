"""scb-check scores of a tree's implementation files and test files apart.

scb-check scores every Python file it finds, tests included. `split_reports` copies the
implementation files and the test files (scb_hits.is_test_file) of a tree into two scratch
trees, runs the pinned checker on each and on the two together, and caches the counts the
scores are made of: {"impl" | "test" | "all": {total_loc, ast_grep_flagged_loc, clone_loc,
verbosity_flagged_loc, high_cc_mass, total_mass}}. ast%, cloned% and verbosity are flagged
lines over LOC (verbosity counts a line once however many of ast-grep, the clone detector and
the trivial-wrapper check flag it), erosion is high-complexity mass over total mass; `scores`
does the division. A cached report missing a count (written before that count was kept) is
recomputed.
"""
import hashlib
import json
import pathlib
import shutil
import subprocess
import tempfile

import scb_hits

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "outputs" / "quality-hits" / "split"
PARTS = ("impl", "test", "all")
SKIPPED_DIRS = {".git", "docs", "doc", ".venv", "venv", "env", "__pycache__", "node_modules", "site-packages", ".tox",
                "build", "dist"}
SUMMED = ("total_loc", "ast_grep_flagged_loc", "clone_loc", "verbosity_flagged_loc", "high_cc_mass", "total_mass")


def part_of(path):
    return "test" if scb_hits.is_test_file(str(path)) else "impl"


def python_files(tree):
    return sorted(p.relative_to(tree) for p in tree.rglob("*.py")
                  if p.is_file() and not SKIPPED_DIRS.intersection(p.relative_to(tree).parts))


def scb_report(directory):
    command = ["uvx", f"scb-check=={scb_hits.SCB_CHECK_VERSION}", "check", "--report", "--include-all", "."]
    return json.loads(subprocess.run(command, cwd=directory, capture_output=True, text=True, check=True).stdout)


def part_report(tree, part, check=scb_report):
    files = [f for f in python_files(tree) if part == "all" or part_of(f) == part]
    if not files:
        return dict.fromkeys(SUMMED, 0)
    with tempfile.TemporaryDirectory() as scratch:
        for f in files:
            target = pathlib.Path(scratch) / f
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tree / f, target)
        report = check(scratch)
    return {k: report[k] for k in SUMMED}


def split_reports(tree, cache=CACHE, check=scb_report):
    tree = pathlib.Path(tree)
    key = hashlib.sha256(f"{scb_hits.SCB_CHECK_VERSION}:{tree.resolve()}".encode()).hexdigest()[:16]
    cached = pathlib.Path(cache) / f"{key}.json"
    if not (cached.exists() and complete(json.loads(cached.read_text()))):
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps({part: part_report(tree, part, check) for part in PARTS}))
    return json.loads(cached.read_text())


def complete(reports):
    """Whether a cached split carries every count the scores need."""
    return all(k in reports.get(part, {}) for part in PARTS for k in SUMMED)


def ratio(top, bottom):
    return top / bottom if bottom else None


def scores(counts):
    """ast%, cloned%, verbosity and erosion from one part's counts, None where the part has no code."""
    return {"ast": ratio(counts["ast_grep_flagged_loc"], counts["total_loc"]),
            "cloned": ratio(counts["clone_loc"], counts["total_loc"]),
            "verbosity": ratio(counts["verbosity_flagged_loc"], counts["total_loc"]),
            "erosion": ratio(counts["high_cc_mass"], counts["total_mass"])}
