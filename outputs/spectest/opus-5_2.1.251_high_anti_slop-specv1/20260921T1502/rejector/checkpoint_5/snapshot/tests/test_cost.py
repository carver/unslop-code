"""Cost accounting and the budget that stops a run.

The mock API reports 10 prompt tokens and 5 completion tokens for every call,
so a call priced at 1.0 per 1k tokens costs 0.015.
"""

CALL_COST = 0.015

TASK = {
    "name": "math_solve",
    "model": "gpt-4",
    "prompt": {"user": "{question}"},
    "generation": {"scheme": "greedy", "max_tokens": 64},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
    "output_field": "solution",
    "cost": {"prompt_cost_per_1k": 1.0, "completion_cost_per_1k": 1.0},
}

JUDGE = {
    "type": "llm_judge",
    "judge_prompt": {"user": "Rate this:\n{__response__}\n\nScore:"},
    "threshold": 7,
    "extract": "first_number",
}

ROWS = [{"question": f"q{index}", "answer": "5"} for index in range(6)]


def test_cost_is_reported_per_kind_and_in_total(cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    run = cli({**TASK, "api_url": url}, ROWS[:2])

    assert run.summary["cost"]["prompt"] == 2 * 10 / 1000
    assert run.summary["cost"]["completion"] == 2 * 5 / 1000
    assert run.summary["cost"]["total"] == 2 * CALL_COST
    assert run.summary["cost"]["budget"] is None
    assert run.summary["cost"]["budget_exceeded"] is False


def test_a_run_without_cost_configuration_reports_none(cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    run = cli({**TASK, "api_url": url, "cost": None}, ROWS[:2])

    assert "cost" not in run.summary


def test_judge_calls_are_priced_too(cli, api):
    url, _ = api(lambda payload, call: "8" if "Score:" in str(payload) else "#### 5")
    run = cli({**TASK, "api_url": url, "evaluation": JUDGE}, ROWS[:1])

    # The answer and the judgement of it.
    assert run.summary["total_api_calls"] == 2
    assert run.summary["cost"]["total"] == 2 * CALL_COST


def test_a_spent_budget_stops_the_run_and_keeps_what_finished(cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    budget = {**TASK["cost"], "budget": 2 * CALL_COST}
    run = cli(
        {**TASK, "api_url": url, "cost": budget, "rate_limits": {"max_concurrent": 1}}, ROWS
    )

    assert run.code == 0
    assert len(run.records) == 2 and all(record["result"]["passed"] for record in run.records)
    assert run.summary["total"] == 2
    assert run.summary["cost"]["budget_exceeded"] is True
    assert run.summary["cost"]["budget_remaining"] == 0.0


def test_a_budget_the_run_stays_under_is_not_exceeded(cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    budget = {**TASK["cost"], "budget": 10.0}
    run = cli({**TASK, "api_url": url, "cost": budget}, ROWS)

    assert len(run.records) == 6
    assert run.summary["cost"]["budget_exceeded"] is False
    assert run.summary["cost"]["budget_remaining"] == round(10.0 - 6 * CALL_COST, 6)


def test_the_budget_flag_overrides_the_configured_one(cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    run = cli(
        {**TASK, "api_url": url, "rate_limits": {"max_concurrent": 1}},
        ROWS,
        "--budget",
        str(3 * CALL_COST),
    )

    assert run.summary["cost"]["budget"] == 3 * CALL_COST
    assert len(run.records) == 3


def test_every_agentic_iteration_is_priced(cli, api):
    tools = [
        {
            "name": "lookup",
            "parameters": {"type": "object", "properties": {"key": {"type": "string"}}},
            "handler": {"type": "static_map", "mapping": {"five": "5"}},
        }
    ]
    def respond(payload, call):
        """Call the tool first, then answer with what it returned."""
        if any(turn["role"] == "tool" for turn in payload["messages"]):
            return "#### 5"
        return [{"name": "lookup", "arguments": {"key": "five"}}]

    url, _ = api(respond)
    run = cli(
        {**TASK, "api_url": url, "generation": {"scheme": "agentic", "max_tokens": 64},
         "tools": tools},
        ROWS[:1],
    )

    assert run.records[0]["result"]["iterations"] == 2
    assert run.summary["cost"]["total"] == 2 * CALL_COST


def test_each_task_of_a_multi_config_is_priced_by_its_own_rates(cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    document = {
        "defaults": {
            "api_url": url,
            "model": "gpt-4",
            "cost": {"prompt_cost_per_1k": 1.0, "completion_cost_per_1k": 1.0},
        },
        "tasks": {
            "cheap": {
                "prompt": {"user": "{question}"},
                "generation": {"scheme": "greedy"},
                "output_field": "solution",
                "cost": {"prompt_cost_per_1k": 0.5, "completion_cost_per_1k": 0.5},
            },
            "full": {
                "prompt": {"user": "{question}"},
                "generation": {"scheme": "greedy"},
                "output_field": "solution",
            },
        },
    }
    rows = {"cheap": ROWS[:1], "full": ROWS[:1]}
    run = cli(document, rows, multi=True)

    assert run.summary["cost"]["total"] == CALL_COST / 2 + CALL_COST
