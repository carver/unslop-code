#!/usr/bin/env python3
"""Mock OpenAI-compatible server used by the test-suite.

Simulates an internal queue: `workers` requests are processed at a time and
each takes `delay` seconds, so sustained capacity is workers/delay*60 rpm.
"""
import argparse
import asyncio
import hashlib
import json
import time

from aiohttp import web

STATE = {"in_flight": 0, "max_in_flight": 0, "calls": 0, "judge_calls": 0,
         "per_prompt": {}, "payloads": []}


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

    # A judge request is recognised by a marker in its system prompt so the
    # mock can answer with a score instead of a solution.
    if cfg.judge_marker and cfg.judge_marker in system_text:
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
    cfg = p.parse_args()

    app = web.Application()
    app["cfg"] = cfg
    app["sem"] = asyncio.Semaphore(cfg.workers)
    app.router.add_post("/v1/chat/completions", completions)
    app.router.add_get("/stats", stats)
    web.run_app(app, port=cfg.port, print=None, access_log=None)


if __name__ == "__main__":
    main()
