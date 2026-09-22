#!/usr/bin/env python3
"""Mock OpenAI-compatible server used by the test suite.

Models the behaviour described in the spec: requests are queued internally and
each one takes real processing time, so a sequential client leaves capacity
idle. Never returns rate-limit errors. Serves both `/v1/chat/completions` and
`/v1/completions`.

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

A scripted reply of the form

  "TOOLCALL:<name>:<json args>"           (join several with '&&')

becomes a tool-call response instead of a text reply: native `tool_calls` on
`/v1/chat/completions`, a `<tool_call>` block on `/v1/completions`. The token
LASTTOOL inside a scripted reply expands to the tool results already present in
the conversation, so a test can prove they were fed back.
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

# Last user turn, per built-in chat template.
USER_TURN_RES = [
    re.compile(r"<\|im_start\|>user\n(.*?)<\|im_end\|>", re.DOTALL),
    re.compile(
        r"<\|start_header_id\|>user<\|end_header_id\|>\n\n(.*?)<\|eot_id\|>", re.DOTALL
    ),
    re.compile(r"<\|user\|>\n(.*?)</s>", re.DOTALL),
    re.compile(r"\[INST\] (.*?) \[/INST\]", re.DOTALL),
]

# Tool results already fed back into a rendered prompt.
TOOL_TURN_RES = [
    re.compile(r"<\|im_start\|>tool\n(.*?)<\|im_end\|>", re.DOTALL),
    re.compile(
        r"<\|start_header_id\|>tool<\|end_header_id\|>\n\n(.*?)<\|eot_id\|>", re.DOTALL
    ),
    re.compile(r"<\|tool\|>\n(.*?)</s>", re.DOTALL),
    re.compile(r"\[TOOL_RESULTS\] (.*?) \[/TOOL_RESULTS\]", re.DOTALL),
]

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


def last_user_turn(prompt):
    """The final user turn inside a rendered completions prompt.

    Templates without a tool role (mistral) fold tool results into an [INST]
    block, so those blocks are skipped: the row's own question is what
    identifies the conversation.
    """
    for pattern in USER_TURN_RES:
        found = [turn for turn in pattern.findall(prompt) if "[TOOL_RESULTS]" not in turn]
        if found:
            return found[-1]
    return prompt


def tool_results(messages, prompt):
    """Every tool result seen so far, in order."""
    if messages:
        return [
            m.get("content", "") for m in messages if m.get("role") == "tool"
        ]
    results = []
    for pattern in TOOL_TURN_RES:
        results.extend(pattern.findall(prompt))
    return results


def prompt_key(user):
    """Group requests that belong to the same input row.

    The user turn is stable across the iterations of one agentic loop, so it
    doubles as the row identity that ECHO_SEQ steps through.
    """
    return user


async def chat_handler(request):
    return await dispatch(request, "chat")


async def completions_handler(request):
    return await dispatch(request, "completions")


async def dispatch(request, api):
    global SEM, LOCK
    body = await request.json()
    messages = body.get("messages") or []
    prompt = body.get("prompt") or ""

    if api == "completions":
        user = last_user_turn(prompt)
    else:
        user = ""
        for message in messages:
            if message.get("role") == "user":
                user = message.get("content", "")

    async with LOCK:
        STATE["calls"] += 1
        REQUESTS.append({"model": body.get("model"), "messages": messages,
                         "prompt": prompt, "api": api,
                         "tools": body.get("tools"),
                         "max_tokens": body.get("max_tokens"),
                         "temperature": body.get("temperature")})
        call_index = STATE["calls"]
        key = prompt_key(user)
        PER_PROMPT[key] += 1
        prompt_index = PER_PROMPT[key]
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
        scripted = scripted.replace("LASTTOOL", ", ".join(tool_results(messages, prompt)))
        calls = parse_tool_directives(scripted)
        if calls:
            return tool_reply(body, call_index, calls, api)
        return reply(body, call_index, scripted, api)

    answer = solve(user)
    if MODE == "wrong":
        answer = answer + 1000
    elif MODE == "fail_first_k" and prompt_index <= K:
        answer = answer + 1000

    content = "Let me solve this step by step.\nWorking it out.\n#### %d" % answer

    return reply(body, call_index, content, api)


def scripted_reply(user, prompt_index):
    """ECHO: / ECHO_SEQ: replies scripted by the prompt itself."""
    if "ECHO_SEQ:" in user:
        options = user.split("ECHO_SEQ:", 1)[1].split("|")
        return options[min(prompt_index - 1, len(options) - 1)]
    if "ECHO:" in user:
        return user.split("ECHO:", 1)[1]
    return None


def parse_tool_directives(text):
    """Turn 'TOOLCALL:<name>:<json>' directives into (name, arguments) pairs."""
    calls = []
    for part in text.split("&&"):
        part = part.strip()
        if not part.startswith("TOOLCALL:"):
            return []
        rest = part[len("TOOLCALL:"):]
        name, _, arguments = rest.partition(":")
        calls.append((name.strip(), arguments.strip() or "{}"))
    return calls


def usage():
    return {"prompt_tokens": 45, "completion_tokens": 120, "total_tokens": 165}


def tool_reply(body, call_index, calls, api):
    if api == "completions":
        blocks = []
        for index, (name, arguments) in enumerate(calls):
            try:
                parsed = json.loads(arguments)
            except ValueError:
                parsed = {}
            blocks.append(
                "<tool_call>\n%s\n</tool_call>"
                % json.dumps({"name": name, "arguments": parsed})
            )
        return reply(body, call_index, "\n".join(blocks), api, finish="tool_calls")

    tool_calls = [
        {
            "id": "call_%d_%d" % (call_index, index),
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        }
        for index, (name, arguments) in enumerate(calls)
    ]
    return web.json_response(
        {
            "id": "chatcmpl-%d" % call_index,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", "mock"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": tool_calls,
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": usage(),
        }
    )


def reply(body, call_index, content, api="chat", finish="stop"):
    if api == "completions":
        return web.json_response(
            {
                "id": "cmpl-%d" % call_index,
                "object": "text_completion",
                "created": int(time.time()),
                "model": body.get("model", "mock"),
                "choices": [{"index": 0, "text": content, "finish_reason": finish}],
                "usage": usage(),
            }
        )
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
                    "finish_reason": finish,
                }
            ],
            "usage": usage(),
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
    app.router.add_post("/v1/chat/completions", chat_handler)
    app.router.add_post("/v1/completions", completions_handler)
    app.router.add_get("/stats", stats)
    app.router.add_get("/requests", requests_log)
    web.run_app(app, host="127.0.0.1", port=int(os.environ.get("MOCK_PORT", "8000")), print=None)


if __name__ == "__main__":
    main()
