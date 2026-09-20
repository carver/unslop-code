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
PROMPT_LABELS = {"just-solve": "just-solve", "anti_slop": "anti-slop", "min12-ABDJKMN": "spectest",
                 "min13-ABDJKMNT": "spectest+antislop"}
SCORES = (("ast", "ast-grep"), ("erosion", "erosion"), ("cloned", "cloned"))
PARTS = (("impl", "impl"), ("test", "tests"), ("all", "all"))


def tool_json(name, *args):
    return subprocess.run([ROOT / "bin" / name, "--json", *args], capture_output=True, text=True, check=True).stdout


def drop(before, after):
    return f"{round(100 * (1 - after / before))}%"


def human_mean(repos):
    """One row for the human panel: each score is the mean of the per-repository values, as the paper reports it."""
    row = {part: {score: statistics.mean(r[part][score] for r in repos) for score, _ in SCORES} for part, _ in PARTS}
    return row | {"test_share": statistics.mean(r["test_share"] for r in repos)}


def problem_rows(rows, prompt):
    return [r for r in rows if r["prompt"] == prompt and r["name"] != "ALL"]


def prompt_row(rows, prompt):
    """A prompt's table row. Each score, the test share included, is the mean of the per-problem
    values, every problem counting once the way every repository does in the human row; pooling
    the runs instead lets the largest problem set the figure. The line counts are per run, so a
    prompt with one run per problem compares with one that has two."""
    problems = problem_rows(rows, prompt)
    total = next(r for r in rows if r["prompt"] == prompt and r["name"] == "ALL")
    row = {"runs": total["runs"], "test_share": statistics.mean(r["test_share"] for r in problems)}
    for part, _ in PARTS:
        counts = {key: round(total[part][key] / total["runs"]) for key in ("loc", "ast_lines")}
        means = {score: statistics.mean(r[part][score] for r in problems if r[part][score] is not None)
                 for score, _ in SCORES}
        row[part] = counts | means
    return row


def test_share_panel(rows, repos):
    """What the test-share card draws: per prompt the share of final-checkpoint lines that sit in
    test files, problem by problem and their mean, and the same over the human repositories with
    the lowest and highest named."""
    prompts = {}
    for prompt in PROMPT_LABELS:
        shares = {r["name"]: r["test_share"] for r in problem_rows(rows, prompt)}
        if shares:
            prompts[prompt] = {"mean": statistics.mean(shares.values()), "problems": shares}
    low, high = (pick(repos, key=lambda r: r["test_share"]) for pick in (min, max))
    human = {"n": len(repos), "mean": statistics.mean(r["test_share"] for r in repos),
             "min": {"repo": low["name"], "value": low["test_share"]},
             "max": {"repo": high["name"], "value": high["test_share"]}}
    return {"prompts": prompts, "human": human}


def cloned_sentence(base, new):
    """Cloned lines against the baseline: a rise that the implementation does not share is the tests'."""
    clones = f'implementation clones go from {base["impl"]["cloned"]:.3f} to {new["impl"]["cloned"]:.3f}'
    if new["all"]["cloned"] > base["all"]["cloned"] and new["impl"]["cloned"] <= base["impl"]["cloned"]:
        return f"The rise in cloned lines is all in the tests; {clones}."
    return (f'Cloned lines go from {base["all"]["cloned"]:.3f} to {new["all"]["cloned"]:.3f} over the whole '
            f"snapshot; {clones}.")


def split_section(rows, repos):
    """The row of each prompt that has runs and the human mean as a table, and the reading of it:
    a paragraph per prompt after the baseline, then the human paragraph."""
    have = {r["prompt"] for r in rows}
    pooled = {prompt: prompt_row(rows, prompt) for prompt in PROMPT_LABELS if prompt in have}
    base, human = pooled["just-solve"], human_mean(repos)
    others = [prompt for prompt in pooled if prompt != "just-solve"]
    head = "".join(f'<th colspan="3">{label}</th>' for _, label in SCORES)
    sub = "".join(f"<th>{label}</th>" for _ in SCORES for _, label in PARTS)
    body = ""
    for prompt, row in pooled.items():
        cells = "".join(f'<td class="num">{row[part][score]:.3f}</td>' for score, _ in SCORES for part, _ in PARTS)
        body += (f'<tr><td>{PROMPT_LABELS[prompt]}</td><td class="num">{row["runs"]}</td>'
                 f'<td class="num">{row["impl"]["loc"]:,}</td>'
                 f'<td class="num">{row["test"]["loc"]:,}</td><td class="num">{row["test_share"]:.0%}</td>{cells}</tr>')
    cells = "".join(f'<td class="num">{human[part][score]:.3f}</td>' for score, _ in SCORES for part, _ in PARTS)
    body += (f'<tr><td>human, {len(repos)} repositories</td><td class="num">-</td><td class="num">-</td>'
             f'<td class="num">-</td>'
             f'<td class="num">{human["test_share"]:.0%}</td>{cells}</tr>')
    table = (f'<div class="tablewrap"><table><thead><tr><th rowspan="2">prompt</th><th rowspan="2">runs</th>'
             f'<th rowspan="2">impl LOC per run</th><th rowspan="2">test LOC per run</th>'
             f'<th rowspan="2">test share</th>{head}</tr><tr>{sub}</tr></thead>'
             f"<tbody>{body}</tbody></table></div>")
    note = ""
    for prompt in others:
        new, name = pooled[prompt], PROMPT_LABELS[prompt]
        lead = ("scb-check scores the test files along with the implementation, and " if prompt == others[0]
                else "")
        note += (f'<p class="note" style="margin-top:{10 if prompt == others[0] else 8}px">{lead}{name} writes '
                 f'{new["test"]["loc"] / base["test"]["loc"]:.1f} times the test code. Over the whole snapshot its '
                 f'ast-grep share falls {drop(base["all"]["ast"], new["all"]["ast"])}; in implementation files alone '
                 f'it falls {drop(base["impl"]["ast"], new["impl"]["ast"])}. {name} also writes '
                 f'{drop(base["impl"]["loc"], new["impl"]["loc"])} less implementation, so <b>the count of flagged '
                 f'implementation lines per run falls {drop(base["impl"]["ast_lines"], new["impl"]["ast_lines"])}</b> '
                 f'({base["impl"]["ast_lines"]:,} to {new["impl"]["ast_lines"]:,}). Erosion has the same shape with '
                 f'more left over: down {drop(base["all"]["erosion"], new["all"]["erosion"])} over the whole snapshot '
                 f'and {drop(base["impl"]["erosion"], new["impl"]["erosion"])} in implementation files. '
                 f'{cloned_sentence(base, new)}</p>')
    against = "; ".join(
        f'{PROMPT_LABELS[prompt]}\'s ast-grep share is '
        f'{pooled[prompt]["impl"]["ast"] / human["impl"]["ast"]:.1f} times the human one, its erosion is '
        f'{pooled[prompt]["impl"]["erosion"]:.2f} against {human["impl"]["erosion"]:.2f}, its cloned share is '
        f'{pooled[prompt]["impl"]["cloned"]:.3f} against {human["impl"]["cloned"]:.3f}, and its tests are cloned '
        f'{pooled[prompt]["test"]["cloned"] / human["test"]["cloned"]:.1f} times as much as human tests'
        for prompt in others)
    note += (f'<p class="note" style="margin-top:8px">The human row is the mean over {len(repos)} of the 28 Major-tier '
             f'repositories (over 10k stars) in the paper\'s v1, Table 2, at HEAD, split by the same tool. '
             f'Humans write tests too, '
             f'{human["test_share"]:.0%} of their lines, so their whole-repository figures are diluted the same way. '
             f'Implementation against implementation, {against}. '
             f'The human bars in the headline are this same rerun. v1\'s Table 2 gives '
             f'0.10 for ast-grep, which this scb-check version does not reproduce ({human["all"]["ast"]:.3f} here); '
             f'its erosion mean, 0.31, it does ({human["all"]["erosion"]:.2f}).</p>')
    return table + note


def build():
    template = (HERE / "uplift-grid.template.html").read_text()
    assert template.count("__DATA__") == 1
    assert template.count("__SPLIT__") == 1
    assert template.count("__TEST_SHARE__") == 1
    page = template.replace("__DATA__", tool_json("grid").strip())
    repos = json.loads((HERE / "human-split.json").read_text())
    rows = json.loads(tool_json("quality-split", "--prompts", ",".join(PROMPT_LABELS)))
    page = page.replace("__SPLIT__", split_section(rows, repos))
    page = page.replace("__TEST_SHARE__", json.dumps(test_share_panel(rows, repos)))
    out = HERE / "uplift-grid.html"
    out.write_text(page)
    return out


if __name__ == "__main__":
    print(build())
