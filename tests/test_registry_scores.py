"""bin/registry-scores: every Differs (v9) and Risk (v10) spelling the agents have used parses to the same score."""
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "registry-scores"
rs = types.ModuleType("registry_scores")
rs.__file__ = str(SCRIPT)
sys.modules["registry_scores"] = rs
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), rs.__dict__)

SECTION_STYLE = """## T1. Heading one
### Choice
Option (1), because the table lists no error.
### Differs
20 — the author might have wanted a 400.
"""
DASH_STYLE = """## T2. Heading two
**Choice** — Option (1).
**Differs** — 30 — the carve-out hints otherwise.
"""
BARE_STYLE = """## T3. Heading three
**Choice** Option (1).
**Differs** 10 — the exact id string is unlikely to be asserted.
"""
RISK_HEADING_STYLE = """## T4. Heading four
### Choice
Option (2).
### Risk: 25
the author's fixture probably has a trailing newline.
"""
RISK_BOLD_STYLE = """## T5. Heading five
**Choice** — Option (1).
**Risk** 5 — nothing tested turns on it.
"""
ALL = SECTION_STYLE + DASH_STYLE + BARE_STYLE + RISK_HEADING_STYLE + RISK_BOLD_STYLE


def test_every_differs_spelling_scores():
    got = {e["id"]: e["score"] for e in rs.entries(ALL)}
    assert got == {"T1": 20, "T2": 30, "T3": 10, "T4": 25, "T5": 5}


def test_choice_and_differs_text_survive_each_style():
    by_id = {e["id"]: e for e in rs.entries(ALL)}
    assert by_id["T1"]["choice"].startswith("Option (1), because")
    assert by_id["T3"]["choice"] == "Option (1)."
    assert by_id["T3"]["differs"].startswith("10 — the exact id")
    assert by_id["T4"]["choice"] == "Option (2)."
    assert by_id["T4"]["differs"].startswith("25 the author's fixture")
