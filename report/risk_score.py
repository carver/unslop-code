#!/usr/bin/env python3
"""Build report/risk-score.html: does the agents' Risk score find the spec bugs?

    python3 report/risk_score.py    # the committed page is the report; no artifact publish

Charts what addressing registry entries from the highest Risk down would find, pooled and then
problem by problem (bin/patch-risk and its curve(), from the confirmed picks in
specs/patch-entries.json). A bug is a reading patched in report/spec-patches.html, which
spec_patches.py builds from the same specs/. The stylesheet is `risk-score.template.html`.
"""
import html
import json
import math

from spec_patches import NUMBER_WORDS, ROOT, SPECS, count, patch_files, patch_risk

HERE = ROOT / "report"


CHART_W, CHART_H, LEFT, RIGHT, TOP, BOTTOM = 420, 170, 40, 14, 12, 30


def moves(points, start):
    """SVG horizontal and vertical moves from `start` through `points`, skipping the ones that go nowhere."""
    path, (last_x, last_y) = "", start
    for x, y in points:
        if (x, y) != (last_x, last_y):
            path += f"H{x}" if y == last_y else f"V{y}" if x == last_x else f"L{x},{y}"
        last_x, last_y = x, y
    return path


def step_path(points):
    """An SVG path through (x, y) points using only horizontal and vertical moves."""
    return f"M{points[0][0]},{points[0][1]}" + moves(points[1:], points[0])


def chart(title, series, points, x_domain, y_max, x_ticks, y_ticks, x_label, tips, reference=None,
          size=(CHART_W, CHART_H)):
    """One single-series line chart. `points` are (x value, y percent); `x_domain` runs left to right
    and may descend; `tips` has one hover text per point; `reference` is a second, muted line."""
    (x0, x1), (width, height) = x_domain, size
    plot_w, plot_h = width - LEFT - RIGHT, height - TOP - BOTTOM

    def sx(value):
        return round(LEFT + plot_w * (value - x0) / (x1 - x0), 1)

    def sy(value):
        return round(TOP + plot_h * (1 - value / y_max), 1)

    grid = "".join(f'<line class="grid" x1="{LEFT}" y1="{sy(t)}" x2="{width - RIGHT}" y2="{sy(t)}"/>'
                   f'<text class="tick" x="{LEFT - 6}" y="{sy(t) + 3}" text-anchor="end">{t}%</text>' for t in y_ticks)
    xs = "".join(f'<text class="tick" x="{sx(t)}" y="{height - BOTTOM + 14}" text-anchor="middle">{t}</text>'
                 for t in x_ticks)
    line = "M" + "L".join(f"{sx(x)},{sy(y)}" for x, y in points)
    extra = ""
    if reference:
        (rx0, ry0), (rx1, ry1) = reference
        extra = f'<line class="reference" x1="{sx(rx0)}" y1="{sy(ry0)}" x2="{sx(rx1)}" y2="{sy(ry1)}"/>'
    hover = json.dumps([[sx(x), sy(y), tip] for (x, y), tip in zip(points, tips, strict=True)],
                       ensure_ascii=False)
    return (f'<figure class="chart" data-points="{html.escape(hover)}"><figcaption>{html.escape(title)}</figcaption>'
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">{grid}{xs}'
            f'<text class="tick" x="{LEFT + plot_w / 2}" y="{height - 2}" text-anchor="middle">{x_label}</text>'
            f'{extra}<path class="series {series}" d="{line}"/>'
            f'<line class="cross" x1="0" y1="{TOP}" x2="0" y2="{height - BOTTOM}" visibility="hidden"/>'
            f'<circle class="dot {series}" r="4" cx="0" cy="0" visibility="hidden"/></svg>'
            f'<div class="tip" hidden></div></figure>')


def band_path(upper, lower):
    """A closed SVG path: along `upper` left to right, down to `lower`, and back along it."""
    return step_path(upper) + moves(list(reversed(lower)), upper[-1]) + "Z"


def stepped(points):
    """(x, y) levels as the corners of a step line: each value holds until the next x."""
    out = [points[0]]
    for x, y in points[1:]:
        out += [(x, out[-1][1]), (x, y)]
    return out


BANDS = (("b1", "spec bugs addressed"), ("b3", "spec bugs still unfound"), ("b2", "changes that fix no known bug"))
STACK_H = 300
LOG_TICKS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)
LOG_FLOOR = 0.5  # drawn as 0, half a decade under 1


def legend():
    return "".join(f'<span><i class="key-swatch {name}"></i>{label}</span>' for name, label in reversed(BANDS))


def stacked_chart(title, levels, x_domain, x_ticks, x_label, tips, size=(CHART_W, STACK_H), y_max=None, key=True):
    """Three stacked, stepped bands over a descending Risk axis. `levels` are (risk, [band values
    bottom to top]). `y_max` fixes the scale, for charts that are compared; `key` draws the legend."""
    (x0, x1), (width, height) = x_domain, size
    plot_w, plot_h = width - LEFT - RIGHT, height - TOP - BOTTOM
    y_max = y_max or max(sum(values) for _, values in levels)
    y_max = next(t for t in LOG_TICKS if t >= y_max)
    y_ticks = [t for t in LOG_TICKS if t <= y_max]

    def sx(value):
        return round(LEFT + plot_w * (value - x0) / (x1 - x0), 1)

    def sy(value):
        # Log scale, with LOG_FLOOR standing in for zero one step below the first decade: a few bugs
        # per run stay readable under many times as many other changes.
        span = math.log10(y_max) - math.log10(LOG_FLOOR)
        above_floor = math.log10(max(value, LOG_FLOOR)) - math.log10(LOG_FLOOR)
        return round(TOP + plot_h * (1 - above_floor / span), 1)

    grid = "".join(f'<line class="grid" x1="{LEFT}" y1="{sy(t)}" x2="{width - RIGHT}" y2="{sy(t)}"/>'
                   f'<text class="tick" x="{LEFT - 6}" y="{sy(t) + 3}" text-anchor="end">{label}</text>'
                   for t, label in [(LOG_FLOOR, "0"), *((t, f"{t:g}") for t in y_ticks)])
    grid += f'<text class="tick" x="{width - RIGHT}" y="{TOP - 3}" text-anchor="end">log scale</text>'
    xs = "".join(f'<text class="tick" x="{sx(t)}" y="{height - BOTTOM + 14}" text-anchor="middle">{t}</text>'
                 for t in x_ticks)
    edges = [[(risk, sum(values[:k])) for risk, values in levels] for k in range(len(BANDS) + 1)]
    edges = [[(sx(x), sy(y)) for x, y in stepped(edge)] for edge in edges]
    bands = "".join(f'<path class="band {name}" d="{band_path(edges[k + 1], edges[k])}"/>'
                    for k, (name, _) in enumerate(BANDS))
    hover = json.dumps([[sx(risk), sy(values[0]), tip] for (risk, values), tip in zip(levels, tips, strict=True)],
                       ensure_ascii=False)
    return (f'<figure class="chart" data-points="{html.escape(hover)}"><figcaption>{html.escape(title)}</figcaption>'
            f'{f"""<div class="key">{legend()}</div>""" if key else ""}'
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">{grid}{xs}'
            f'<text class="tick" x="{LEFT + plot_w / 2}" y="{height - 2}" text-anchor="middle">{x_label}</text>'
            f'{bands}<line class="cross" x1="0" y1="{TOP}" x2="0" y2="{height - BOTTOM}" visibility="hidden"/>'
            f'<circle class="dot b1" r="4" cx="0" cy="0" visibility="hidden"/></svg>'
            f'<div class="tip" hidden></div></figure>')


def percent(part, whole):
    return 100 * part / whole if whole else 0


def stack_series(curve):
    """(levels for stacked_chart, hover texts): per-run averages at each Risk level."""
    runs = curve["runs"]
    levels = [(r["risk"], [r["found"] / runs, r["remaining"] / runs, (r["addressed"] - r["hits"]) / runs])
              for r in curve["thresholds"]]
    tips = [f"Risk ≥ {risk}, per run: {found:.1f} bugs addressed, {left:.1f} still unfound, "
            f"{none:.1f} changes that fix no known bug" for risk, (found, left, none) in levels]
    return levels, tips


def gain_series(curve):
    """(points, hover texts, the share of bugs a whole registry finds) for the gain chart."""
    ceiling = curve["gain"][-1][1]
    tips = [f"Top {p}% of a registry by Risk: {100 * share:.0f}% of its bugs found "
            f"({p * ceiling:.0f}% in random order)" for p, share in curve["gain"]]
    return [(p, 100 * share) for p, share in curve["gain"]], tips, ceiling


def risk_axis(curves):
    """(highest Risk on the axis, its ticks), shared by every chart of `curves`."""
    high = 5 * -(-max(row["risk"] for curve in curves for row in curve["thresholds"]) // 5)
    return high, list(range(high, -1, -10))


DIFFICULTY_ORDER = ("Easy", "Medium", "Hard")
SMALL = (300, 190)


def problem_highlights(curves):
    """What stands out across the problem cards, with its figures read from the curves. '' unless the
    four problems it compares are all there."""
    if not {"rejector", "datagate", "xjq", "mvvault"} <= set(curves):
        return ""

    def top_fifth(problem):
        gain = dict(curves[problem]["gain"])
        return f"{100 * gain[20]:.0f}%", f"{20 * gain[100]:.0f}%"

    (datagate, datagate_random), (xjq, xjq_random) = top_fifth("datagate"), top_fifth("xjq")
    rejector, rejector_random = top_fifth("rejector")
    mvvault = curves["mvvault"]
    unasked = percent(mvvault["thresholds"][-1]["remaining"], mvvault["bug_instances"])
    return f"""<div class="highlights"><h3>What stands out</h3>
<p>Difficulty does not sort these. The two Easy problems sit at opposite ends: reading the top fifth of a datagate
registry finds {datagate} of its bugs ({datagate_random} in random order), and on xjq {xjq} ({xjq_random}).</p>
<p>The kind of bug sorts them better. On rejector and datagate several bugs are sentences whose own wording
pulls two ways, like rejector's "retry it up to 3 times. After the third failure". The agent sees those
coming and scores them high: the top fifth of a rejector registry finds {rejector} of its bugs, against
{rejector_random} in random order. mvvault's bugs are mostly things the spec never says, such as which HTTP client
the tests can reroute, or the exact words of an error message. A registry of ambiguous sentences has nothing to flag
there, and {unasked:.0f}% of mvvault's bug instances were never asked about by their run.</p></div>"""


def problem_section(curves, difficulty):
    """One card per problem, easiest first: the same two charts as the pooled pair, on shared scales."""
    high, x_ticks = risk_axis(curves.values())
    y_max = max(sum(values) for curve in curves.values() for _, values in stack_series(curve)[0])
    cards = []
    for problem in sorted(curves, key=lambda p: (DIFFICULTY_ORDER.index(difficulty[p]), p)):
        curve = curves[problem]
        levels, stack_tips = stack_series(curve)
        gain, gain_tips, ceiling = gain_series(curve)
        label = (f'<span class="mono">{problem}</span> {difficulty[problem]} · {count(curve["runs"], "run")} · '
                 f'{count(curve["bugs"], "bug")}')
        cards.append(
            f'<div class="card"><h3>{label}</h3>'
            + stacked_chart("Spec changes per run", levels, (high, 0), x_ticks, "clarify entries at or above this Risk",
                            stack_tips, size=SMALL, y_max=y_max, key=False)
            + chart("Bugs found, reading from the top", "s1", gain, (0, 100), 100, (0, 50, 100), (0, 50, 100),
                    "% of the registry read", gain_tips, reference=((0, 0), (100, 100 * ceiling)), size=SMALL)
            + "</div>")
    return (f'<section id="risk-by-problem"><h2 class="plain">The same, problem by problem</h2>'
            f'<p class="risk-key">Easiest first, by the benchmark\'s own difficulty label. Every left chart shares one '
            f'scale and so does every right chart, so heights compare across problems. Few runs and few bugs each: '
            f'read the shapes, not the steps.</p><div class="key shared">{legend()}</div>'
            f'<div class="cards">{"".join(cards)}</div>{problem_highlights(curves)}</section>')


def chart_section(curve):
    """The pooled charts, from bin/patch-risk's curve()."""
    rows, instances = curve["thresholds"], curve["bug_instances"]
    high, x_ticks = risk_axis([curve])
    levels, stack_tips = stack_series(curve)
    gain, gain_tips, ceiling = gain_series(curve)
    floor = rows[-1]["remaining"]
    table = "".join(f"<tr><td>{r['risk']}</td><td>{r['addressed']}</td><td>{r['hits']}</td>"
                    f"<td>{percent(r['hits'], r['addressed']):.1f}%</td><td>{r['remaining']}</td></tr>"
                    for r in rows if r["risk"] % 5 == 0 or r is rows[0])
    return f"""<section id="risk-charts">
<div class="risk-key">
<p>The spectest prompts have the agent keep a registry of every ambiguity it meets in the spec: the line, the
readings, the one it chose, and a Risk from 0 to 100, its own estimate that the hidden tests take another reading.
It writes that number before it has seen any test. Suppose a spec author clarified every entry at or above some
Risk. The charts pool {curve['runs']} runs with {curve['entries']} scored entries. A bug is one of the
{curve['bugs']} readings patched in the <a href="spec-patches.html">spec patches</a>; it counts once for each run
that read its line unpatched, whichever way the run read it: {instances} bug instances. {floor} of {instances}
stay unfound at any level, because those runs never asked the question.</p>
</div>
<div class="charts">
{stacked_chart("One run's registry: spec changes made, and what they fix", levels, (high, 0), x_ticks,
               "clarify every entry at or above this Risk", stack_tips)}
{chart("Bugs found reading a registry from its highest Risk down", "s1", gain, (0, 100), 100, (0, 25, 50, 75, 100),
       (0, 25, 50, 75, 100), "% of the run's registry read (dashed: random order)", gain_tips,
       reference=((0, 0), (100, 100 * ceiling)), size=(CHART_W, STACK_H))}
</div>
<p class="risk-key">Left: averages per run, in spec changes, on a log axis so that a few bugs stay readable
under many times as many other changes; read a band's edges, not its height. The two lower bands always add up
to the run's bugs; the top band is every other entry clarified. It is an upper bound on waste: an entry counts
as a bug only if it is one we patched, and a high-Risk entry we never patched may still be a real ambiguity
that no test probes.</p>
<details class="numbers"><summary>The numbers</summary><div class="scroll"><table>
<thead><tr><th>Risk ≥</th><th>entries addressed</th><th>a bug's entry</th><th>share</th>
<th>bug instances left</th></tr></thead>
<tbody>{table}</tbody></table></div></details>
</section>"""


SCRIPT = """<script>
document.querySelectorAll(".chart").forEach(function (fig) {
  var points = JSON.parse(fig.dataset.points), svg = fig.querySelector("svg");
  var cross = fig.querySelector(".cross"), dot = fig.querySelector(".dot"), tip = fig.querySelector(".tip");
  function show(event) {
    var box = svg.getBoundingClientRect(), x = (event.clientX - box.left) * svg.viewBox.baseVal.width / box.width;
    var best = points.reduce(function (a, b) { return Math.abs(b[0] - x) < Math.abs(a[0] - x) ? b : a; });
    cross.setAttribute("x1", best[0]); cross.setAttribute("x2", best[0]);
    dot.setAttribute("cx", best[0]); dot.setAttribute("cy", best[1]);
    cross.setAttribute("visibility", "visible"); dot.setAttribute("visibility", "visible");
    tip.textContent = best[2]; tip.hidden = false;
  }
  function hide() {
    cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hidden = true;
  }
  svg.addEventListener("pointermove", show); svg.addEventListener("pointerdown", show);
  svg.addEventListener("pointerleave", hide);
});
</script>"""


def build():
    files = patch_files()
    curves = {problem: patch_risk.curve([problem], SPECS, ROOT / "outputs") for problem in files}
    rated = (line.split(",") for line in (ROOT / "problems.csv").read_text().splitlines()[1:])
    difficulty = {name: level for name, level, *_ in rated}
    lede = (f"Scores from the spectest runs on the {NUMBER_WORDS[len(files)]} problems with "
            '<a href="spec-patches.html">spec patches</a>, set against the readings those patches settle.')
    foot = ('Source: <span class="mono">bin/patch-risk</span> over the registries in '
            '<span class="mono">outputs/</span> and the patches in <span class="mono">specs/</span>, latest version '
            'of each problem; which entry asks a patched line\'s question is in '
            '<span class="mono">specs/patch-entries.json</span>.')
    body = (f'<div class="wrap"><h1>Does the agents\' Risk score find the spec bugs?</h1><p class="lede">{lede}</p>'
            f'{chart_section(patch_risk.curve(list(files), SPECS, ROOT / "outputs"))}'
            f'{problem_section(curves, difficulty)}<p class="foot">{foot}</p></div>{SCRIPT}')
    return (HERE / "risk-score.template.html").read_text() + "</style>\n" + body + "\n"


if __name__ == "__main__":
    (HERE / "risk-score.html").write_text(build())
    print("wrote report/risk-score.html")
