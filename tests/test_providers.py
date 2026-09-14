"""
The Provider seam: the scripted fake and the DeepSeek adapter's stream handling.

The DeepSeek adapter is tested against a stub of the OpenAI client so that
reasoning/tool-call accumulation is covered without any network.
"""

from types import SimpleNamespace

import pytest

from app.harness.deepseek import DeepSeekProvider
from app.harness.provider import Completed, CompletionRequest, TextDelta, ReasoningDelta, drain
from app.harness.scripted import ScriptedProvider

pytestmark = pytest.mark.unit


# =========================================================================
# ScriptedProvider
# =========================================================================
def test_scripted_provider_streams_text_and_records_the_request():
    p = ScriptedProvider()
    p.script("one two three")
    req = CompletionRequest(model="m", messages=[{"role": "user", "content": "hi"}])

    completion, text = drain(p.complete(req))

    assert text == "one two three" == completion.content
    assert p.requests == [req]


def test_scripted_provider_raises_scripted_exceptions_and_still_records():
    p = ScriptedProvider()
    p.script(RuntimeError("boom"))
    req = CompletionRequest(model="m", messages=[])
    with pytest.raises(RuntimeError):
        list(p.complete(req))
    assert p.requests == [req]


def test_scripted_provider_fails_loudly_when_the_script_runs_out():
    p = ScriptedProvider()
    with pytest.raises(AssertionError, match="script"):
        list(p.complete(CompletionRequest(model="m", messages=[])))


def test_scripted_embeddings_are_deterministic_unit_vectors():
    p = ScriptedProvider(embedding_dim=8)
    a, b = p.embed(["stripe checkout", "stripe checkout"])
    c = p.embed(["stripe billing"])[0]
    assert a == b and a != c and len(a) == 8
    assert sum(x * x for x in a) == pytest.approx(1.0)
    assert p.embed_requests == [["stripe checkout", "stripe checkout"], ["stripe billing"]]


# =========================================================================
# DeepSeekProvider over a stubbed OpenAI client
# =========================================================================
def _chunk(content=None, reasoning=None, tool_calls=None, usage=None, finish=None):
    delta = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish)
    return SimpleNamespace(choices=[choice] if (content or reasoning or tool_calls or finish) else [], usage=usage, model="deepseek-v4-pro")


def _tool_delta(index, id=None, name=None, arguments=None):
    return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=arguments))


class _StubChat:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.chunks)


def _usage(prompt=50, completion=20, reasoning=7, hit=32, miss=18):
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning),
        prompt_cache_hit_tokens=hit, prompt_cache_miss_tokens=miss,
    )


def test_deepseek_adapter_accumulates_text_reasoning_tool_calls_and_usage():
    chat = _StubChat([
        _chunk(reasoning="think "),
        _chunk(reasoning="more"),
        _chunk(content="Hel"),
        _chunk(content="lo"),
        _chunk(tool_calls=[_tool_delta(0, id="call_1", name="get_pricing", arguments='{"pro')]),
        _chunk(tool_calls=[_tool_delta(0, arguments='duct": "Radar"}')]),
        _chunk(finish="tool_calls"),
        _chunk(usage=_usage()),
    ])
    provider = DeepSeekProvider(chat_client=SimpleNamespace(chat=chat), embed_client=None)

    events = list(provider.complete(CompletionRequest(model="deepseek-v4-pro", messages=[{"role": "user", "content": "x"}])))

    assert [e.text for e in events if isinstance(e, ReasoningDelta)] == ["think ", "more"]
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Hel", "lo"]
    completion = events[-1].completion
    assert isinstance(events[-1], Completed)
    assert completion.content == "Hello"
    assert completion.reasoning_content == "think more"
    assert completion.finish_reason == "tool_calls"
    assert [(t.id, t.name, t.arguments) for t in completion.tool_calls] == [("call_1", "get_pricing", '{"product": "Radar"}')]
    assert (completion.usage.prompt_tokens, completion.usage.completion_tokens, completion.usage.reasoning_tokens) == (50, 20, 7)
    assert (completion.usage.cache_hit_tokens, completion.usage.cache_miss_tokens) == (32, 18)


def test_deepseek_adapter_sends_the_request_as_deepseek_expects():
    chat = _StubChat([_chunk(content="ok"), _chunk(finish="stop"), _chunk(usage=_usage())])
    provider = DeepSeekProvider(chat_client=SimpleNamespace(chat=chat), embed_client=None)
    request = CompletionRequest(
        model="deepseek-v4-pro",
        messages=[{"role": "user", "content": "x"}],
        tools=({"type": "function", "function": {"name": "f", "parameters": {}}},),
        max_tokens=123,
        thinking="disabled",
    )

    list(provider.complete(request))

    call = chat.calls[0]
    assert call["model"] == "deepseek-v4-pro"
    assert call["stream"] is True and call["stream_options"] == {"include_usage": True}
    assert call["max_tokens"] == 123
    assert call["tools"] == list(request.tools)
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}


def test_deepseek_clients_give_up_on_a_stalled_request(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    provider = DeepSeekProvider.from_env()
    assert provider._chat.timeout == 180.0 and provider._chat.max_retries == 2
    monkeypatch.setenv("DEEPSEEK_TIMEOUT_SECONDS", "30")
    assert DeepSeekProvider.from_env()._chat.timeout == 30.0


def test_deepseek_adapter_omits_tools_when_there_are_none():
    chat = _StubChat([_chunk(content="ok"), _chunk(finish="stop"), _chunk(usage=_usage())])
    provider = DeepSeekProvider(chat_client=SimpleNamespace(chat=chat), embed_client=None)
    list(provider.complete(CompletionRequest(model="m", messages=[{"role": "user", "content": "x"}])))
    assert "tools" not in chat.calls[0]
