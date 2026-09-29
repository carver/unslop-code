#!/usr/bin/env python3
"""Read Figure 4's human lines out of the SlopCodeBench paper's vector figure.

    curl -sL -o /tmp/scb-v2.tar https://arxiv.org/e-print/2603.24755v2
    mkdir -p /tmp/scb-v2 && tar -xf /tmp/scb-v2.tar -C /tmp/scb-v2
    python3 report/paper_figure4.py /tmp/scb-v2/figures/agent_human_trajectory.pdf

Prints {metric: {series: [Start, Early, Mid, Late, Final]}} for the figure's two panels,
verbosity (left) and erosion (right), over the paper's human repository panel by GitHub-star tier
and its agents (arXiv 2603.24755v2, Figure 4). A repository's phases are up to 30 sampled
commits of its history, normalized the way an agent's checkpoints are. Values are good to about
0.003, as in paper_figure5.py, whose tick scale this reuses. The Major line is pasted into the
PAPER_HUMAN constant of uplift-grid.template.html. Needs pymupdf:
`uv run --no-project --with pymupdf python report/paper_figure4.py <pdf>`.
"""
import json
import sys

import pymupdf

from paper_figure5 import tick_scale

PANELS = {"verbosity": (20, 250), "erosion": (265, 495)}  # x span of each panel's plot, points
ROW = (0, 110)  # y span of the panels, points
SERIES = {
    (0.12, 0.47, 0.71): "Agents",
    (0.58, 0.64, 0.72): "Hobby",
    (1.0, 0.5, 0.05): "Niche",
    (0.17, 0.63, 0.17): "Established",
    (0.84, 0.15, 0.16): "Major",
}  # line colours


def figure_lines(pdf_path):
    page = pymupdf.open(pdf_path)[0]
    drawings = page.get_drawings()
    gridlines = [
        (d["items"][0][1].x, d["items"][0][1].y)
        for d in drawings
        if len(d["items"]) == 1 and d["items"][0][0] == "l" and abs(d["items"][0][1].y - d["items"][0][2].y) < 0.01
    ]
    out = {}
    for metric, (x0, x1) in PANELS.items():
        value = tick_scale(page, x0, x1, *ROW, gridlines)
        out[metric] = {}
        for d in drawings:
            items = d["items"]
            if len(items) != 4 or any(it[0] != "l" for it in items):
                continue
            xs = [items[0][1].x] + [it[2].x for it in items]
            ys = [items[0][1].y] + [it[2].y for it in items]
            if x0 < xs[0] < x1:
                out[metric][SERIES[tuple(round(c, 2) for c in d["color"])]] = [round(value(y), 3) for y in ys]
    return out


if __name__ == "__main__":
    print(json.dumps(figure_lines(sys.argv[1])))
