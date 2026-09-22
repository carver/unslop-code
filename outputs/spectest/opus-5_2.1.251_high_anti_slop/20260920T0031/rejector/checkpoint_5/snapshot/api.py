"""Async client for an OpenAI-compatible API, with request pacing, retries and billing.

The request and response shapes belong to the task's `Endpoint`; this module
only decides when a request may go out, how often it is retried, and what the
run counts and charges it as.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from cost import CostConfig
from endpoints import Completion, Endpoint
from limits import RequestLimiter, Reservation, estimate_tokens
from templates import Message
from tools import Tool
from tracking import RunMetrics

REQUEST_TIMEOUT_SECONDS = 300.0
#: Retries attempted after an initial HTTP 5xx before a row is given up on.
MAX_RETRIES = 3


class ApiClient:
    """Sends one task's requests, pacing them, retrying server errors and billing them.

    Counts every HTTP request made, retries included, which is what the summary
    reports as the task's API calls.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        limiter: RequestLimiter,
        metrics: RunMetrics,
        endpoint: Endpoint,
        cost: CostConfig | None = None,
    ) -> None:
        self._http = http
        self._limiter = limiter
        self._metrics = metrics
        self._endpoint = endpoint
        self._cost = cost
        self.api_calls = 0

    async def complete(
        self,
        messages: Sequence[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        tools: Sequence[Tool] = (),
    ) -> Completion | None:
        """Generate one completion, or None once the retry budget or the run's budget is spent."""
        if self._metrics.cost.exhausted:
            return None

        payload = self._endpoint.payload(messages, model, temperature, max_tokens, tools)
        expected = estimate_tokens(messages) + max_tokens
        for _ in range(MAX_RETRIES + 1):
            reservation = await self._limiter.reserve(expected)
            response, latency_ms = await self._post(payload)
            if not response.is_server_error:
                response.raise_for_status()
                completion = self._endpoint.completion(response.json(), model, latency_ms)
                self._settle(completion, reservation)
                return completion
        return None

    async def _post(self, payload: dict[str, Any]) -> tuple[httpx.Response, int]:
        self.api_calls += 1
        started = self._metrics.request()
        response = await self._http.post(self._endpoint.path, json=payload)
        return response, round((self._metrics.timeline.finished() - started) * 1000)

    def _settle(self, completion: Completion, reservation: Reservation) -> None:
        """Replace the token reservation with what the response reports, and bill it."""
        prompt_tokens = completion.meta["prompt_tokens"]
        completion_tokens = completion.meta["completion_tokens"]
        reservation.settle(prompt_tokens + completion_tokens)
        self._metrics.cost.record(self._cost, prompt_tokens, completion_tokens)
