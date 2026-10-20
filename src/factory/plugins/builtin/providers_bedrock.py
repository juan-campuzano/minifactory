"""Amazon Bedrock LLM provider (Converse API). `boto3` is imported lazily, so the rest of
the factory works without it: `pip install -e ".[aws]"` when you want this provider."""

from __future__ import annotations

import threading
from typing import Any

from factory.core.errors import FactoryError
from factory.core.registry import register


@register("llm", "bedrock")
class BedrockLLM:
    """Credentials come from the normal AWS chain (env, `profile`, SSO...). With `role_arn`
    the provider first assumes that role (e.g. a cross-account "IA" role).

    `price_per_mtok` ({input, output}, USD per 1M tokens) is optional: when given, every call
    reports `cost_usd`. Prices are yours to set; nothing is hardcoded because they change.

    `client` is for tests: any object with a boto3-style `converse(**kwargs)`."""

    def __init__(self, model_id: str, region: str | None = None, profile: str | None = None,
                 role_arn: str | None = None, max_tokens: int = 4096, temperature: float = 0.0,
                 price_per_mtok: dict[str, float] | None = None, client: Any = None):
        self.model_id, self.region, self.profile, self.role_arn = model_id, region, profile, role_arn
        self.max_tokens, self.temperature = max_tokens, temperature
        self.price = price_per_mtok  # {"input": usd, "output": usd} per 1M tokens, set by you
        self._client = client
        self._lock = threading.Lock()

    def _get_client(self) -> Any:
        with self._lock:
            if self._client is None:
                self._client = self._build_client()
            return self._client

    def _build_client(self) -> Any:
        try:
            import boto3  # lazy: optional dependency
        except ImportError:
            raise FactoryError("the bedrock LLM needs boto3: pip install 'minifactory[aws]'") from None

        session = boto3.Session(profile_name=self.profile, region_name=self.region)
        if self.role_arn:
            creds = session.client("sts").assume_role(
                RoleArn=self.role_arn, RoleSessionName="minifactory")["Credentials"]
            session = boto3.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
                region_name=self.region or session.region_name)
        return session.client("bedrock-runtime")

    def complete(self, system: str, prompt: str) -> str:
        return self.complete_ex(system, prompt)[0]

    def complete_ex(self, system: str, prompt: str) -> tuple[str, dict[str, Any]]:
        response = self._get_client().converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": self.temperature},
        )
        if response.get("stopReason") == "max_tokens":  # a cut-off file must never reach the repo
            raise RuntimeError(f"reply truncated at max_tokens={self.max_tokens}; raise it")
        parts = response["output"]["message"]["content"]
        text = "".join(part.get("text", "") for part in parts)
        if not text:
            raise RuntimeError(f"Bedrock returned no text (stopReason={response.get('stopReason')})")
        raw = response.get("usage", {})
        usage: dict[str, Any] = {"input_tokens": raw.get("inputTokens", 0),
                                 "output_tokens": raw.get("outputTokens", 0)}
        if self.price:
            usage["cost_usd"] = round((usage["input_tokens"] * self.price["input"]
                                       + usage["output_tokens"] * self.price["output"]) / 1e6, 6)
        return text, usage
