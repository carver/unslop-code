#!/usr/bin/env python3
"""Mock OpenAI-compatible server used by the test-suite.

Simulates an internal queue: `workers` requests are processed at a time and
each takes `delay` seconds, so sustained capacity is workers/delay*60 rpm.
"""
import argparse
import asyncio
import hashlib
import json
import re
import time

from aiohttp import web

STATE = {"in_flight": 0, "max_in_flight": 0, "calls": 0, "judge_calls": 0,
         "per_prompt": {}, "payloads": [], "completion_calls": 0}

TOOL_RESULT_PATTERNS = [
    re.compile(r"<\|im_start\|>tool\n(.*?)<\|im_end\|>", re.DOTALL),
    re.compile(r"<\|start_header_id\|>tool<\|end_header_id\|>\n\n(.*?)<\|eot_id\|>", re.DOTALL),
    re.compile(r"<\|tool\|>\n(.*?)</s>", re.DOTALL),
    re.compile(r"\[TOOL_RESULTS\] (.*?) \[/TOOL_RESULTS\]", re.DOTALL),
]
TOOL_ROLE_MARKERS = ("<|im_start|>tool", "<|start_header_id|>tool", "<|tool|>",
                     "[TOOL_RESULTS]")


def tool_calls_payload(cfg, round_index):
    """The tool calls one assistant turn should request."""
    values = [v for v in (cfg.tool_arg_values or "").split(",") if v != ""]
    if not values:
        values = [""]
    per_round = max(1, cfg.calls_per_round)
    calls = []
    for i in range(per_round):
        value = values[(round_index * per_round + i) % len(values)]
        calls.append({"name": cfg.tool_name, "arguments": {cfg.tool_arg_key: value}})
    return calls


def wants_tools(cfg, rounds_seen):
    if cfg.always_tools:
        return True
    return rounds_seen < cfg.tool_rounds


async def completions(request):
    cfg = request.app["cfg"]
    body = await request.json()
    messages = body.get("messages", [])
    prompt = json.dumps(messages, sort_keys=True)
    key = hashlib.sha1(prompt.encode()).hexdigest()

    STATE["payloads"].append(body)
    if len(STATE["payloads"]) > 200:
        STATE["payloads"].pop(0)
    STATE["calls"] += 1
    call_index = STATE["calls"]
    seen = STATE["per_prompt"].get(key, 0) + 1
    STATE["per_prompt"][key] = seen

    if cfg.fail_first and call_index <= cfg.fail_first:
        return web.json_response({"error": "boom"}, status=500)
    if cfg.always_500:
        return web.json_response({"error": "boom"}, status=500)
    if cfg.fail_prompt_calls and seen <= cfg.fail_prompt_calls:
        return web.json_response({"error": "boom"}, status=500)
    if cfg.always_400:
        return web.json_response({"error": "bad request"}, status=400)

    async with request.app["sem"]:
        STATE["in_flight"] += 1
        STATE["max_in_flight"] = max(STATE["max_in_flight"], STATE["in_flight"])
        try:
            await asyncio.sleep(cfg.delay)
        finally:
            STATE["in_flight"] -= 1

    user_text = ""
    system_text = ""
    for m in messages:
        if m.get("role") == "user":
            user_text = m.get("content", "")
        elif m.get("role") == "system":
            system_text = m.get("content", "")

    is_judge = bool(cfg.judge_marker and cfg.judge_marker in system_text)
    rounds_seen = sum(1 for m in messages
                      if m.get("role") == "assistant" and m.get("tool_calls"))
    tool_results = [m.get("content", "") for m in messages if m.get("role") == "tool"]
    if not is_judge and (cfg.tool_rounds or cfg.always_tools) and wants_tools(cfg, rounds_seen):
        calls = tool_calls_payload(cfg, rounds_seen)
        return web.json_response({
            "id": "chatcmpl-%d" % call_index,
            "object": "chat.completion",
            "model": body.get("model", "mock"),
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "call_%d_%d" % (call_index, i), "type": "function",
                         "function": {"name": c["name"],
                                      "arguments": json.dumps(c["arguments"])}}
                        for i, c in enumerate(calls)
                    ],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    # A judge request is recognised by a marker in its system prompt so the
    # mock can answer with a score instead of a solution.
    if is_judge:
        STATE["judge_calls"] += 1
        judge_seen = STATE["per_prompt"].get("judge:" + key, 0) + 1
        STATE["per_prompt"]["judge:" + key] = judge_seen
        if judge_seen <= cfg.judge_wrong_attempts:
            content = cfg.judge_wrong_answer
        else:
            content = cfg.judge_answer
    else:
        # `wrong_attempts` responses per distinct prompt are wrong, then correct.
        wrong = seen <= cfg.wrong_attempts
        # `correct_every` makes only every Nth response for a prompt correct.
        if cfg.correct_every:
            wrong = wrong or (seen % cfg.correct_every != 0)
        answer = cfg.wrong_answer if wrong else cfg.answer
        if cfg.answer_from_tools and tool_results:
            answer = tool_results[-1]
        content = cfg.template.format(user=user_text, answer=answer)

    return web.json_response({
        "id": "chatcmpl-%d" % call_index,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "mock"),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    })


async def completions_text(request):
    """`/v1/completions`: a rendered prompt string in, `choices[].text` out."""
    cfg = request.app["cfg"]
    body = await request.json()
    prompt = body.get("prompt", "")
    key = hashlib.sha1(prompt.encode()).hexdigest()

    STATE["payloads"].append(body)
    if len(STATE["payloads"]) > 200:
        STATE["payloads"].pop(0)
    STATE["calls"] += 1
    STATE["completion_calls"] += 1
    call_index = STATE["calls"]
    seen = STATE["per_prompt"].get(key, 0) + 1
    STATE["per_prompt"][key] = seen

    if cfg.fail_first and call_index <= cfg.fail_first:
        return web.json_response({"error": "boom"}, status=500)
    if cfg.always_500:
        return web.json_response({"error": "boom"}, status=500)
    if cfg.always_400:
        return web.json_response({"error": "bad request"}, status=400)

    async with request.app["sem"]:
        STATE["in_flight"] += 1
        STATE["max_in_flight"] = max(STATE["max_in_flight"], STATE["in_flight"])
        try:
            await asyncio.sleep(cfg.delay)
        finally:
            STATE["in_flight"] -= 1

    rounds_seen = (sum(prompt.count(marker) for marker in TOOL_ROLE_MARKERS)
                   // max(1, cfg.calls_per_round))
    results = []
    for pattern in TOOL_RESULT_PATTERNS:
        results += pattern.findall(prompt)
    if (cfg.tool_rounds or cfg.always_tools) and wants_tools(cfg, rounds_seen):
        blocks = ["<tool_call>\n%s\n</tool_call>" % json.dumps(c)
                  for c in tool_calls_payload(cfg, rounds_seen)]
        content = "\n".join(blocks)
    else:
        wrong = seen <= cfg.wrong_attempts
        answer = cfg.wrong_answer if wrong else cfg.answer
        if cfg.answer_from_tools and results:
            answer = results[-1]
        content = cfg.template.format(user=prompt, answer=answer)

    return web.json_response({
        "id": "cmpl-%d" % call_index,
        "object": "text_completion",
        "created": int(time.time()),
        "model": body.get("model", "mock"),
        "choices": [{"index": 0, "text": content, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
    })


async def stats(request):
    return web.json_response(STATE)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8123)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--delay", type=float, default=4.0)
    p.add_argument("--answer", default="42")
    p.add_argument("--wrong-answer", dest="wrong_answer", default="7")
    p.add_argument("--wrong-attempts", dest="wrong_attempts", type=int, default=0)
    p.add_argument("--correct-every", dest="correct_every", type=int, default=0)
    p.add_argument("--fail-first", dest="fail_first", type=int, default=0)
    p.add_argument("--fail-prompt-calls", dest="fail_prompt_calls", type=int, default=0)
    p.add_argument("--always-500", dest="always_500", action="store_true")
    p.add_argument("--always-400", dest="always_400", action="store_true")
    p.add_argument("--template", default="Let me solve it.\nThe result is {answer}\n#### {answer}")
    p.add_argument("--judge-marker", dest="judge_marker", default="JUDGE")
    p.add_argument("--judge-answer", dest="judge_answer", default="8")
    p.add_argument("--judge-wrong-answer", dest="judge_wrong_answer", default="2")
    p.add_argument("--judge-wrong-attempts", dest="judge_wrong_attempts", type=int, default=0)
    p.add_argument("--tool-rounds", dest="tool_rounds", type=int, default=0)
    p.add_argument("--always-tools", dest="always_tools", action="store_true")
    p.add_argument("--calls-per-round", dest="calls_per_round", type=int, default=1)
    p.add_argument("--tool-name", dest="tool_name", default="lookup")
    p.add_argument("--tool-arg-key", dest="tool_arg_key", default="key")
    p.add_argument("--tool-arg-values", dest="tool_arg_values", default="revenue_q1")
    p.add_argument("--answer-from-tools", dest="answer_from_tools", action="store_true")
    cfg = p.parse_args()

    app = web.Application()
    app["cfg"] = cfg
    app["sem"] = asyncio.Semaphore(cfg.workers)
    app.router.add_post("/v1/chat/completions", completions)
    app.router.add_post("/v1/completions", completions_text)
    app.router.add_get("/stats", stats)
    web.run_app(app, port=cfg.port, print=None, access_log=None)


if __name__ == "__main__":
    main()
