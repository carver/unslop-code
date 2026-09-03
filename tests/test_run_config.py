"""Naming and prompt resolution for bin/run-config."""
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "run-config"
rc = types.ModuleType("run_config"); rc.__file__ = str(SCRIPT); sys.modules["run_config"] = rc
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), rc.__dict__)


def test_run_name_adds_the_patched_suffix_once():
    assert rc.run_name("spectest-min2-strict-errors", False) == "spectest-min2-strict-errors"
    assert rc.run_name("configs/prompts/spectest-min2-strict-errors.jinja", True) == "spectest-min2-strict-errors-disambiguated"
    assert rc.run_name("just-solve", True, name="just-solve-disambiguated") == "just-solve-disambiguated"


def test_prompt_resolves_to_local_template_or_benchmark_name():
    assert rc.resolve_prompt("spectest-v8A-no-libs-no-subagent").endswith("configs/prompts/spectest-v8A-no-libs-no-subagent.jinja")
    assert rc.resolve_prompt("just-solve") == "just-solve"


def test_config_text_carries_prompt_problem_and_run_dir_name():
    t = rc.config_text("just-solve", "xjq", "just-solve-disambiguated", True, "LAUNCH")
    assert "prompt: just-solve\n" in t and "  - xjq\n" in t
    assert "_just-solve-disambiguated/${now" in t and "#   LAUNCH" in t and "patched spec copy" in t
