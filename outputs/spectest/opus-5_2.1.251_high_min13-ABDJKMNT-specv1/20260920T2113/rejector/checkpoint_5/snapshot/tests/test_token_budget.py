"""Token-aware scheduling end to end: what a request reserves, and how a TPM
budget paces a run."""

from __future__ import annotations

import asyncio

import httpx

from rejlib.api import ApiClient, Stats
from rejlib.config import RateLimits, load_config
from rejlib.cost import FREE, Ledger
from rejlib.prompts import build_messages
from rejlib.ratelimit import RateLimiter
from rejlib.scheduler import Scheduler
from tests.conftest import answering, numbered_rows, task_config

#: A task whose rendered request is exactly the question: five words below.
NO_SYSTEM = {"system": None, "user": "{question}"}
FIVE_WORD_ROW = {"question": "what is two plus three", "answer": "5"}


def reservations(cli, monkeypatch, config: dict, row: dict) -> list[int]:
    """The token amounts one attempt reserved before dispatch."""
    seen = []
    reserve = RateLimiter.reserve

    async def spy(self, estimated_tokens):
        seen.append(estimated_tokens)
        return await reserve(self, estimated_tokens)

    monkeypatch.setattr(RateLimiter, "reserve", spy)
    loaded = load_config(cli.write_config(config), {}).only

    async def scenario():
        async with httpx.AsyncClient() as http:
            scheduler = Scheduler(RateLimits(tpm=500000), FREE, Ledger())
            client = ApiClient(http, loaded, scheduler, Stats())
            await client.complete(build_messages(loaded, row))

    asyncio.run(scenario())
    return seen


# "before sending a request, estimate prompt tokens by counting words in the
#  rendered messages using `1 token ~= 0.75 words`, rounded up"
# "reserve against `estimated_prompt_tokens + max_tokens` before dispatch"
def test_request_reserves_prompt_estimate_plus_max_tokens(cli, api, monkeypatch):
    server = api(answering())
    config = task_config(api_url=server.url, prompt=NO_SYSTEM,
                         generation={"scheme": "greedy", "max_tokens": 256})
    # ceil(5 words / 0.75) == 7, plus the 256 tokens the reply may use
    assert reservations(cli, monkeypatch, config, FIVE_WORD_ROW) == [7 + 256]


# "reserve against `estimated_prompt_tokens + max_tokens` before dispatch" - a
# larger completion budget reserves more
def test_reservation_grows_with_max_tokens(cli, api, monkeypatch):
    server = api(answering())
    config = task_config(api_url=server.url, prompt=NO_SYSTEM,
                         generation={"scheme": "greedy", "max_tokens": 1000})
    assert reservations(cli, monkeypatch, config, FIVE_WORD_ROW) == [7 + 1000]


# "when `tpm` is configured, also enforce a sliding 60-second token budget" - a
# budget with room for the whole run does not slow it down
def test_generous_token_budget_does_not_pace_the_run(cli, api):
    server = api(answering(), delay=0.05)
    config = task_config(api_url=server.url, rpm=600, rate_limits={"tpm": 500000})
    run = cli.run(config, numbered_rows(12))
    assert run.returncode == 0
    assert len(run.rows) == 12
    assert run.summary["elapsed_seconds"] < 30


# "rows are still paired with outputs in input order even when requests overlap;
#  concurrent execution must not cause a later input row to consume the response
#  intended for an earlier row"
def test_rows_keep_their_own_responses_under_a_token_budget(cli, api):
    server = api(answering(), delay=0.02)
    config = task_config(api_url=server.url, rpm=600, rate_limits={"tpm": 500000})
    run = cli.run(config, numbered_rows(15))
    assert run.returncode == 0
    assert [row["input"]["question"] for row in run.rows] == [str(n) for n in range(15)]
    for row in run.rows:
        assert row["output"]["solution"] == f"#### {row['input']['question']}"


# "TPM bottleneck: if `rpm: 600`, `tpm: 10000` ... TPM, not RPM, becomes the
#  binding limit ... the scheduler should pace close to the token budget instead
#  of the higher request budget"
# The window is 60 seconds wide, so the fourth row of this run has to wait for
# the first to age out of it: the whole run therefore takes about a minute.
def test_token_budget_paces_the_run_when_it_binds(cli, api):
    server = api(answering(prompt_tokens=400, completion_tokens=100))
    config = task_config(
        api_url=server.url, rpm=600,
        rate_limits={"tpm": 1200, "max_concurrent": 1},
        generation={"scheme": "greedy", "max_tokens": 100},
    )
    run = cli.run(config, numbered_rows(4))
    assert run.returncode == 0
    assert len(run.rows) == 4
    assert run.summary["elapsed_seconds"] > 50


# "each `llm_judge` call goes through the same limiter"
def test_judge_calls_respect_the_limiter(cli, api):
    from tests.conftest import judge_responder, multi_config

    server = api(judge_responder("A fine answer.", "9"), delay=0.05)
    config = multi_config(
        "review",
        defaults={"api_url": server.url, "rate_limits": {"max_concurrent": 1, "tpm": 500000}},
    )
    rows = [{"prompt_text": f"Describe {index}.", "criteria": "vividness"}
            for index in range(4)]
    run = cli.run_multi(config, {"review": rows})
    assert run.returncode == 0
    # eight requests - one generation and one judge call per row - and never two
    # at a time, which only holds if the judge call is limited as well
    assert len(server.log.calls) == 8
    assert server.log.max_in_flight == 1
