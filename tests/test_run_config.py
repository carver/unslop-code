"""Naming and prompt resolution for bin/run-config."""
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "run-config"
rc = types.ModuleType("run_config"); rc.__file__ = str(SCRIPT); sys.modules["run_config"] = rc
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), rc.__dict__)


def test_run_name_adds_the_spec_suffix_once():
    assert rc.run_name("spectest-min2-strict-errors", "v0") == "spectest-min2-strict-errors"
    assert rc.run_name("configs/prompts/spectest-v9.jinja", "v2") == "spectest-v9-specv2"
    assert rc.run_name("just-solve", "v1", name="just-solve-specv1") == "just-solve-specv1"


def test_problems_root_is_the_cache_for_v0_and_the_problems_specs_folder_otherwise():
    assert rc.problems_root("xjq", "v0") == rc.CACHE
    assert rc.problems_root("xjq", "v2") == rc.ROOT / "specs" / "xjq" / "v2" / "problems"


def test_prompt_resolves_to_local_template_or_benchmark_name():
    assert rc.resolve_prompt("spectest-v8A-no-libs-no-subagent") == "configs/prompts/spectest-v8A-no-libs-no-subagent.jinja"
    assert rc.resolve_prompt(str(rc.ROOT / "configs/prompts/spectest-v9.jinja")) == "configs/prompts/spectest-v9.jinja"
    assert rc.resolve_prompt("just-solve") == "just-solve"


def test_repo_relative_keeps_paths_outside_the_repo_absolute(tmp_path):
    outside = tmp_path / "other.jinja"
    assert rc.repo_relative(outside) == str(outside.resolve())
    assert rc.repo_relative(rc.ROOT / "outputs") == "outputs"


def test_config_text_carries_prompt_problem_and_run_dir_name():
    t = rc.config_text("just-solve", "xjq", "just-solve-specv1", "v1", "LAUNCH")
    assert "prompt: just-solve\n" in t and "  - xjq\n" in t
    assert "_just-solve-specv1/${now" in t and "#   LAUNCH" in t and "spec v1, specs/xjq/v1/" in t


def test_config_text_names_agent_and_outputs_relative_to_the_repo_root():
    t = rc.config_text("configs/prompts/spectest-v9.jinja", "xjq", "spectest-v9", "v0", "LAUNCH")
    assert "agent: configs/agents/claude_code-2.1.251.yaml\n" in t and "save_dir: outputs\n" in t
    assert str(rc.ROOT) not in t
