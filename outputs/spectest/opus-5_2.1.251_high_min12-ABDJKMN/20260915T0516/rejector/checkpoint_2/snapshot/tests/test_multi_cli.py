"""Part 2 CLI: --task, --eval-model, input modes, and output handling."""
import json
import os

import pytest

from conftest import (make_config, make_multi_config, judge_task, script_task,
                      MultiRun)
from mock_api import MockAPI, always, by_text, message_text, per_question

GSM = [{"question": "2+2?", "answer": "4"}]
MML = [{"question": "capital?", "answer": "B"}]
REVIEW = [{"prompt_text": "Write about cats", "criteria": "clarity"}]


def three_task_config(api_url=None):
    cfg = make_multi_config(api_url=api_url or "http://localhost:8000")
    cfg["tasks"]["review"] = judge_task(threshold=7)
    return cfg


# Spec: "explicit mapping mode:
#   --config multi.yaml --input gsm8k=math.jsonl --input mmlu=qa.jsonl
#   --output results/"
# Context: Input handling for multi-task configs.
def test_explicit_mapping_mode_runs_both_tasks(multi):
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B"})) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML}, mode="explicit")
    assert run.returncode == 0, run.stderr
    assert run.exists("gsm8k") and run.exists("mmlu")
    assert len(run.rows("gsm8k")) == 1 and len(run.rows("mmlu")) == 1


def test_explicit_mapping_uses_the_named_path(multi, cli, workdir):
    cfg = make_multi_config()
    with MockAPI(always("#### 4")) as api:
        cfg["defaults"]["api_url"] = api.url
        cfg_path = multi.write_config(cfg)
        math_path = multi.write_input("gsm8k", GSM, filename="math.jsonl")
        qa_path = multi.write_input("mmlu", MML, filename="qa.jsonl")
        proc = cli("run", "--config", cfg_path,
                   "--input", "gsm8k=%s" % math_path,
                   "--input", "mmlu=%s" % qa_path,
                   "--output", str(workdir / "results"))
    assert proc.returncode == 0, proc.stderr
    assert os.path.exists(str(workdir / "results" / "gsm8k.jsonl"))
    assert os.path.exists(str(workdir / "results" / "mmlu.jsonl"))


# Spec: "directory mode: --config multi.yaml --input-dir data/ --output results/"
# and "--input-dir looks for `<task_name>.jsonl`"
# Context: Input handling for multi-task configs.
def test_directory_mode_reads_task_named_files(multi):
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B"})) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML}, mode="dir")
    assert run.returncode == 0, run.stderr
    assert run.rows("gsm8k")[0]["input"] == GSM[0]
    assert run.rows("mmlu")[0]["input"] == MML[0]


def test_directory_mode_missing_task_file_exits_1(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM}, mode="dir")
    assert run.returncode == 1
    assert run.stderr.strip()


def test_missing_input_directory_exits_1(multi, cli, workdir):
    cfg_path = multi.write_config(make_multi_config())
    proc = cli("run", "--config", cfg_path, "--input-dir",
               str(workdir / "nope"), "--output", str(workdir / "results"))
    assert proc.returncode == 1
    assert proc.stderr.strip()


# Spec: "for multi-task configs, explicit `--input <task=path>` and
# `--input-dir` are alternative modes; do not combine them"
# Context: Rules, input handling.
def test_combining_input_and_input_dir_exits_1(multi, cli, workdir):
    cfg = make_multi_config()
    cfg_path = multi.write_config(cfg)
    path = multi.write_input("gsm8k", GSM)
    multi.write_input("mmlu", MML)
    proc = cli("run", "--config", cfg_path,
               "--input", "gsm8k=%s" % path,
               "--input-dir", str(multi.data_dir),
               "--output", str(workdir / "results"))
    assert proc.returncode == 1
    assert proc.stderr.strip()


def test_multi_task_input_without_task_prefix_exits_1(multi, cli, workdir):
    cfg_path = multi.write_config(make_multi_config())
    path = multi.write_input("gsm8k", GSM)
    proc = cli("run", "--config", cfg_path, "--input", path,
               "--output", str(workdir / "results"))
    assert proc.returncode == 1
    assert proc.stderr.strip()


def test_input_for_an_unknown_task_exits_1(multi, cli, workdir):
    cfg_path = multi.write_config(make_multi_config())
    path = multi.write_input("gsm8k", GSM)
    proc = cli("run", "--config", cfg_path,
               "--input", "nosuchtask=%s" % path,
               "--output", str(workdir / "results"))
    assert proc.returncode == 1
    assert proc.stderr.strip()


def test_missing_input_for_one_task_exits_1(multi, cli, workdir):
    cfg_path = multi.write_config(make_multi_config())
    path = multi.write_input("gsm8k", GSM)
    proc = cli("run", "--config", cfg_path, "--input", "gsm8k=%s" % path,
               "--output", str(workdir / "results"))
    assert proc.returncode == 1
    assert proc.stderr.strip()


def test_no_input_flag_at_all_exits_1(multi, cli, workdir):
    cfg_path = multi.write_config(make_multi_config())
    proc = cli("run", "--config", cfg_path, "--output", str(workdir / "results"))
    assert proc.returncode == 1
    assert proc.stderr.strip()


# Spec: "--task <name>: repeatable; run only the selected task or tasks"
# Context: CLI changes. "Only `gsm8k` runs."
def test_task_flag_runs_only_the_selected_task(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM}, args=["--task", "gsm8k"])
    assert run.returncode == 0, run.stderr
    assert run.exists("gsm8k")
    assert api.call_count == 1
    assert message_text(api.calls[0], "user") == "2+2?"


# Spec: "when `--task` is present, require input only for selected tasks and
# ignore unselected tasks for validation and execution"
# Context: Rules, input handling. "Input files for unselected tasks are not
# required."
def test_unselected_task_input_is_not_required(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM}, args=["--task", "gsm8k"])
    assert run.returncode == 0, run.stderr


def test_unselected_task_input_is_not_required_in_directory_mode(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM}, mode="dir", args=["--task", "gsm8k"])
    assert run.returncode == 0, run.stderr
    assert run.exists("gsm8k")


# T21: an unselected task is never validated either.
def test_unselected_task_with_a_broken_config_is_ignored(multi):
    cfg = make_multi_config()
    del cfg["tasks"]["mmlu"]["prompt"]["user"]
    with MockAPI(always("#### 4")) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"gsm8k": GSM}, args=["--task", "gsm8k"])
    assert run.returncode == 0, run.stderr
    assert run.rows("gsm8k")[0]["result"]["passed"] is True


def test_task_flag_is_repeatable(multi):
    cfg = three_task_config()
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B"})) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"gsm8k": GSM, "mmlu": MML},
                        args=["--task", "gsm8k", "--task", "mmlu"])
    assert run.returncode == 0, run.stderr
    assert run.exists("gsm8k") and run.exists("mmlu")
    assert not run.exists("review")
    assert sorted(run.summary["tasks"]) == ["gsm8k", "mmlu"]


def test_unknown_task_name_exits_1(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML},
                        args=["--task", "nosuchtask"])
    assert run.returncode == 1
    assert run.stderr.strip()


# Spec: "when `--task` is present, write output files only for the tasks that
# ran"
# Context: Output handling.
def test_no_output_file_for_unselected_tasks(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML}, args=["--task", "gsm8k"])
    assert run.returncode == 0, run.stderr
    assert run.exists("gsm8k")
    assert not run.exists("mmlu")


# Spec: "for multi-task configs, `--output` must be a directory" and "write
# `<output_dir>/<task_name>.jsonl`"
# Context: Output handling.
def test_output_directory_is_created_when_absent(multi, workdir):
    out = workdir / "fresh" / "nested"
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM}, args=["--task", "gsm8k"], output=out)
    assert run.returncode == 0, run.stderr
    assert os.path.exists(str(out / "gsm8k.jsonl"))


def test_existing_file_as_output_exits_1(multi, workdir):
    out = workdir / "not_a_dir"
    out.write_text("")
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM}, args=["--task", "gsm8k"], output=out)
    assert run.returncode == 1
    assert run.stderr.strip()


def test_output_files_are_named_after_the_task(multi):
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B"})) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 0, run.stderr
    assert sorted(os.listdir(run.out_dir)) == ["gsm8k.jsonl", "mmlu.jsonl"]


def test_existing_task_output_file_is_overwritten(multi, workdir):
    out = workdir / "results"
    out.mkdir()
    (out / "gsm8k.jsonl").write_text("STALE\n")
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM}, args=["--task", "gsm8k"], output=out)
    assert run.returncode == 0, run.stderr
    assert "STALE" not in (out / "gsm8k.jsonl").read_text()


# Spec: "for single-task configs, `--input <path>` without `=` still behaves
# as in Part 1" and "--output <path> still writes a single file"
# Context: Rules, input and output handling.
def test_single_task_config_keeps_part_1_input_and_output(run_tool, workdir):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert os.path.isfile(str(workdir / "results.jsonl"))
    assert len(run.rows) == 1


def test_single_task_output_path_is_not_treated_as_a_directory(run_tool, workdir):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}],
                       output_name="out.jsonl")
    assert run.returncode == 0, run.stderr
    assert os.path.isfile(str(workdir / "out.jsonl"))


# Spec: "--eval-model <string>: override the judge model for all selected
# `llm_judge` tasks"
# Context: CLI changes.
def test_eval_model_overrides_the_judge_model(multi):
    cfg = make_multi_config(tasks={"review": judge_task(threshold=7)})
    with MockAPI(by_text([("Rate this response", "8")], default="essay")) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"review": REVIEW},
                        args=["--eval-model", "cheap-judge"])
    assert run.returncode == 0, run.stderr
    models = {("judge" if "Rate this response" in message_text(c) else "gen"):
              c["model"] for c in api.calls}
    assert models["judge"] == "cheap-judge"
    assert models["gen"] == "gpt-4"
    assert run.rows("review")[0]["meta"]["judge_meta"]["model"] == "cheap-judge"


# T35: the flag beats a judge model set in the config.
def test_eval_model_beats_evaluation_model(multi):
    cfg = make_multi_config(
        tasks={"review": judge_task(threshold=7, model="config-judge")})
    with MockAPI(by_text([("Rate this response", "8")], default="essay")) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"review": REVIEW},
                        args=["--eval-model", "flag-judge"])
    assert run.returncode == 0, run.stderr
    judge = [c for c in api.calls if "Rate this response" in message_text(c)]
    assert judge[0]["model"] == "flag-judge"


def test_eval_model_applies_to_every_selected_judge_task(multi):
    cfg = make_multi_config(tasks={
        "review": judge_task(threshold=7),
        "review2": judge_task(threshold=7),
    })
    with MockAPI(by_text([("Rate this response", "8")], default="essay")) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"review": REVIEW, "review2": REVIEW},
                        args=["--eval-model", "cheap-judge"])
    assert run.returncode == 0, run.stderr
    judge = [c for c in api.calls if "Rate this response" in message_text(c)]
    assert len(judge) == 2
    assert {c["model"] for c in judge} == {"cheap-judge"}


def test_eval_model_does_not_change_non_judge_tasks(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM}, args=["--task", "gsm8k",
                                              "--eval-model", "cheap-judge"])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["model"] == "gpt-4"


def test_eval_model_works_for_a_single_task_config(run_tool):
    evaluation = {"type": "llm_judge", "threshold": 7,
                  "judge_prompt": {"user": "Rate this response:\n{__response__}"}}
    with MockAPI(by_text([("Rate this response", "8")], default="essay")) as api:
        run = run_tool(make_config(api_url=api.url, evaluation=evaluation,
                                   user="{prompt_text}"),
                       [{"prompt_text": "cats"}],
                       args=["--eval-model", "cheap-judge"])
    assert run.returncode == 0, run.stderr
    judge = [c for c in api.calls if "Rate this response" in message_text(c)]
    assert judge[0]["model"] == "cheap-judge"


# T20: Part 1 overrides still apply, and apply to every selected task.
def test_model_override_applies_to_all_tasks(multi):
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B"})) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML},
                        args=["--model", "override-model"])
    assert run.returncode == 0, run.stderr
    assert {c["model"] for c in api.calls} == {"override-model"}


# T22: `--task` also selects against a single-task config's `task.name`.
def test_task_flag_matching_the_single_task_name_runs_it(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, name="gsm8k_solve"),
                       [{"question": "q", "answer": "5"}],
                       args=["--task", "gsm8k_solve"])
    assert run.returncode == 0, run.stderr
    assert len(run.rows) == 1


def test_task_flag_naming_another_task_exits_1_for_single_task_configs(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, name="gsm8k_solve"),
                       [{"question": "q", "answer": "5"}],
                       args=["--task", "other"])
    assert run.returncode == 1
    assert run.stderr.strip()


# T38: directory mode also works for a single-task config, by `task.name`.
def test_single_task_config_accepts_input_dir(multi, cli, workdir):
    cfg = make_config(name="gsm8k")
    with MockAPI(always("#### 4")) as api:
        cfg["task"]["api_url"] = api.url
        cfg_path = multi.write_config(cfg, name="single.yaml")
        multi.write_input("gsm8k", GSM)
        proc = cli("run", "--config", cfg_path,
                   "--input-dir", str(multi.data_dir),
                   "--output", str(workdir / "out.jsonl"))
    assert proc.returncode == 0, proc.stderr
    assert os.path.isfile(str(workdir / "out.jsonl"))


# T39: `<name>=<path>` is a mapping for a single-task config when the name
# matches; any other value stays a literal path.
def test_single_task_config_accepts_a_matching_mapping(multi, cli, workdir):
    cfg = make_config(name="gsm8k")
    with MockAPI(always("#### 4")) as api:
        cfg["task"]["api_url"] = api.url
        cfg_path = multi.write_config(cfg, name="single.yaml")
        path = multi.write_input("gsm8k", GSM)
        proc = cli("run", "--config", cfg_path, "--input", "gsm8k=%s" % path,
                   "--output", str(workdir / "out.jsonl"))
    assert proc.returncode == 0, proc.stderr
    assert os.path.isfile(str(workdir / "out.jsonl"))


def test_single_task_input_path_containing_an_equals_sign(multi, cli, workdir):
    cfg = make_config(name="gsm8k")
    with MockAPI(always("#### 4")) as api:
        cfg["task"]["api_url"] = api.url
        cfg_path = multi.write_config(cfg, name="single.yaml")
        path = multi.write_input("gsm8k", GSM, filename="a=b.jsonl")
        proc = cli("run", "--config", cfg_path, "--input", path,
                   "--output", str(workdir / "out.jsonl"))
    assert proc.returncode == 0, proc.stderr


def test_two_input_flags_for_a_single_task_config_exit_1(multi, cli, workdir):
    cfg_path = multi.write_config(make_config(name="gsm8k"), name="single.yaml")
    path = multi.write_input("gsm8k", GSM)
    proc = cli("run", "--config", cfg_path, "--input", path, "--input", path,
               "--output", str(workdir / "out.jsonl"))
    assert proc.returncode == 1
    assert proc.stderr.strip()


# T40: a repeated mapping for the same task takes the last path given.
def test_repeated_input_for_one_task_uses_the_last_path(multi, cli, workdir):
    cfg = make_multi_config()
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B"})) as api:
        cfg["defaults"]["api_url"] = api.url
        cfg_path = multi.write_config(cfg)
        first = multi.write_input("gsm8k", [{"question": "ignored", "answer": "0"}],
                                  filename="first.jsonl")
        second = multi.write_input("gsm8k", GSM, filename="second.jsonl")
        mml = multi.write_input("mmlu", MML)
        proc = cli("run", "--config", cfg_path,
                   "--input", "gsm8k=%s" % first,
                   "--input", "gsm8k=%s" % second,
                   "--input", "mmlu=%s" % mml,
                   "--output", str(workdir / "results"))
    assert proc.returncode == 0, proc.stderr
    with open(str(workdir / "results" / "gsm8k.jsonl")) as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    assert [r["input"] for r in rows] == GSM
