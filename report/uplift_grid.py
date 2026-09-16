#!/usr/bin/env python3
"""Build report/uplift-grid.html: the template with `bin/grid --json` embedded.

    python3 report/uplift_grid.py    # then publish report/uplift-grid.html

The page is self-contained: the grid data sits in a script constant, the charts are inline
SVG drawn by the page, no library. Re-run after any run lands so the page and
notes/results.md agree.
"""
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent


def build():
    data = subprocess.run([ROOT / "bin" / "grid", "--json"], capture_output=True, text=True, check=True).stdout
    template = (HERE / "uplift-grid.template.html").read_text()
    assert template.count("__DATA__") == 1
    out = HERE / "uplift-grid.html"
    out.write_text(template.replace("__DATA__", data.strip()))
    return out


if __name__ == "__main__":
    print(build())
