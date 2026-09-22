#!/usr/bin/env python3
"""Mock OpenAI-compatible server used by the test suite.

Models the behaviour described in the spec: requests are queued internally and
each one takes real processing time, so a sequential client leaves capacity
idle. Never returns rate-limit errors.

Env knobs:
  MOCK_PORT        port to bind (default 8000)
  MOCK_RPM         request capacity per minute (default 60)
  MOCK_LATENCY     seconds of processing per request (default 2.0)
  MOCK_MODE        answer | wrong | fail_first_k | flaky5xx | always5xx
  MOCK_K           k for fail_first_k (default 2)
  MOCK_5XX_N       number of 5xx responses before success (flaky5xx)

Two scripted replies make multi-task/judge/script tests easy to write:

  "... ECHO:<text>"          -> the reply is <text> (everything after ECHO:)
  "... ECHO_SEQ:<a>|<b>|..." -> the reply is the nth alternative, where n counts
                               how many times this exact prompt has been seen
                               (the last alternative repeats)
"""

import asyncio
import json
import os
import re
import time
from collections import defaultdict

from aiohttp import web

RPM = float(os.environ.get("MOCK_RPM", "60"))
LATENCY = float(os.environ.get("MOCK_LATENCY", "2.0"))
MODE = os.environ.get("MOCK_MODE", "answer")
K = int(os.environ.get("MOCK_K", "2"))
FIVEXX_N = int(os.environ.get("MOCK_5XX_N", "2"))

# Concurrency that yields exactly RPM throughput at LATENCY seconds each.
CAPACITY = max(1, int(round(RPM * LATENCY / 60.0)))

STATE = {"calls": 0, "max_inflight": 0, "inflight": 0, "first": None, "last": None}
REQUESTS = []
PER_PROMPT = defaultdict(int)
SEM = None
LOCK = None


def solve(question):
    """Answer the toy arithmetic questions used in the tests."""
    numbers = [int(x) for x in re.findall(r"-?\d+", question)]
    if "+" in question or "buys" in question or "more" in question:
        return sum(numbers) if numbers else 0
    if "travels" in question and "hours" in question:
        return numbers[0] // numbers[1] if len(numbers) >= 2 else 0
    if "*" in question or "times" in question:
        result = 1
        for number in numbers:
            result *= number
        return result
    return numbers[-1] if numbers else 0


async def handler(request):
    global SEM, LOCK
    body = await request.json()
    messages = body.get("messages", [])
    user = ""
    for message in messages:
        if message.get("role") == "user":
            user = message.get("content", "")

    async with LOCK:
        STATE["calls"] += 1
        REQUESTS.append({"model": body.get("model"), "messages": messages,
                         "max_tokens": body.get("max_tokens"),
                         "temperature": body.get("temperature")})
        call_index = STATE["calls"]
        PER_PROMPT[user] += 1
        prompt_index = PER_PROMPT[user]
        if STATE["first"] is None:
            STATE["first"] = time.monotonic()

    if MODE == "always5xx":
        return web.json_response({"error": "boom"}, status=503)
    if MODE == "flaky5xx" and prompt_index <= FIVEXX_N:
        return web.json_response({"error": "boom"}, status=500)

    async with SEM:
        STATE["inflight"] += 1
        STATE["max_inflight"] = max(STATE["max_inflight"], STATE["inflight"])
        try:
            await asyncio.sleep(LATENCY)
        finally:
            STATE["inflight"] -= 1
    STATE["last"] = time.monotonic()

    scripted = scripted_reply(user, prompt_index)
    if scripted is not None:
        return reply(body, call_index, scripted)

    answer = solve(user)
    if MODE == "wrong":
        answer = answer + 1000
    elif MODE == "fail_first_k" and prompt_index <= K:
        answer = answer + 1000

    content = "Let me solve this step by step.\nWorking it out.\n#### %d" % answer

    return reply(body, call_index, content)


def scripted_reply(user, prompt_index):
    """ECHO: / ECHO_SEQ: replies scripted by the prompt itself."""
    if "ECHO_SEQ:" in user:
        options = user.split("ECHO_SEQ:", 1)[1].split("|")
        return options[min(prompt_index - 1, len(options) - 1)]
    if "ECHO:" in user:
        return user.split("ECHO:", 1)[1]
    return None


def reply(body, call_index, content):
    return web.json_response(
        {
            "id": "chatcmpl-%d" % call_index,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", "mock"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 45,
                "completion_tokens": 120,
                "total_tokens": 165,
            },
        }
    )


async def requests_log(request):
    return web.json_response(REQUESTS)


async def stats(request):
    elapsed = 0.0
    if STATE["first"] and STATE["last"]:
        elapsed = STATE["last"] - STATE["first"]
    return web.json_response(
        {
            "calls": STATE["calls"],
            "max_inflight": STATE["max_inflight"],
            "capacity": CAPACITY,
            "elapsed": elapsed,
        }
    )


async def init(app):
    global SEM, LOCK
    SEM = asyncio.Semaphore(CAPACITY)
    LOCK = asyncio.Lock()


def main():
    app = web.Application()
    app.on_startup.append(init)
    app.router.add_post("/v1/chat/completions", handler)
    app.router.add_get("/stats", stats)
    app.router.add_get("/requests", requests_log)
    web.run_app(app, host="127.0.0.1", port=int(os.environ.get("MOCK_PORT", "8000")), print=None)


if __name__ == "__main__":
    main()
