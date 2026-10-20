import pytest

from factory.core import registry
from factory.plugins.builtin.providers_bedrock import BedrockLLM

registry.load_plugins()


class FakeBedrock:
    def __init__(self, response):
        self.response, self.calls = response, []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def reply(*texts):
    return {"output": {"message": {"content": [{"text": t} for t in texts]}}, "stopReason": "end_turn"}


def test_converse_request_and_text_extraction():
    fake = FakeBedrock(reply("FILE: a\n", "x\nEND_FILE"))
    llm = BedrockLLM(model_id="m", max_tokens=100, client=fake)
    assert llm.complete("sys", "hi") == "FILE: a\nx\nEND_FILE"
    call = fake.calls[0]
    assert call["modelId"] == "m" and call["system"] == [{"text": "sys"}]
    assert call["messages"] == [{"role": "user", "content": [{"text": "hi"}]}]
    assert call["inferenceConfig"] == {"maxTokens": 100, "temperature": 0.0}


def test_empty_reply_is_an_error():
    llm = BedrockLLM(model_id="m", client=FakeBedrock(reply()))
    with pytest.raises(RuntimeError, match="no text"):
        llm.complete("s", "p")


def test_registered_and_usable_from_a_workflow_spec():
    assert registry.get("llm", "bedrock") is BedrockLLM


def test_usage_and_cost_are_reported():
    response = {**reply("ok"), "usage": {"inputTokens": 1000, "outputTokens": 500}}
    llm = BedrockLLM(model_id="m", price_per_mtok={"input": 1.0, "output": 5.0}, client=FakeBedrock(response))
    text, usage = llm.complete_ex("s", "p")
    assert text == "ok"
    assert usage == {"input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.0035}


def test_truncated_reply_is_rejected():
    llm = BedrockLLM(model_id="m", client=FakeBedrock({**reply("FILE: a\npartial"), "stopReason": "max_tokens"}))
    with pytest.raises(RuntimeError, match="truncated"):
        llm.complete("s", "p")


def test_missing_boto3_is_a_clear_error_not_a_traceback(monkeypatch):
    import sys

    from factory.core.errors import FactoryError

    monkeypatch.setitem(sys.modules, "boto3", None)  # makes `import boto3` raise ImportError
    with pytest.raises(FactoryError, match=r"minifactory\[aws\]"):
        BedrockLLM(model_id="m").complete("s", "p")
