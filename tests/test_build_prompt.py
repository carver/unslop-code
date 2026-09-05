"""bin/build-prompt: chunk sets build deterministic prompts, and all chunks rebuild min4."""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "build-prompt"
bp = types.ModuleType("build_prompt"); bp.__file__ = str(SCRIPT); sys.modules["build_prompt"] = bp
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), bp.__dict__)


def nonblank(text):
    return [l for l in text.splitlines() if l.strip()]


def test_all_chunks_rebuild_min4_line_for_line():
    name, text = bp.build("ABCDEFGHIJK")
    assert name == "min4-ABCDEFGHIJK"
    assert nonblank(text) == nonblank((ROOT / "configs/prompts/spectest-min4-ambiguities.jinja").read_text())


@pytest.mark.parametrize("letters,rung", [("ADEJK", "spectest-min2-strict-errors"), ("ABCJK", "spectest-min2b-generator-floor"), ("ABCDEJK", "spectest-min3-hypothesis")])
def test_existing_rungs_are_chunk_sets(letters, rung):
    assert nonblank(bp.build(letters)[1]) == nonblank((ROOT / f"configs/prompts/{rung}.jinja").read_text())


def test_letter_order_and_case_do_not_matter():
    assert bp.build("geb") == bp.build("BEG")
    assert bp.build("BEG")[0] == "min4-BEG"


def test_unknown_or_repeated_letters_fail():
    with pytest.raises(SystemExit):
        bp.build("BZ")
    with pytest.raises(SystemExit):
        bp.build("BB")



MIN9 = ROOT / "configs/prompts/min9-chunks"


def test_all_min9_chunks_rebuild_v9_line_for_line():
    name, text = bp.build("ABCDEFGHIJKLMNOPQRS", MIN9)
    assert name == "min9-ABCDEFGHIJKLMNOPQRS"
    assert nonblank(text) == nonblank((ROOT / "configs/prompts/spectest-v9.jinja").read_text())


def test_min9_subset_keeps_every_section_header_and_leaves_no_slot():
    _, text = bp.build("DFJ", MIN9)
    for header in ("# Environment", "# Testing", "# Implement", "# Declare complete", "# Spec"):
        assert header in text
    assert "<<" not in text
    assert "\n\n\n" not in text
    assert "Touch an IN_PROGRESS file. Delete any COMPLETED file.\n\n# Testing" in text
