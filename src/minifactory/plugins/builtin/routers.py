"""Routers: given free text and the routable workflows, which one fits? (The judgment is the
plugin's; what to do with its confidence is the caller's policy, see factory/router.py.)"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from minifactory.core.errors import RoutingError
from minifactory.core.models import Candidate, Decision
from minifactory.core.registry import register

from .providers_misc import EnvSecrets
from .util import ssl_context

NONE = "none"  # reserved answer: no workflow fits


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-záéíóúñ]+", text.lower()) if len(w) > 2}


@register("router", "keyword")
class KeywordRouter:
    """Deterministic word-overlap router: for tests and offline use, not for quality."""

    def choose(self, request: str, candidates: list[Candidate]) -> Decision:
        words = _words(request)
        scores = {c.name: len(words & _words(" ".join([c.description, *c.examples]))) for c in candidates}
        total = sum(scores.values())
        if total == 0:
            return Decision(choice=None, confidence=1.0, probabilities={NONE: 1.0})
        best = max(scores, key=lambda n: scores[n])
        return Decision(choice=best, confidence=round(scores[best] / total, 3),
                        probabilities={n: round(v / total, 3) for n, v in scores.items()})


Transport = Callable[[dict[str, Any]], dict[str, Any]]


@register("router", "jev")
class JevRouter:
    """TypeSafe's Jev: one request with two judgments over the same state, answered in parallel:
    a Choice (which workflow, or none) and a Noul (is the request actionable as written)."""

    URL = "https://api.typesafe.ai/v1/systemone"

    def __init__(self, secrets: Any = None, model: str = "jev-latest", timeout: int = 30,
                 transport: Transport | None = None):
        self.secrets, self.model, self.timeout = secrets or EnvSecrets(), model, timeout
        self._transport = transport or self._http

    def _http(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            key = self.secrets.get("TYPESAFE_API_KEY")
        except KeyError:
            raise RoutingError("TYPESAFE_API_KEY is not set (get one at https://console.typesafe.ai/)") from None
        req = urllib.request.Request(
            self.URL, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ssl_context()) as resp:
                return json.load(resp)  # type: ignore[no-any-return]
        except urllib.error.HTTPError as e:
            raise RoutingError(f"Jev API error {e.code}: {e.read().decode()[:300]}") from None

    def choose(self, request: str, candidates: list[Candidate]) -> Decision:
        if any(c.name == NONE for c in candidates):
            raise ValueError(f"'{NONE}' is reserved; rename that workflow")
        criteria: dict[str, Any] = {
            c.name: {k: v for k, v in
                     {"what": c.description, "not_for": c.not_for, "examples": c.examples}.items() if v}
            for c in candidates}
        criteria[NONE] = "No workflow fits, or the text is not a request to build or change software."
        # One readiness Noul per workflow, answered in the same request; only the chosen
        # workflow's answer is used (its own `needs`, not a generic notion of "vague").
        questions: dict[str, Any] = {
            "workflow": {"type": "choice", "criteria": criteria,
                         "instructions": "Which workflow should handle the user's request?"}}
        for i, c in enumerate(candidates):
            needs = c.needs or "enough information to start the work without asking the user anything first"
            questions[f"ready_{i}"] = {
                "type": "noul",
                "instructions": f"Does the request contain {needs}?",
                "criteria": {"true": "Yes, it contains that", "false": "No, that is missing"}}
        body = {"model": self.model, "state": {"request": request}, "questions": questions}
        reply = self._transport(body)
        answers = reply["answers"]
        picked = answers["workflow"]
        index = next((i for i, c in enumerate(candidates) if c.name == picked["choice"]), None)
        ready = answers[f"ready_{index}"]["noul"] >= 0.5 if index is not None else True
        return Decision(
            choice=None if picked["choice"] == NONE else picked["choice"],
            confidence=picked["confidence"],
            probabilities=picked["probabilities"],
            actionable=ready,
            usage=reply.get("usage", {}),
        )
