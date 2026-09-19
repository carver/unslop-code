"""Hidden-test misses bucketed by how they failed, and matched against other runs.

A cause outside the prompt (a fixture that only works with one HTTP library, a port clash, a
timeout) fails several tests the same way, and fails them again in other runs. `signature`
reduces a pytest crash message to the part that repeats: its first line with numbers, addresses
and temporary paths blanked, plus the exception classes named further down (the ones in the
captured stderr). `run_misses` reads a run's `checkpoint_*/evaluation/report.json`;
`shared` finds the same test failing the same way in other runs of the problem.
"""
import json
import re

TMP_PATH = re.compile(r"/tmp/pytest-of-\w+/pytest-\d+/[\w.-]+/")
ADDRESS = re.compile(r"0x[0-9a-fA-F]+")
NUMBER = re.compile(r"\d+(?:\.\d+)*")
EXCEPTION = re.compile(r"\b[A-Z]\w*(?:Error|Exception|Expired|Timeout|Interrupt)\b")
NODE_PREFIX = ".evaluation_tests/"
MISSED = ("failed", "error")
STAGES = ("setup", "call", "teardown")
FIRST_LINE_LIMIT = 160
RUNS_NAMED = 4


def signature(message):
    first, _, rest = message.strip().partition("\n")
    first = NUMBER.sub("N", ADDRESS.sub("<addr>", TMP_PATH.sub("<tmp>/", first)))
    if len(first) > FIRST_LINE_LIMIT:
        first = first[:FIRST_LINE_LIMIT] + "…"
    named = [name for name in dict.fromkeys(EXCEPTION.findall(rest)) if name not in first and name != "AssertionError"]
    return f"{first} [{', '.join(named)}]" if named else first


def crash_message(test):
    return next((test[stage]["crash"]["message"] for stage in STAGES if test.get(stage, {}).get("crash")), "")


def run_misses(problem_dir):
    """{test: signature} over every checkpoint of a run; a test that fails more than once keeps its last."""
    misses = {}
    reports = problem_dir.glob("checkpoint_*/evaluation/report.json")
    for report in sorted(reports, key=lambda p: int(p.parent.parent.name.rsplit("_", 1)[1])):
        for test in json.loads(report.read_text()).get("tests", []):
            if test["outcome"] in MISSED:
                misses[test["nodeid"].removeprefix(NODE_PREFIX)] = signature(crash_message(test))
    return misses


def buckets(misses):
    """[(signature, [tests])], the signature with the most tests first."""
    grouped = {}
    for test, sig in sorted(misses.items()):
        grouped.setdefault(sig, []).append(test)
    return sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))


def shared(mine, others):
    """{signature: [(other run, tests it misses the same way)]} for `others` of {label: misses}, the
    run that shares the most tests first."""
    found = {}
    for label, theirs in others.items():
        counts = {}
        for test, sig in mine.items():
            if theirs.get(test) == sig:
                counts[sig] = counts.get(sig, 0) + 1
        for sig, count in counts.items():
            found.setdefault(sig, []).append((label, count))
    return {sig: sorted(runs, key=lambda run: (-run[1], run[0])) for sig, runs in found.items()}


def render(mine, others):
    if not mine:
        return "No misses."
    also = shared(mine, others)
    lines = []
    for sig, tests in buckets(mine):
        lines.append(f"{len(tests)} test{'s' if len(tests) > 1 else ''}: {sig}")
        lines += [f"    {test}" for test in tests]
        if sig in also:
            runs = ", ".join(f"{label} ({count} of {len(tests)})" for label, count in also[sig][:RUNS_NAMED])
            more = len(also[sig]) - RUNS_NAMED
            lines.append(f"    same tests, same failure in: {runs}" + (f" and {more} more" if more > 0 else ""))
    return "\n".join(lines)
