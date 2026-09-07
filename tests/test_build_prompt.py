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


MIN10 = ROOT / "configs/prompts/min10-chunks"


def test_all_min10_chunks_rebuild_v10_line_for_line():
    name, text = bp.build("ABCDEFGHIJKLMNOPQRS", MIN10)
    assert name == "min10-ABCDEFGHIJKLMNOPQRS"
    assert nonblank(text) == nonblank((ROOT / "configs/prompts/spectest-v10.jinja").read_text())


def test_min10_is_min9_with_only_the_registry_chunk_changed():
    """The two sets share letters and slugs, so a min9 subset name means the same rules in min10."""
    nine = {p.name: p.read_text() for p in MIN9.glob("?-*.txt")}
    ten = {p.name: p.read_text() for p in MIN10.glob("?-*.txt")}
    assert nine.keys() == ten.keys()
    assert [n for n in nine if nine[n] != ten[n]] == ["J-testing-ambiguity-registry.txt"]
    assert (MIN9 / "SKELETON.jinja").read_text() == (MIN10 / "SKELETON.jinja").read_text()


MIN11 = ROOT / "configs/prompts/min11-chunks"


def test_all_min11_chunks_rebuild_v11_line_for_line():
    name, text = bp.build("ABCDEFGHIJKLMNOPQRS", MIN11)
    assert name == "min11-ABCDEFGHIJKLMNOPQRS"
    assert nonblank(text) == nonblank((ROOT / "configs/prompts/spectest-v11.jinja").read_text())


def test_min11_is_min10_with_only_the_generator_floor_and_task_line_changed():
    """Same letters and slugs again, so a min10 subset name means the same rules in min11."""
    ten = {p.name: p.read_text() for p in MIN10.glob("?-*.txt")}
    eleven = {p.name: p.read_text() for p in MIN11.glob("?-*.txt")}
    assert ten.keys() == eleven.keys()
    assert [n for n in ten if ten[n] != eleven[n]] == ["F-testing-generator-floor.txt"]
    assert eleven["F-testing-generator-floor.txt"].rstrip().endswith("empty, one element, etc.")
    ten_skeleton = (MIN10 / "SKELETON.jinja").read_text().splitlines()
    eleven_skeleton = (MIN11 / "SKELETON.jinja").read_text().splitlines()
    assert [(a, b) for a, b in zip(ten_skeleton, eleven_skeleton) if a != b] == [
        ("Fully implement the following spec, without questions. Use the approach:",
         "Fully implement the following spec. Use the approach:")]
