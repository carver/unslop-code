#!/usr/bin/env python3
"""Build report/uplift-grid.html: the template with `bin/grid --json` embedded.

    python3 report/uplift_grid.py    # then publish report/uplift-grid.html

The page is self-contained: the grid data sits in a script constant, the charts are inline
SVG drawn by the page, no library. The implementation-against-tests table comes from
`bin/quality-split --json` and is written into the page as HTML; its human row is the mean
over report/human-split.json, the same tool run with --tree on checkouts of the paper's
Major-tier repositories (notes/quality-test-dilution.md says how). Re-run after any run
lands so the page and notes/results.md agree.
"""
import json
import pathlib
import statistics
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PROMPT_LABELS = {"just-solve": "just-solve", "min12-ABDJKMN": "spectest"}
SCORES = (("ast", "ast-grep"), ("erosion", "erosion"), ("cloned", "cloned"))
PARTS = (("impl", "impl"), ("test", "tests"), ("all", "all"))


def tool_json(name):
    return subprocess.run([ROOT / "bin" / name, "--json"], capture_output=True, text=True, check=True).stdout


def drop(before, after):
    return f"{round(100 * (1 - after / before))}%"


def human_mean(repos):
    """One row for the human panel: each score is the mean of the per-repository values, as the paper reports it."""
    row = {part: {score: statistics.mean(r[part][score] for r in repos) for score, _ in SCORES} for part, _ in PARTS}
    return row | {"test_share": statistics.mean(r["test_share"] for r in repos)}


def split_section(rows, repos):
    """The pooled row of each prompt and the human mean as a table, and the reading of it."""
    pooled = {r["prompt"]: r for r in rows if r["name"] == "ALL"}
    base, new, human = pooled["just-solve"], pooled["min12-ABDJKMN"], human_mean(repos)
    head = "".join(f'<th colspan="3">{label}</th>' for _, label in SCORES)
    sub = "".join(f"<th>{label}</th>" for _ in SCORES for _, label in PARTS)
    body = ""
    for prompt, row in pooled.items():
        cells = "".join(f'<td class="num">{row[part][score]:.3f}</td>' for score, _ in SCORES for part, _ in PARTS)
        body += (f'<tr><td>{PROMPT_LABELS[prompt]}</td><td class="num">{row["impl"]["loc"]:,}</td>'
                 f'<td class="num">{row["test"]["loc"]:,}</td><td class="num">{row["test_share"]:.0%}</td>{cells}</tr>')
    cells = "".join(f'<td class="num">{human[part][score]:.3f}</td>' for score, _ in SCORES for part, _ in PARTS)
    body += (f'<tr><td>human, {len(repos)} repositories</td><td class="num">-</td><td class="num">-</td>'
             f'<td class="num">{human["test_share"]:.0%}</td>{cells}</tr>')
    table = (f'<div class="tablewrap"><table><thead><tr><th rowspan="2">prompt</th><th rowspan="2">impl LOC</th>'
             f'<th rowspan="2">test LOC</th><th rowspan="2">test share</th>{head}</tr><tr>{sub}</tr></thead>'
             f"<tbody>{body}</tbody></table></div>")
    note = (f'<p class="note" style="margin-top:10px">scb-check scores the test files along with the '
            f'implementation, and spectest writes '
            f'{new["test"]["loc"] / base["test"]["loc"]:.1f} times the test code. Over the whole snapshot its '
            f'ast-grep share falls {drop(base["all"]["ast"], new["all"]["ast"])}; in implementation files alone '
            f'it falls {drop(base["impl"]["ast"], new["impl"]["ast"])}. spectest also writes '
            f'{drop(base["impl"]["loc"], new["impl"]["loc"])} less implementation, so <b>the count of flagged '
            f'implementation lines falls {drop(base["impl"]["ast_lines"], new["impl"]["ast_lines"])}</b> '
            f'({base["impl"]["ast_lines"]:,} to {new["impl"]["ast_lines"]:,}). Erosion has the same shape with more '
            f'left over: down {drop(base["all"]["erosion"], new["all"]["erosion"])} over the whole snapshot and '
            f'{drop(base["impl"]["erosion"], new["impl"]["erosion"])} in implementation files. The rise in cloned '
            f'lines is all in the tests; implementation clones fall from {base["impl"]["cloned"]:.3f} to '
            f'{new["impl"]["cloned"]:.3f}.</p>')
    note += (f'<p class="note" style="margin-top:8px">The human row is the mean over {len(repos)} of the paper\'s '
             f'Major-tier repositories (over 10k stars) at HEAD, split by the same tool. Humans write tests too, '
             f'{human["test_share"]:.0%} of their lines, so their whole-repository figures are diluted the same way. '
             f'Implementation against implementation, spectest\'s ast-grep share is '
             f'{new["impl"]["ast"] / human["impl"]["ast"]:.1f} times the human one, its erosion is '
             f'{new["impl"]["erosion"]:.2f} against {human["impl"]["erosion"]:.2f}, and its cloned share is '
             f'{new["impl"]["cloned"]:.3f} against {human["impl"]["cloned"]:.3f}. Its tests are cloned '
             f'{new["test"]["cloned"] / human["test"]["cloned"]:.1f} times as much as '
             f'human tests. The human bars in the headline are this same rerun. The paper\'s own table gives '
             f'0.10 for ast-grep, which this scb-check version does not reproduce ({human["all"]["ast"]:.3f} here); '
             f'its erosion mean, 0.31, it does ({human["all"]["erosion"]:.2f}).</p>')
    return table + note


def build():
    template = (HERE / "uplift-grid.template.html").read_text()
    assert template.count("__DATA__") == 1
    assert template.count("__SPLIT__") == 1
    page = template.replace("__DATA__", tool_json("grid").strip())
    repos = json.loads((HERE / "human-split.json").read_text())
    page = page.replace("__SPLIT__", split_section(json.loads(tool_json("quality-split")), repos))
    out = HERE / "uplift-grid.html"
    out.write_text(page)
    return out


if __name__ == "__main__":
    print(build())
