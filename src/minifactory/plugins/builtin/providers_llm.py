"""LLM providers. `openai` is the real thing (any OpenAI-compatible gateway, like your
LiteLLM one); `scripted` is a deterministic fake so you can test the whole factory
offline, with no tokens and no flakiness."""

from __future__ import annotations

import json
import re
import threading
import urllib.request
from collections import defaultdict
from pathlib import Path

from minifactory.core.registry import register

from .util import ssl_context


def _edit(path: str, content: str) -> str:
    return f"FILE: {path}\n{content}\nEND_FILE"


@register("llm", "scripted")
class ScriptedLLM:
    """Rule-based stand-in. Understands exactly two tasks, on a `build.cfg` file:
    migrate (sets java_version) and repair (drops an option the build rejects)."""

    def complete(self, system: str, prompt: str) -> str:
        files = dict(re.findall(r"=== FILE (\S+) ===\n(.*?)\n=== END ===", prompt, re.DOTALL))
        cfg = files.get("build.cfg")
        if cfg is None:
            return "I could not find a file I know how to change."
        if "TASK: migrate" in prompt:
            m = re.search(r"TARGET java_version=(\d+)", prompt)
            if m:
                return _edit("build.cfg",
                             re.sub(r"(?m)^java_version=.*$", f"java_version={m.group(1)}", cfg))
        if "TASK: repair" in prompt:
            m = re.search(r"unsupported option '(\w+)'", prompt)
            if m:
                kept = [ln for ln in cfg.splitlines() if not ln.startswith(m.group(1) + "=")]
                return _edit("build.cfg", "\n".join(kept))
        return "I do not know how to fix this."


def _field(prompt: str, key: str) -> str | None:
    m = re.search(rf"^{key}: (.+)$", prompt, re.MULTILINE)
    return m.group(1).strip() if m else None


@register("llm", "fixture")
class FixtureLLM:
    """Replays canned replies from `<path>/<app>/`, so a whole app can be 'generated' offline.

        plan.json              reply to TASK: plan_app
        implement/<feature>.txt  reply to TASK: implement (FEATURE: <feature>)
        repair/<n>.txt         reply to the n-th TASK: repair call for that app (1-based)
    """

    def __init__(self, path: str):
        self.root = Path(path)
        self._repairs: defaultdict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def _read(self, *parts: str) -> str:
        target = self.root.joinpath(*parts)
        return target.read_text() if target.is_file() else f"No fixture at {target}"

    def complete(self, system: str, prompt: str) -> str:
        app, task = _field(prompt, "APP"), _field(prompt, "TASK")
        if not app or not task:
            return "Prompt has no APP/TASK header."
        if task == "plan_app":
            return self._read(app, "plan.json")
        if task == "implement":
            return self._read(app, "implement", f"{_field(prompt, 'FEATURE')}.txt")
        if task == "repair":
            with self._lock:
                self._repairs[app] += 1
                n = self._repairs[app]
            return self._read(app, "repair", f"{n}.txt")
        return f"Unknown task {task}."


@register("llm", "openai")
class OpenAICompatLLM:
    """POST {base_url}/chat/completions. The API key comes from the secrets port, which is
    where your cross-account STS assume-role logic would live (as a `secrets` plugin)."""

    def __init__(self, base_url: str, model: str, api_key_secret: str = "LLM_API_KEY",
                 timeout: int = 120, secrets=None):
        self.base_url, self.model = base_url.rstrip("/"), model
        self.api_key_secret, self.timeout, self.secrets = api_key_secret, timeout, secrets

    def complete(self, system: str, prompt: str) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.secrets.get(self.api_key_secret)}"})
        with urllib.request.urlopen(req, timeout=self.timeout, context=ssl_context()) as resp:
            return json.load(resp)["choices"][0]["message"]["content"]
