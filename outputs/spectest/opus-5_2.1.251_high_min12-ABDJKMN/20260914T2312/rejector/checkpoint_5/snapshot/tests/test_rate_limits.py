"""Scheduling behaviour from the Rate Limits section."""

import math
import threading
import time

import pytest

import fake_api


def small_tokens(content="#### 5", **kw):
    kw.setdefault("prompt_tokens", 1)
    kw.setdefault("completion_tokens", 1)
    return fake_api.always(content, **kw)


def spawn(fn):
    done = []

    def target():
        fn()
        done.append(True)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, done


# ---------------------------------------------------------------------------
# Spec: "continue to enforce RPM, now using a sliding 60-second window"
# Context: Rate Limits.  With rpm=3 a fourth request waits until the oldest of
# the three leaves the 60-second window.
# ---------------------------------------------------------------------------
def test_rpm_uses_a_sliding_60_second_window(rejector, fake_clock):
    clock = fake_clock()
    limiter = rejector.RateLimiter(rpm=3, tpm=None, max_concurrent=None,
                                   clock=clock)
    for _ in range(3):
        limiter.acquire(0)

    thread, done = spawn(lambda: limiter.acquire(0))
    thread.join(0.3)
    assert not done, "a 4th request went out while 3 were inside the window"

    clock.advance(59.0)
    thread.join(0.2)
    assert not done, "the window is 60 seconds, not 59"

    clock.advance(1.5)
    thread.join(3.0)
    assert done, "the request never went out after the window slid"


# ---------------------------------------------------------------------------
# Spec: "continue to enforce RPM" -- requests inside the window are not
# delayed.
# Context: Rate Limits.  rpm=100 admits 100 requests without blocking.
# ---------------------------------------------------------------------------
def test_rpm_admits_up_to_the_configured_rate(rejector, fake_clock):
    limiter = rejector.RateLimiter(rpm=100, tpm=None, max_concurrent=None,
                                   clock=fake_clock())
    started = time.time()
    for _ in range(100):
        limiter.acquire(0)
    assert time.time() - started < 2.0


# ---------------------------------------------------------------------------
# Spec: "if `rpm` is omitted, RPM limiting is disabled for that task"
# Context: Rate Limits.  No rpm means no window bookkeeping blocks anything.
# ---------------------------------------------------------------------------
def test_no_rpm_never_blocks(rejector, fake_clock):
    limiter = rejector.RateLimiter(rpm=None, tpm=None, max_concurrent=None,
                                   clock=fake_clock())
    for _ in range(500):
        limiter.acquire(10)


# ---------------------------------------------------------------------------
# Spec: "before sending a request, estimate prompt tokens by counting words in
#        the rendered messages using `1 token ~= 0.75 words`, rounded up"
# Context: Rate Limits.  9 words -> ceil(9 / 0.75) = 12 tokens.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("words,expected", [
    (9, 12),
    (1, 2),
    (3, 4),
    (0, 0),
    (100, 134),
])
def test_prompt_token_estimate_from_word_count(rejector, words, expected):
    messages = [{"role": "user", "content": " ".join(["word"] * words)}]
    assert rejector.estimate_prompt_tokens(messages) == expected
    assert expected == math.ceil(words / 0.75)


# ---------------------------------------------------------------------------
# Spec: "estimate prompt tokens by counting words in the rendered messages"
# Context: Rate Limits.  Every message in the conversation contributes.
# ---------------------------------------------------------------------------
def test_prompt_token_estimate_spans_all_messages(rejector):
    messages = [{"role": "system", "content": "a b c"},
                {"role": "user", "content": "d e f"}]
    assert rejector.estimate_prompt_tokens(messages) == math.ceil(6 / 0.75)


# ---------------------------------------------------------------------------
# Spec: "reserve against `estimated_prompt_tokens + max_tokens` before dispatch"
# Context: Rate Limits.  A 100-token window admits one 60-token reservation
# but not two.
# ---------------------------------------------------------------------------
def test_tpm_reserves_before_dispatch(rejector, fake_clock):
    limiter = rejector.RateLimiter(rpm=None, tpm=100, max_concurrent=None,
                                   clock=fake_clock())
    limiter.acquire(60)
    thread, done = spawn(lambda: limiter.acquire(60))
    thread.join(0.3)
    assert not done, "two 60-token reservations fit in a 100-token window"


# ---------------------------------------------------------------------------
# Spec: "after the response arrives, record actual `prompt_tokens +
#        completion_tokens` from the API response in the TPM window"
# Context: Rate Limits.  Recording a smaller actual frees the difference.
# ---------------------------------------------------------------------------
def test_actual_usage_replaces_the_reservation(rejector, fake_clock):
    limiter = rejector.RateLimiter(rpm=None, tpm=100, max_concurrent=None,
                                   clock=fake_clock())
    first = limiter.acquire(60)
    thread, done = spawn(lambda: limiter.acquire(60))
    thread.join(0.2)
    assert not done

    limiter.record(first, 10)       # the request really used 10 tokens
    thread.join(3.0)
    assert done, "60 + 10 fits in a 100-token window once actuals are known"


# ---------------------------------------------------------------------------
# Spec: "when `tpm` is configured, also enforce a sliding 60-second token
#        budget"
# Context: Rate Limits.  Recorded tokens leave the window after 60 seconds.
# ---------------------------------------------------------------------------
def test_tpm_window_slides(rejector, fake_clock):
    clock = fake_clock()
    limiter = rejector.RateLimiter(rpm=None, tpm=100, max_concurrent=None,
                                   clock=clock)
    limiter.record(limiter.acquire(90), 90)
    thread, done = spawn(lambda: limiter.acquire(90))
    thread.join(0.2)
    assert not done
    clock.advance(61)
    thread.join(3.0)
    assert done


# ---------------------------------------------------------------------------
# Spec: "if both RPM and TPM are configured, a request may be sent only when
#        both budgets have capacity"
# Context: Rate Limits.  RPM capacity alone is not enough.
# ---------------------------------------------------------------------------
def test_both_budgets_must_have_capacity(rejector, fake_clock):
    limiter = rejector.RateLimiter(rpm=1000, tpm=100, max_concurrent=None,
                                   clock=fake_clock())
    limiter.acquire(90)
    thread, done = spawn(lambda: limiter.acquire(90))
    thread.join(0.3)
    assert not done, "RPM had room but TPM did not"


def test_both_budgets_must_have_capacity_rpm_side(rejector, fake_clock):
    limiter = rejector.RateLimiter(rpm=1, tpm=1000000, max_concurrent=None,
                                   clock=fake_clock())
    limiter.acquire(10)
    thread, done = spawn(lambda: limiter.acquire(10))
    thread.join(0.3)
    assert not done, "TPM had room but RPM did not"


# ---------------------------------------------------------------------------
# Spec: "TPM bottleneck: if `rpm: 600`, `tpm: 10000`, and a typical request
#        consumes about 612 tokens ... the scheduler should pace close to the
#        token budget instead of the higher request budget"
# Context: Rate Limits.  16 requests of 612 tokens fit in 10000; the 17th does
# not.
# ---------------------------------------------------------------------------
def test_tpm_is_the_binding_limit(rejector, fake_clock):
    limiter = rejector.RateLimiter(rpm=600, tpm=10000, max_concurrent=None,
                                   clock=fake_clock())
    for _ in range(16):
        limiter.record(limiter.acquire(612), 612)
    thread, done = spawn(lambda: limiter.acquire(612))
    thread.join(0.3)
    assert not done, "paced on rpm=600 instead of tpm=10000"


# ---------------------------------------------------------------------------
# Spec: "max_concurrent is a hard cap on in-flight requests"
# Context: Rate Limits.  The limiter hands out exactly that many slots.
# ---------------------------------------------------------------------------
def test_max_concurrent_slots_are_bounded(rejector, fake_clock):
    limiter = rejector.RateLimiter(rpm=None, tpm=None, max_concurrent=2,
                                   clock=fake_clock())
    held = [limiter.slot(), limiter.slot()]
    for slot in held:
        slot.__enter__()
    thread, done = spawn(lambda: limiter.slot().__enter__())
    thread.join(0.3)
    assert not done
    held[0].__exit__(None, None, None)
    thread.join(3.0)
    assert done


# ---------------------------------------------------------------------------
# Spec: "a request may be sent only when both budgets have capacity" -- a
# reservation bigger than the whole window must not deadlock.
# Context: Rate Limits.  An empty window always admits one request.
# ---------------------------------------------------------------------------
def test_oversized_reservation_still_goes_out(rejector, fake_clock):
    limiter = rejector.RateLimiter(rpm=None, tpm=10, max_concurrent=None,
                                   clock=fake_clock())
    thread, done = spawn(lambda: limiter.acquire(5000))
    thread.join(3.0)
    assert done


# ---------------------------------------------------------------------------
# Spec: "rows are still paired with outputs in input order even when requests
#        overlap; concurrent execution must not cause a later input row to
#        consume the response intended for an earlier row"
# Context: Rate Limits.  Responses that finish out of order stay paired.
# ---------------------------------------------------------------------------
def test_rows_stay_paired_when_requests_overlap(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(12)]

    def responder(rec):
        # Later rows answer first, so completion order reverses arrival order.
        index = int(rec.user_content.replace("q", ""))
        time.sleep(0.02 * (12 - index))
        return 200, fake_api.completion(rec.user_content, prompt_tokens=1,
                                        completion_tokens=1)

    with fake_api.FakeAPI(responder) as api:
        res = run_task(api,
                       task={"evaluation": None,
                             "rate_limits": {"rpm": 600, "max_concurrent": 12}},
                       rows=rows, check=0)
    assert api.max_inflight > 1
    assert [r["output"]["solution"] for r in res.rows] == \
           ["q%d" % i for i in range(12)]
    assert [r["input"]["question"] for r in res.rows] == \
           ["q%d" % i for i in range(12)]


# ---------------------------------------------------------------------------
# Spec: "each `llm_judge` call goes through the same limiter"
# Context: Rate Limits.  With one concurrency slot the judge call cannot run
# alongside a generation call.
# ---------------------------------------------------------------------------
def test_judge_calls_go_through_the_limiter(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(4)]
    judge = fake_api.dispatch(
        lambda rec: "Rate" in (rec.system_content or ""),
        fake_api.always("0.9", prompt_tokens=1, completion_tokens=1),
        fake_api.always("#### 5", prompt_tokens=1, completion_tokens=1))
    with fake_api.FakeAPI(judge, latency=0.05) as api:
        res = run_task(api,
                       task={"rate_limits": {"max_concurrent": 1},
                             "evaluation": {
                                 "type": "llm_judge",
                                 "answer_field": None, "extract": None,
                                 "judge_prompt": {
                                     "system": "Rate the answer 0..1.",
                                     "user": "{question} -> {__response__}"},
                                 "threshold": 0.5}},
                       rows=rows, check=0)
    assert api.max_inflight == 1
    assert api.call_count == 8       # one generation + one judge call per row


# ---------------------------------------------------------------------------
# Spec: "for agentic loops, every API request counts toward RPM and TPM, and
#        the loop holds one concurrency slot for its entire lifetime"
# Context: Rate Limits.  max_concurrent=1 serialises whole loops, so one row's
# requests never interleave with another's.
# ---------------------------------------------------------------------------
def test_agentic_loop_holds_one_slot_for_its_lifetime(run_agentic):
    rows = [{"question": "revenue_q1 for %s?" % name, "answer": "1250000"}
            for name in ("a", "b", "c")]
    script = [fake_api.calls(("lookup", {"key": "revenue_q1"}),
                             prompt_tokens=1, completion_tokens=1),
              fake_api.final("#### 1250000", prompt_tokens=1,
                             completion_tokens=1)]
    with fake_api.FakeAPI(fake_api.agentic(script), latency=0.05) as api:
        run_agentic(api, task={"rate_limits": {"max_concurrent": 1}},
                    rows=rows, check=0)
    assert api.max_inflight == 1
    keys = [rec.row_key for rec in api.requests]
    # Each row's requests form one contiguous block.
    assert len(keys) == 6
    blocks = [k for i, k in enumerate(keys) if i == 0 or keys[i - 1] != k]
    assert len(blocks) == len(set(blocks))


# ---------------------------------------------------------------------------
# Spec: "for agentic loops, every API request counts toward RPM and TPM"
# Context: Rate Limits.  Each iteration is admitted separately.
# ---------------------------------------------------------------------------
def test_every_agentic_iteration_counts_toward_the_window(run_agentic):
    script = [fake_api.calls(("lookup", {"key": "revenue_q1"}),
                             prompt_tokens=1, completion_tokens=1),
              fake_api.calls(("lookup", {"key": "revenue_q2"}),
                             prompt_tokens=1, completion_tokens=1),
              fake_api.final("#### 2730000", prompt_tokens=1,
                             completion_tokens=1)]
    with fake_api.FakeAPI(fake_api.agentic(script)) as api:
        res = run_agentic(api, task={"rate_limits": {"rpm": 3}}, check=0)
    assert api.call_count == 3
    assert res.summary["total_api_calls"] == 3
