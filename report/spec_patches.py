#!/usr/bin/env python3
"""Build report/spec-patches.html: every spec patch, latest version of each problem, line by line.

    python3 report/spec_patches.py    # then publish report/spec-patches.html

The patches, their hunks, the version each entered and any later rewording come from
`specs/<problem>/vN/`; dates from the patch header, else from git (the commit that added the
file, UTC). A patch's title is its header line unless `spec-patches.json` gives a shorter one; the
same file holds each problem's blurb. The stylesheet is `spec-patches.template.html`.

Behind the page's toggle, each changed line shows the Risk scores that runs gave the question
while the line was unpatched and they read it wrong (bin/patch-risk, from the confirmed picks in
specs/patch-entries.json). The build stops while any of those picks is unconfirmed.
"""
import difflib
import html
import json
import os
import re
import statistics
import subprocess
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPECS = ROOT / "specs"
NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
STRIP_WIDTH, STRIP_PAD, DOT, AXIS_GAP = 220, 12, 4.5, 9


def load_patch_risk():
    module = types.ModuleType("patch_risk")
    module.__file__ = str(ROOT / "bin" / "patch-risk")
    sys.modules.setdefault("patch_risk", module)
    exec(compile(Path(module.__file__).read_text(), module.__file__, "exec"), module.__dict__)
    return module


patch_risk = load_patch_risk()


def patch_files(specs=SPECS):
    """{problem: [patch paths of its latest version]} for every problem with tests listed, in that order."""
    problems = json.loads((specs / "patch-tests.json").read_text())
    return {p: sorted(patch_risk.latest_version(p, specs).glob("*.patch")) for p in problems}


def history(problem, patch_name, specs=SPECS):
    """(version the patch entered, version that last reworded it or None)."""
    prefix = patch_name.split("-")[0]
    versions = sorted((v for v in (specs / problem).glob("v*") if v.is_dir() and v.name[1:].isdigit()),
                      key=lambda v: int(v.name[1:]))
    diffs = [(v.name, next(v.glob(f"{prefix}-*.patch")).read_text().split("\n--- a/", 1)[-1])
             for v in versions if list(v.glob(f"{prefix}-*.patch"))]
    reworded = [name for (name, diff), (_, before) in zip(diffs[1:], diffs, strict=False) if diff != before]
    return diffs[0][0], reworded[-1] if reworded else None


def added_on(path):
    """The date the patch's own header gives (its first lines), else the UTC date of the commit that
    added the file, following renames; '' outside git."""
    header = path.read_text().split("\n--- a/")[0].splitlines()[:4]
    stated = re.search(r"\b20\d\d-\d\d-\d\d\b", "\n".join(header))
    if stated:
        return stated.group(0)
    log = subprocess.run(
        ["git", "log", "--diff-filter=A", "--follow", "--date=short-local", "--format=%ad", "--", str(path)],
        cwd=ROOT, env={**os.environ, "TZ": "UTC"}, capture_output=True, text=True, check=False,
    ).stdout.split()
    return log[-1] if log else ""


def marked(old, new):
    """The two lines as HTML with the words that changed wrapped in <mark>; either may be None."""
    if old is None or new is None:
        return (old and f'<mark class="del">{html.escape(old)}</mark>',
                new and f'<mark class="add">{html.escape(new)}</mark>')
    a, b = (re.findall(r"\s*(?:\w+|[^\w\s])|\s+", line) for line in (old, new))
    out_old, out_new = [], []
    for op, i, j, k, m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        gone, come = html.escape("".join(a[i:j])), html.escape("".join(b[k:m]))
        out_old.append(gone if op == "equal" else f'<mark class="del">{gone}</mark>' if gone else "")
        out_new.append(come if op == "equal" else f'<mark class="add">{come}</mark>' if come else "")
    return "".join(out_old), "".join(out_new)


def count(n, noun):
    return f"{n} {noun}{'' if n == 1 else 's'}"


def prompt_of(run):
    """'opus-5_2.1.251_high_min12-ABDJKMN-specv3/20260910T0934' -> 'min12-ABDJKMN'."""
    return re.sub(r"-spec(v\d+)$", "", run.split("/")[0].split("_high_")[-1])


def risk_sentence(side, problem="<problem>", slip_prompts=()):
    """What the Risk block says for one changed line, from bin/patch-risk's wrong side. `slip_prompts`
    names the prompt of each run whose entry chose the tests' reading and whose code failed them:
    a slip under a prompt that wrote tests from that entry says something a just-solve slip does not."""
    if side["unconfirmed"]:
        raise SystemExit(f"spec_patches: {side['unconfirmed']} unconfirmed pick(s); run bin/patch-risk {problem} "
                         "--candidates and record them in specs/patch-entries.json")
    scores, unasked, unscored, slips = side["scores"], side["unasked"], side["unscored"], side.get("slips", 0)
    under = f" (prompt {', '.join(slip_prompts)})" if slip_prompts else ""
    slipped = [f"{slips} more{under} chose the tests' reading in the registry and failed the tests anyway: "
               "a slip in the code, not a reading."] if slips else []
    if not side["runs"]:
        return "No run that kept a registry read this wrong."
    if not scores:
        if not unscored and not slips:
            return f"No score: {count(unasked, 'run')} read this wrong and none had asked the question."
        parts = [f"No score: {count(side['runs'], 'run')} failed the tests."]
        parts += [f"{unasked} had not asked the question."] if unasked else []
        parts += [f"{unscored} kept a registry from before the Risk line."] if unscored else []
        return " ".join(parts + [s.replace(" more", "") for s in slipped])
    median = statistics.median(scores)
    median = int(median) if median == int(median) else median
    spread = f"Risk {scores[0]}" if min(scores) == max(scores) else f"Risk {min(scores)}–{max(scores)}, median {median}"
    which = "the 1 run" if len(scores) == 1 else f"{'all' if min(scores) == max(scores) else 'the'} {len(scores)} runs"
    parts = [f"<b>{spread}</b> in {which} that read this wrong and had asked the question."]
    parts += [f"{unasked} more read it wrong without asking it."] if unasked else []
    parts += [f"{unscored} more kept a registry from before the Risk line."] if unscored else []
    return " ".join(parts + slipped)


def strip(points):
    """A dot per (score, run label) on a 0-100 axis, repeats stacked, the median ticked. '' when empty."""
    if not points:
        return ""
    points = sorted(points)
    stack = max(sum(1 for s, _ in points if s == score) for score, _ in points)
    axis_y = STRIP_PAD + (stack - 1) * AXIS_GAP + DOT
    height = axis_y + 16

    def x(score):
        return round(STRIP_PAD + (STRIP_WIDTH - 2 * STRIP_PAD) * score / 100, 1)

    seen, dots = {}, []
    for score, label in points:
        level = seen[score] = seen.get(score, -1) + 1
        dots.append(f'<circle class="strip-dot" cx="{x(score)}" cy="{round(axis_y - DOT - 1 - level * AXIS_GAP, 1)}" '
                    f'r="{DOT}"><title>Risk {score} · {html.escape(label)}</title></circle>')
    median = x(statistics.median(s for s, _ in points))
    ticks = "".join(f'<text class="strip-label" x="{x(v)}" y="{axis_y + 12}" text-anchor="middle">{v}</text>'
                    for v in (0, 50, 100))
    return (f'<svg width="{STRIP_WIDTH}" height="{round(height, 1)}" viewBox="0 0 {STRIP_WIDTH} {round(height, 1)}" '
            f'role="img" aria-label="Risk scores on a 0 to 100 scale">'
            f'<line class="strip-axis" x1="{x(0)}" y1="{axis_y}" x2="{x(100)}" y2="{axis_y}"/>'
            f'<line class="strip-median" x1="{median}" y1="{axis_y - 4}" x2="{median}" y2="{axis_y + 4}"/>'
            f'{"".join(dots)}{ticks}</svg>')


def run_label(run):
    """'opus-5_2.1.251_high_min13-ABDJKMNT/20260919T1228' -> 'min13-ABDJKMNT 20260919T1228'."""
    family, stamp = run.split("/")
    return f"{family.split('_high_')[-1]} {stamp}"


def hunk_html(sentence):
    lines = []
    pairs = max(len(sentence["removed"]), len(sentence["added"]))
    for i in range(pairs):
        old = sentence["removed"][i] if i < len(sentence["removed"]) else None
        new = sentence["added"][i] if i < len(sentence["added"]) else None
        old, new = marked(old, new)
        lines += [f'<div class="line del"><span class="sign">−</span><span>{old}</span></div>'] if old else []
        lines += [f'<div class="line add"><span class="sign">+</span><span>{new}</span></div>'] if new else []
    points = [(d["risk"], run_label(d["run"])) for d in sentence["detail"]
              if d["side"] == "wrong" and d["risk"] is not None]
    slip_prompts = [prompt_of(d["run"]) for d in sentence["detail"] if d["side"] == "wrong" and d["slip"]]
    sentence_html = risk_sentence(sentence["wrong"], sentence["problem"], slip_prompts)
    risk = (f'<div class="risk" hidden><p>{sentence_html}</p>'
            f'{strip(points)}</div>')
    return f'<div class="hunk"><div class="where">checkpoint {sentence["checkpoint"]}</div>{"".join(lines)}{risk}</div>'


def patch_html(problem, patch, sentences, title):
    number = patch.name.split("-")[0]
    entered, reworded = history(problem, patch.name)
    dated = added_on(SPECS / problem / (reworded or entered) / patch.name)
    checkpoints = sorted({s["checkpoint"] for s in sentences})
    where = f"checkpoint{'' if len(checkpoints) == 1 else 's'} {', '.join(map(str, checkpoints))}"
    meta = " · ".join(filter(None, [f"entered {entered}" + (f", reworded in {reworded}" if reworded else ""),
                                    dated, where, f'<span class="mono">{patch.name}</span>']))
    return (f'<article class="patch" id="{problem}-{number}"><div class="num mono">{number}</div><div class="body">'
            f'<h3>{html.escape(title)}</h3><p class="meta">{meta}</p>{"".join(map(hunk_html, sentences))}'
            f"</div></article>")


def header_title(patch):
    """'rejector: a failing request gets three HTTP calls in all (checkpoint 1)' -> 'A failing request gets ...'."""
    line = patch.read_text().splitlines()[0].split(":", 1)[-1].strip()
    line = re.sub(r"\s*\(checkpoint[^)]*\)$", "", line)
    return line[:1].upper() + line[1:]


RISK_KEY = """<div class="risk-key" id="risk-key" hidden>
<p>The spectest prompts have the agent keep a registry of every ambiguity it meets in the spec: the line, the
readings, the one it chose, and a Risk from 0 to 100, its own estimate that the hidden tests take another reading.
It writes that number before it has seen any test.</p>
<p>Under each changed line: the Risk on that question in the runs that read the line unpatched, chose against the
tests (the tests the patch answers failed) and had the question in their registry. Each dot is one run, the tick is
the median. Runs that failed the same tests without asking the question are counted beside it. A run whose entry
chose the tests' reading and whose code failed them anyway is a slip, not a reading: it gets no dot and is named
with its prompt. Which registry entry asks a line's question, and which way it chose, was settled by reading the
entries, one run at a time.</p>
</div>"""

SCRIPT = """<script>
(function () {
  var box = document.getElementById("show-risk");
  function apply() {
    document.querySelectorAll(".risk, #risk-key").forEach(function (el) { el.hidden = !box.checked; });
  }
  try { box.checked = localStorage.getItem("show-risk") === "1"; } catch (e) {}
  box.addEventListener("change", function () {
    try { localStorage.setItem("show-risk", box.checked ? "1" : "0"); } catch (e) {}
    apply();
  });
  apply();
})();
</script>"""


def build():
    words = json.loads((HERE / "spec-patches.json").read_text())["problems"]
    split = json.loads((ROOT / "split.json").read_text())
    files = patch_files()
    toc, sections, total = [], [], 0
    for problem, patches in files.items():
        collected = patch_risk.collect(problem, SPECS, ROOT / "outputs")
        version = patch_risk.latest_version(problem, SPECS).name
        total += len(patches)
        toc.append(f'<a href="#{problem}"><span class="mono">{problem}</span>'
                   f'<span class="count">{len(patches)} patches · {version}</span></a>')
        articles = [patch_html(problem, patch, [s for s in collected if s["patch"] == patch.name],
                               words[problem]["titles"].get(patch.name) or header_title(patch)) for patch in patches]
        blurb = html.escape(words[problem]["blurb"])
        sections.append(f'<section id="{problem}"><h2><span class="mono">{problem}</span> <span class="ver">{version}'
                        f'</span></h2><p class="blurb">{blurb}</p>{"".join(articles)}</section>')
    dev = split["dev"]
    unpatched = [p for p in dev if p not in files]
    rest = f" {' and '.join(unpatched)} {'has' if len(unpatched) == 1 else 'have'} no patches." if unpatched else ""
    lede = (f"Every change made to a benchmark spec so far: {total} patches across {NUMBER_WORDS[len(files)]} of the "
            f"{NUMBER_WORDS[len(dev)]} dev problems, each a unified diff against the spec the benchmark ships (v0). "
            "Each entry shows the changed line before and after.")
    foot = ('Source: <span class="mono">specs/&lt;problem&gt;/&lt;vN&gt;/NN-slug.patch</span> in unslop-code-bench, '
            "latest version of each problem. A version folder carries every earlier patch, so this is the full set."
            f"{rest} Risk scores: <span class=\"mono\">bin/patch-risk</span>.")
    body = (f'<div class="wrap"><h1>SCBench Spec Patches</h1><p class="lede">{lede}</p>'
            '<label class="switch" for="show-risk"><input type="checkbox" id="show-risk">'
            "<span>Show the agents' own Risk scores for each line</span></label>"
            f'{RISK_KEY}<nav class="toc">{"".join(toc)}</nav>{"".join(sections)}<p class="foot">{foot}</p></div>'
            f"{SCRIPT}")
    return (HERE / "spec-patches.template.html").read_text() + "</style>\n" + body + "\n"


if __name__ == "__main__":
    (HERE / "spec-patches.html").write_text(build())
    print("wrote report/spec-patches.html")
