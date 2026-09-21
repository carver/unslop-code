#!/usr/bin/env python3
"""Build report/quality-examples.html: code the agent wrote, marked with its scb-check hits.

    python3 report/quality_examples.py    # the committed page is the report; no artifact publish

`quality-examples.json` names the examples, hand-picked to show spectest at its best (the
candidates they came from are in notes/quality-test-dilution.md). Each has line ranges in a just-solve snapshot
and the ranges of the same logical code in a min12-ABDJKMN snapshot (clone blowups have one
side only). This script reads the code from `outputs/`, takes hit locations from scb-check
(report/scb_hits.py, cached under outputs/quality-hits/) and function complexities from the
run's symbols.jsonl, and works out every count and verdict itself; the manifest only supplies
the prose.
"""
import html
import json
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer

import scb_hits

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HITS_CACHE = ROOT / "outputs" / "quality-hits"
CC_THRESHOLD = 10  # scb-check counts a function as eroded above this cyclomatic complexity

SECTIONS = [
    ("ast", "ast-grep smells", "Each tinted line sits inside a match of one of scb-check's ast-grep rules. Across "
     "the six problems spectest's flagged share is 61% lower than just-solve's, but most of that is its test "
     "files, which are 73% of its lines and rarely match a rule. In implementation files alone the drop is 17% "
     "(bin/quality-split)."),
    ("clone", "Cloned lines", "Tinted blocks are copies of each other. just-solve clones little in its "
     "implementation files, so the pair is small."),
    ("erosion", "Erosion", "Erosion is the share of cyclomatic complexity sitting in functions above "
     f"CC {CC_THRESHOLD}. The tinted line is the def of such a function."),
    ("blowup", "Where spectest goes wrong: cloned tests", "spectest's cloned% is 2 to 33 times "
     "just-solve's on every problem, and the copies are in the tests it writes. This is a spectest run, "
     "so there is no other side to show."),
]
HIT_KIND = {"ast": "ast", "clone": "clone", "blowup": "clone"}
FEWER = {"ast": "fewer hits", "clone": "fewer cloned lines", "erosion": "lower"}
VERDICT_CLASS = {"clean": "good", **dict.fromkeys(FEWER.values(), "good"), "no better": "flat", "worse": "bad"}


@dataclass(frozen=True)
class Side:
    snapshot: Path
    segments: list
    hits: list
    functions: list


@dataclass(frozen=True)
class Line:
    number: int
    html: str
    flagged: bool


@dataclass(frozen=True)
class Segment:
    file: str
    label: str
    lines: list


@dataclass(frozen=True)
class Summary:
    count: int  # ast: hits, clone: cloned lines, erosion: highest CC
    items: list  # ast: (rule, hits), erosion: (function, CC), clone: empty
    flagged: int = 0  # lines tinted in the segments
    copies: int = 0  # clone: instances in the largest group, wherever they sit


def overlaps(span, segment):
    return span["file"] == segment["file"] and span["start"] <= segment["end"] and span["end"] >= segment["start"]


def hits_in(side, category):
    kind = HIT_KIND[category]
    return [h for h in side.hits if h["kind"] == kind
            and any(overlaps(span, seg) for span in h["spans"] for seg in side.segments)]


def functions_in(side):
    return [f for f in side.functions
            if any(f["file_path"] == seg["file"] and seg["start"] <= f["start"] <= seg["end"] for seg in side.segments)]


def flagged_numbers(side, category, segment):
    if category == "erosion":
        return {f["start"] for f in functions_in(side) if f["complexity"] > CC_THRESHOLD}
    return {n for h in hits_in(side, category) for span in h["spans"] if overlaps(span, segment)
            for n in range(span["start"], span["end"] + 1)}


@cache
def highlighted_lines(path):
    lexer = PythonLexer(stripnl=False, stripall=False, ensurenl=False)
    return highlight(Path(path).read_text(), lexer, HtmlFormatter(nowrap=True)).split("\n")


def annotate(side, category):
    segments = []
    for seg in side.segments:
        source = highlighted_lines(side.snapshot / seg["file"])
        if not 1 <= seg["start"] <= seg["end"] <= len(source):
            raise ValueError(f"{side.snapshot / seg['file']}: no lines {seg['start']}-{seg['end']}")
        flagged = flagged_numbers(side, category, seg)
        lines = [Line(n, source[n - 1], n in flagged) for n in range(seg["start"], seg["end"] + 1)]
        segments.append(Segment(seg["file"], seg.get("label", ""), lines))
    return segments


def summarize(side, category):
    if category == "erosion":
        items = [(f["name"], f["complexity"]) for f in sorted(functions_in(side), key=lambda f: f["start"])]
        return Summary(max((cc for _, cc in items), default=0), items)
    flagged = sum(len(flagged_numbers(side, category, seg)) for seg in side.segments)
    if category == "ast":
        hits = hits_in(side, category)
        return Summary(len(hits), Counter(h["rule"] for h in hits).most_common(), flagged)
    copies = max((len(h["spans"]) for h in hits_in(side, category)), default=0)
    return Summary(flagged, [], flagged, copies)


def verdict(category, before, after):
    floor = CC_THRESHOLD if category == "erosion" else 0
    if after <= floor:
        return "clean"
    if after < before:
        return FEWER[category]
    return "no better" if after == before else "worse"


def load_functions(snapshot):
    symbols = Path(snapshot).parent / "quality_analysis" / "symbols.jsonl"
    rows = [json.loads(line) for line in symbols.read_text().splitlines()] if symbols.exists() else []
    return [r for r in rows if r["type"] in ("function", "method")]


def load_cached_hits(snapshot):
    return scb_hits.load(snapshot, HITS_CACHE)


def esc(text):
    return html.escape(str(text), quote=True)


def stat_text(summary, category, shown):
    if category == "erosion":
        return f"highest CC {summary.count}"
    if category == "ast":
        return f"{summary.count} ast-grep hit{'' if summary.count == 1 else 's'} on {summary.flagged} of {shown} lines"
    cloned = f"{summary.flagged} of {shown} lines cloned"
    return f"{cloned}, largest group has {summary.copies} copies" if category == "blowup" else cloned


def render_code(segments):
    out = []
    for seg in segments:
        first, last = seg.lines[0].number, seg.lines[-1].number
        label = f" &middot; {esc(seg.label)}" if seg.label else ""
        out.append(f'<div class="seghead mono">{esc(seg.file)}:{first}-{last}{label}</div>')
        rows = "".join(f'<div class="ln{" flag" if line.flagged else ""}"><span class="no">{line.number}</span>'
                       f'<span class="src">{line.html or " "}</span></div>' for line in seg.lines)
        out.append(f'<div class="code"><div class="lines">{rows}</div></div>')
    return "".join(out)


def render_items(summary, category):
    if not summary.items:
        return ""
    if category == "erosion":
        chips = [f'<li class="{"over" if cc > CC_THRESHOLD else ""}"><span class="mono">{esc(name)}</span> CC {cc}</li>'
                 for name, cc in summary.items]
    else:
        chips = [f'<li class="over"><span class="mono">{esc(rule)}</span>{f" &times;{n}" if n > 1 else ""}</li>'
                 for rule, n in summary.items]
    return f'<ul class="items">{"".join(chips)}</ul>'


def render_pane(side, category, css, prompt, run, pane_id="", hidden=False, note=""):
    summary = summarize(side, category)
    shown = sum(seg["end"] - seg["start"] + 1 for seg in side.segments)
    attrs = (f' id="{pane_id}"' if pane_id else "") + (" hidden" if hidden else "")
    return (f'<section class="pane {css}"{attrs}><div class="panehead"><b>{prompt}</b>'
            f'<span class="mono run">{esc(run)}</span>'
            f'<span class="stat">{stat_text(summary, category, shown)}</span></div>'
            f'{render_code(annotate(side, category))}{render_items(summary, category)}{note}</section>')


def render_example(example, side_for):
    category, ident = example["category"], esc(example["id"])
    before = side_for(example["before"])
    head = f'<header><h3>{esc(example["title"])}</h3><span class="chip">{esc(example["problem"])}</span></header>'
    why = f'<p class="why">{esc(example["what_is_wrong"])}</p>'
    if "after" not in example:
        pane = render_pane(before, category, "min", "spectest", example["before"]["run"])
        return f'<article class="ex" id="{ident}">{head}{why}<div class="panes">{pane}</div></article>'
    after = side_for(example["after"])
    result = verdict(category, summarize(before, category).count, summarize(after, category).count)
    note = (f'<p class="changed"><span class="verdict {VERDICT_CLASS[result]}">{result}</span> '
            f'{esc(example["what_changed"])}</p>')
    switch = (f'<button type="button" class="switch" role="switch" aria-checked="false" aria-controls="{ident}-after">'
              f'<span class="track"><span class="thumb"></span></span>Show the spectest version</button>')
    panes = (render_pane(before, category, "js", "just-solve", example["before"]["run"])
             + render_pane(after, category, "min", "spectest", example["after"]["run"], f"{ident}-after", True, note))
    return f'<article class="ex" id="{ident}">{head}{why}{switch}<div class="panes">{panes}</div></article>'


def render_examples(manifest, load_hits=load_cached_hits, load_functions=load_functions):
    @cache
    def run_data(run):
        snapshot = Path(manifest["runs"][run])
        snapshot = snapshot if snapshot.is_absolute() else ROOT / snapshot
        return snapshot, load_hits(snapshot), load_functions(snapshot)

    def side_for(spec):
        snapshot, hits, functions = run_data(spec["run"])
        return Side(snapshot, spec["segments"], hits, functions)

    out = []
    for category, title, blurb in SECTIONS:
        examples = [e for e in manifest["examples"] if e["category"] == category]
        if examples:
            body = "".join(render_example(e, side_for) for e in examples)
            intro = f'<h2>{title}</h2><p class="note">{blurb}</p>'
            out.append(f'<section class="group" id="{category}">{intro}{body}</section>')
    return "".join(out)


def build():
    manifest = json.loads((HERE / "quality-examples.json").read_text())
    template = (HERE / "quality-examples.template.html").read_text()
    assert template.count("__EXAMPLES__") == 1
    out = HERE / "quality-examples.html"
    out.write_text(template.replace("__EXAMPLES__", render_examples(manifest)))
    return out


if __name__ == "__main__":
    print(build())
