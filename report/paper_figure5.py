#!/usr/bin/env python3
"""Read Figure 5's erosion lines out of the SlopCodeBench paper's vector figure.

    curl -sL -o /tmp/scb-v2.tar https://arxiv.org/e-print/2603.24755v2
    mkdir -p /tmp/scb-v2 && tar -xf /tmp/scb-v2.tar -C /tmp/scb-v2
    python3 report/paper_figure5.py /tmp/scb-v2/figures/prompt_strategy_trajectories.pdf

Prints {row: {model: {prompt: [Start, Early, Mid, Late, Final]}}} for the figure's two rows,
mean structural erosion (top) and verbosity (bottom) by progress phase (arXiv 2603.24755v2,
Figure 5). The figure is matplotlib output, so each line is one four-segment path; the y scale
comes from the tick labels matched to their gridlines, which makes a value good to about
0.003. The result is pasted into the PAPER constant of uplift-grid.template.html. Needs
pymupdf: `uv run --no-project --with pymupdf python report/paper_figure5.py <pdf>`.
"""
import json
import sys

import pymupdf

PANELS = {"GPT 5.3 Codex": (40, 215), "GPT 5.4": (250, 425), "GPT 5.5": (460, 635)}  # x span of each panel, points
PROMPTS = {
    (0.03, 0.32, 0.61): "Baseline",
    (0.9, 0.33, 0.05): "Anti-Slop",
    (0.34, 0.64, 0.35): "Plan-First",
}  # line colours
ROWS = {"erosion": (0, 100), "verbosity": (100, 195)}  # y span of each row of panels, points


def tick_scale(page, x0, x1, y0, y1, gridlines):
    """y -> value for one panel, from its numeric tick labels and the gridlines they sit on."""
    ticks = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                bb, text = span["bbox"], span["text"]
                cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
                if x0 - 30 < cx < x0 and y0 < cy < y1 and text.replace(".", "").isdigit():
                    near = [gy for gx, gy in gridlines if x0 < gx < x0 + 12 and abs(gy - cy) < 4]
                    ticks.append((float(text), min(near, key=lambda gy: abs(gy - cy)) if near else cy))
    (v0, y0), (v1, y1) = min(ticks), max(ticks)
    return lambda y: v0 + (v1 - v0) * (y - y0) / (y1 - y0)


def figure_lines(pdf_path):
    page = pymupdf.open(pdf_path)[0]
    drawings = page.get_drawings()
    gridlines = [
        (d["items"][0][1].x, d["items"][0][1].y)
        for d in drawings
        if len(d["items"]) == 1 and d["items"][0][0] == "l" and abs(d["items"][0][1].y - d["items"][0][2].y) < 0.01
    ]
    out = {}
    for row, (y0, y1) in ROWS.items():
        out[row] = {}
        for model, (x0, x1) in PANELS.items():
            value = tick_scale(page, x0, x1, y0, y1, gridlines)
            out[row][model] = {}
            for d in drawings:
                items = d["items"]
                if len(items) != 4 or any(it[0] != "l" for it in items) or d.get("width") != 2.0:
                    continue
                xs = [items[0][1].x] + [it[2].x for it in items]
                ys = [items[0][1].y] + [it[2].y for it in items]
                if not (x0 < xs[0] < x1 and y0 < ys[0] < y1):
                    continue
                prompt = PROMPTS[tuple(round(c, 2) for c in d["color"])]
                out[row][model][prompt] = [round(value(y), 3) for y in ys]
    return out


if __name__ == "__main__":
    print(json.dumps(figure_lines(sys.argv[1])))
