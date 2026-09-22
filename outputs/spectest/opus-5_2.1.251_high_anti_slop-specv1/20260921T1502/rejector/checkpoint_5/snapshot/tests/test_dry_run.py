"""The `--dry-run` estimate, which makes no API calls."""

TASK = {
    "name": "gsm8k",
    # Nothing listens here: a dry run must not reach for it.
    "api_url": "http://127.0.0.1:1",
    "model": "gpt-4",
    "rpm": 100,
    "prompt": {"system": "Solve the math problem.", "user": "{question}"},
    "generation": {"scheme": "greedy", "max_tokens": 512},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
    "output_field": "solution",
    "cost": {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03},
}

# Four words in the system message and two in each rendered user message.
ROWS = [{"question": "what is this", "answer": "5"} for _ in range(10)]
WORDS_PER_PROMPT = 7


def test_a_dry_run_estimates_tokens_and_cost(cli):
    run = cli(TASK, ROWS, "--dry-run")

    prompt_tokens = round(WORDS_PER_PROMPT * 1.33 * 10)
    task = run.summary["tasks"]["gsm8k"]
    assert run.code == 0
    assert task["inputs"] == 10
    assert task["est_prompt_tokens"] == prompt_tokens
    assert task["est_completion_tokens"] == 10 * 512
    assert task["est_total_tokens"] == prompt_tokens + 10 * 512
    assert task["est_cost"] == round(prompt_tokens / 1000 * 0.01 + 5120 / 1000 * 0.03, 6)


def test_a_dry_run_writes_no_output_and_makes_no_calls(tmp_path, cli):
    run = cli(TASK, ROWS, "--dry-run")

    assert run.records == []
    assert not (tmp_path / "out.jsonl").exists()


def test_the_estimate_totals_every_task(cli):
    run = cli(TASK, ROWS, "--dry-run")
    task = run.summary["tasks"]["gsm8k"]

    assert run.summary["total_inputs"] == 10
    assert run.summary["est_total_tokens"] == task["est_total_tokens"]
    assert run.summary["est_total_cost"] == task["est_cost"]


def test_time_follows_the_request_budget(cli):
    run = cli(TASK, ROWS, "--dry-run")

    # Ten single attempt rows through a budget of 100 requests a minute.
    assert run.summary["est_time_minutes"] == 0.1


def test_rejection_sampling_plans_for_its_worst_case(cli):
    task = {**TASK, "generation": {"scheme": "rejection", "temperature": 0.7, "n": 5}}
    run = cli(task, ROWS, "--dry-run")

    assert run.summary["est_time_minutes"] == 0.5


def test_a_task_without_cost_rates_estimates_nothing_to_spend(cli):
    run = cli({**TASK, "cost": None}, ROWS, "--dry-run")

    assert run.summary["tasks"]["gsm8k"]["est_cost"] == 0.0
    assert run.summary["est_total_cost"] == 0.0


def test_a_dry_run_still_validates_the_input(cli):
    run = cli(TASK, [{"answer": "5"}], "--dry-run")

    assert run.code == 1
    assert "missing field 'question'" in run.stderr


def test_every_task_of_a_multi_config_is_estimated(cli):
    document = {
        "defaults": {"api_url": TASK["api_url"], "model": "gpt-4", "rpm": 100},
        "tasks": {
            "first": {
                "prompt": {"user": "{question}"},
                "generation": {"scheme": "greedy", "max_tokens": 100},
                "output_field": "solution",
            },
            "second": {
                "prompt": {"user": "{question}"},
                "generation": {"scheme": "greedy", "max_tokens": 200},
                "output_field": "solution",
            },
        },
    }
    run = cli(document, {"first": ROWS, "second": ROWS[:5]}, "--dry-run", multi=True)

    assert run.summary["tasks"]["first"]["est_completion_tokens"] == 10 * 100
    assert run.summary["tasks"]["second"]["est_completion_tokens"] == 5 * 200
    assert run.summary["total_inputs"] == 15
    assert run.summary["est_time_minutes"] == 0.15
