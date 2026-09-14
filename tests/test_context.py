"""
Context pressure, relieved in tiers (ADR 0006).

Limits at the source first — a long customer message becomes an Attachment
the model reads in pieces, and a turn's tool results are capped in total —
then clearing of spent tool results into stubs, then Compaction: triggered
by the previous response's reported prompt tokens at the high-water mark,
compacting to the low-water mark with one rolling summary and a verbatim
recent window. The static prefix never changes.
"""

import json
from dataclasses import replace

import pytest

from app import database
from app.harness.core import HarnessConfig
from app.harness.provider import Completion, ToolCall, Usage
from tests.conftest import chat as _chat
from tests.conftest import first_customer

pytestmark = pytest.mark.unit

# Small thresholds so a handful of short messages exercise every tier.
SMALL = HarnessConfig(
    attachment_threshold_chars=500,
    turn_result_budget_chars=2000,
    context_budget_tokens=10_000,  # high water 7,500 tokens; low water 4,000
    high_water=0.75,
    low_water=0.40,
    summary_max_tokens=200,  # ≈ 800 characters
    recent_window_tokens=300,  # ≈ 1,200 characters kept verbatim
)
small = pytest.mark.parametrize("harness_config", [SMALL], indirect=True)
# The same, without the turn budget in the way, for tests that read attachments in large pieces.
roomy = pytest.mark.parametrize("harness_config", [replace(SMALL, turn_result_budget_chars=100_000)], indirect=True)


def _calls(*specs):
    return Completion(
        content="", finish_reason="tool_calls",
        tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=json.dumps(a)) for i, (n, a) in enumerate(specs)),
    )


def _reply(text, prompt_tokens):
    """A final reply whose response reports `prompt_tokens` — what the next turn's relief decisions read."""
    return Completion(content=text, usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=20, cache_miss_tokens=prompt_tokens))


def _tool_messages(request):
    return [m for m in request.messages if m["role"] == "tool"]


def _hooks(session_id):
    row = database.get_connection().execute(
        "SELECT hooks_json FROM turn_metrics WHERE session_id = ? ORDER BY rowid DESC LIMIT 1", (session_id,)
    ).fetchone()
    return json.loads(row[0])


def _long_message(sections=12, width=250):
    return "\n".join(f"Section {i}: " + ("requirement %d detail " % i) * (width // 22) for i in range(sections))


# =========================================================================
# One configuration object
# =========================================================================
def test_every_threshold_lives_in_the_configuration_object(monkeypatch):
    fields = {
        "tool_round_budget", "result_cap_chars", "turn_result_budget_chars", "attachment_threshold_chars",
        "context_budget_tokens", "high_water", "low_water", "summary_max_tokens", "recent_window_tokens",
    }
    assert fields <= set(HarnessConfig.__dataclass_fields__)
    monkeypatch.setenv("HARNESS_CONTEXT_BUDGET_TOKENS", "120000")
    monkeypatch.setenv("HARNESS_HIGH_WATER", "0.8")
    monkeypatch.setenv("HARNESS_ATTACHMENT_THRESHOLD_CHARS", "1234")
    cfg = HarnessConfig.from_env()
    assert (cfg.context_budget_tokens, cfg.high_water, cfg.attachment_threshold_chars) == (120000, 0.8, 1234)
    with pytest.raises(ValueError):
        monkeypatch.setenv("HARNESS_CONTEXT_BUDGET_TOKENS", "50000")  # the default window no longer fits under the low mark
        HarnessConfig.from_env()
    with pytest.raises(ValueError):
        HarnessConfig(high_water=0.4, low_water=0.75)
    with pytest.raises(ValueError):
        HarnessConfig(context_budget_tokens=1000, low_water=0.4, summary_max_tokens=300, recent_window_tokens=300)


# =========================================================================
# Attachments: a long message is read on demand
# =========================================================================
@roomy
def test_a_long_customer_message_becomes_an_attachment_read_in_pieces(client, provider):
    text = _long_message()
    assert len(text) > 500
    provider.script(
        _calls(("read_attachment", {"id": 1, "offset": 0, "limit": 1000})),
        _calls(("read_attachment", {"id": 1, "offset": 1000, "limit": 1000})),
        "Thanks — here is what I make of your requirements.",
    )
    r = _chat(client, "s1", text)
    assert r.status_code == 200 and r.json()["reply"].startswith("Thanks")

    stub = provider.requests[0].messages[-1]
    assert stub["role"] == "user" and "attachment" in stub["content"].lower() and "read_attachment" in stub["content"]
    assert f"{len(text):,}" in stub["content"] and "Section 0:" in stub["content"], "an id, the size and a preview"
    assert "Section 11:" not in stub["content"], "the full text is not in context"
    assert database.load_messages("s1")[0]["content"] == stub["content"], "working memory holds the stub, not the text"

    (row,) = database.get_connection().execute("SELECT * FROM attachments").fetchall()
    assert row["session_id"] == "s1" and row["chars"] == len(text) and row["content"] == text

    first = _tool_messages(provider.requests[1])[0]["content"]
    header, body = first.split("\n", 1)
    assert body == text[:1000] and "next offset 1000" in header and f"of {len(text):,}" in header
    second = _tool_messages(provider.requests[2])[-1]["content"]
    assert second.split("\n", 1)[1] == text[1000:2000] and "next offset 2000" in second.split("\n", 1)[0]


@roomy
def test_read_attachment_is_scoped_to_the_session_and_bounded(client, provider):
    text = _long_message(sections=60)
    provider.script("Noted.", _calls(("read_attachment", {"id": 1})), "ok")
    _chat(client, "s1", text)
    _chat(client, "s2", "Can you read attachment 1?")
    feedback = _tool_messages(provider.requests[2])[0]["content"]
    assert "no attachment" in feedback.lower() or "not in this conversation" in feedback.lower()

    provider.script(_calls(("read_attachment", {"id": 1, "offset": 5000, "limit": 100000})),
                    _calls(("read_attachment", {"id": 1, "offset": 100000})), "ok")
    _chat(client, "s1", "Go on.")
    piece = _tool_messages(provider.requests[4])[-1]["content"]
    header, body = piece.split("\n", 1)
    assert 5000 < len(body) <= 6000 and body == text[5000:5000 + len(body)], "a piece never exceeds the result cap"
    assert len(piece) <= 6000, "with its header it still fits the result cap, so it is never truncated mid-way"
    beyond = _tool_messages(provider.requests[5])[-1]["content"]
    assert "end of attachment" in beyond and beyond.split("\n", 1)[1] == ""


@roomy
def test_evidence_in_an_attached_message_still_counts(client, provider):
    text = _long_message() + "\nBy the way, we need a volume discount before we can sign."
    provider.script(_calls(("request_handoff", {"team": "Deal Desk / Pricing", "reason": "Asks for a volume discount.",
                                                "evidence": "we need a volume discount before we can sign"})))
    cid = database.get_connection().execute(
        "SELECT customer_id FROM customers WHERE annual_payment_volume < 1000000 ORDER BY customer_id LIMIT 1"
    ).fetchone()[0]
    r = _chat(client, "s1", text, cid)
    assert r.json()["pending_handoff"]["team"] == "Deal Desk / Pricing", "the words are in the attachment, not the stub"


# =========================================================================
# A turn's tool results are capped in total
# =========================================================================
@small
def test_a_turns_tool_results_are_capped_in_total(client, provider):
    text = _long_message(sections=40)
    provider.script(
        _calls(("read_attachment", {"id": 1, "offset": 0, "limit": 1500})),
        _calls(("read_attachment", {"id": 1, "offset": 1500, "limit": 1500})),
        _calls(("read_attachment", {"id": 1, "offset": 3000, "limit": 1500})),
        "That is what I could read this turn.",
    )
    _chat(client, "s1", text)
    results = [m["content"] for m in _tool_messages(provider.requests[3])]
    assert len(results) == 3
    assert len(results[0]) >= 1500, "the first result fits the turn's budget"
    assert "budget" in results[1] and len(results[1]) < 1000, "the second is cut to what is left"
    assert "budget" in results[2] and len(results[2]) < 600, "the third keeps only a minimum"
    assert _hooks("s1")["modified"] >= 2


@small
def test_skill_bodies_are_not_charged_to_the_turn_budget(client, provider):
    provider.script(_calls(("Skill", {"name": "payments"}), ("Skill", {"name": "billing"}), ("Skill", {"name": "connect"})), "ok")
    _chat(client, "s1", "hi")
    for m in _tool_messages(provider.requests[1]):
        assert "budget" not in m["content"]


# =========================================================================
# Clearing: spent tool results become stubs before anything is summarised
# =========================================================================
@small
def test_spent_tool_results_are_cleared_into_stubs_when_pressure_builds(client, provider):
    text = _long_message()
    provider.script(
        _calls(("read_attachment", {"id": 1, "offset": 0, "limit": 1500})),
        _reply("Read it.", prompt_tokens=7700),  # over the high-water mark, but clearing alone brings it under
        "Sure.",
        _reply("Yes.", prompt_tokens=3000),
        "Fine.",
    )
    _chat(client, "s1", text)
    _chat(client, "s1", "Can you summarise section 3?")

    memory = provider.requests[2].messages
    stub = [m for m in memory if m["role"] == "tool"][0]["content"]
    assert stub.startswith("[cleared") and "read_attachment" in stub and "1,5" in stub, "one line: what it was and how big"
    assert "Section 0" not in stub
    row = database.get_connection().execute("SELECT content, cleared_at FROM messages WHERE role = 'tool'").fetchone()
    assert row["cleared_at"] and "Section 0" in row["content"], "the row keeps its content; only the rendering changes"
    assert _hooks("s1")["cleared"] == 1
    assert database.get_connection().execute("SELECT COUNT(*) FROM compactions").fetchone()[0] == 0, "clearing was enough"
    assert provider.requests[2].messages[0] == provider.requests[0].messages[0]

    _chat(client, "s1", "And section 4?")
    _chat(client, "s1", "Thanks.")
    assert "cleared" not in _hooks("s1"), "nothing to clear once pressure is gone"
    assert len(provider.requests) == 5, "no model call other than the turns themselves"


# =========================================================================
# Compaction: rarely, in large steps, summary on the sub-agent model
# =========================================================================
def _talk(client, provider, session_id, cid, turns, prompt_tokens_last, start=0):
    """`turns` plain exchanges of ~400-character messages, numbered from `start`; the last reply reports `prompt_tokens_last`."""
    for i in range(start, start + turns):
        reply = f"Reply {i}: " + ("noted point %d. " % i) * 26
        provider.script(_reply(reply, prompt_tokens_last if i == start + turns - 1 else 2000))
        _chat(client, session_id, f"Message {i}: " + ("customer detail %d, " % i) * 24, cid)


@small
def test_compaction_triggers_at_the_high_water_mark_and_keeps_the_recent_window_verbatim(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script(_calls(("Skill", {"name": "payments"})), _reply("Loaded.", 2000))
    _chat(client, "s1", "Let's talk payments.", cid)
    provider.script(_calls(("remember", {"kind": "commitment", "fact": "Going live with Stripe in Q4"})), _reply("Noted.", 2000))
    _chat(client, "s1", "We go live in Q4.", cid)
    provider.script(_reply("Read it.", 2000))
    _chat(client, "s1", _long_message(), cid)  # an attachment, folded away with the rest
    _talk(client, provider, "s1", cid, turns=4, prompt_tokens_last=8000)
    before = provider.requests[-1].messages
    n_requests = len(provider.requests)

    provider.script("Summary text: the customer discussed payments over several messages.", _reply("Here you go.", 3000))
    _chat(client, "s1", "Message 4: what do you recommend?", cid)

    summary_request, turn_request = provider.requests[n_requests], provider.requests[n_requests + 1]
    assert len(provider.requests) == n_requests + 2
    assert summary_request.model == "deepseek-flash" and not summary_request.tools
    assert "Message 0:" in summary_request.messages[-1]["content"] and "Let's talk payments" in summary_request.messages[-1]["content"]
    assert summary_request.messages[0]["content"] != before[0]["content"], "its own context, not the sales agent's prompt"

    messages = turn_request.messages
    assert messages[0] == before[0] and messages[1] == before[1], "the static prefix is unchanged"
    summary = messages[2]
    assert summary["role"] == "user" and "Summary text" in summary["content"]
    assert "Active skills: payments" in summary["content"], "the skills loaded in the compacted part are recorded"
    assert "attachment 1 (" in summary["content"] and "read_attachment" in summary["content"], "the model can still reach what was attached"
    assert "Facts established this session: commitment: Going live with Stripe in Q4" in summary["content"]
    assert messages[-1] == {"role": "user", "content": "Message 4: what do you recommend?"}, "the current message is verbatim"
    window = messages[3:-1]
    assert window[0]["role"] == "user" and window[0]["content"].startswith("Message 3:"), "the window starts at a customer message"
    assert window[-1]["content"].startswith("Reply 3:")
    assert sum(len(m["content"]) for m in window) <= 300 * 4, "the recent window is token-budgeted"
    assert not any("Message 1:" in m["content"] for m in messages[3:]), "older turns live only in the summary"
    assert len(summary["content"]) <= 200 * 4 + 200

    row = database.get_connection().execute("SELECT * FROM compactions").fetchone()
    assert row["session_id"] == "s1" and row["prompt_tokens_before"] == 8000 and row["model"] == "deepseek-flash"
    assert _hooks("s1")["compacted"] == 1
    assert database.load_messages("s1")[0]["content"] == summary["content"], "rendered working memory starts with the summary"


@small
def test_compaction_does_not_run_again_until_pressure_returns(client, provider):
    cid = first_customer(client)["customer_id"]
    _talk(client, provider, "s1", cid, turns=3, prompt_tokens_last=8000)
    provider.script("First summary.", _reply("ok", 3000))
    _chat(client, "s1", "Message 3: continue.", cid)
    assert database.get_connection().execute("SELECT COUNT(*) FROM compactions").fetchone()[0] == 1

    n = len(provider.requests)
    _talk(client, provider, "s1", cid, turns=2, prompt_tokens_last=8000, start=4)  # the last reply is over the mark again
    assert len(provider.requests) == n + 2 and "compacted" not in _hooks("s1"), "below the mark last time: no compaction"
    assert database.get_connection().execute("SELECT COUNT(*) FROM compactions").fetchone()[0] == 1

    provider.script("Second summary, folding the first.", _reply("ok", 3000))
    _chat(client, "s1", "Message 6: and more.", cid)
    assert database.get_connection().execute("SELECT COUNT(*) FROM compactions").fetchone()[0] == 2
    second = provider.requests[-2].messages[-1]["content"]
    assert "First summary." in second and "Message 3:" in second and "Message 4:" in second, "the previous summary is folded into the next"
    assert "Second summary" in provider.requests[-1].messages[2]["content"]
    assert provider.requests[-1].messages[3]["content"].startswith("Message 5:"), "the recent window stays verbatim"
    assert "First summary." not in json.dumps(provider.requests[-1].messages[3:])


@small
def test_the_rolling_summary_never_grows_past_its_cap(client, provider):
    cid = first_customer(client)["customer_id"]
    _talk(client, provider, "s1", cid, turns=3, prompt_tokens_last=8000)
    provider.script("Very long summary. " * 200, _reply("ok", 3000))
    _chat(client, "s1", "Message 3: go on.", cid)
    summary = provider.requests[-1].messages[2]["content"]
    assert len(summary) <= 200 * 4, "preface, prose and the certain lines together never exceed the cap"
    assert "cut at its size cap" in summary and "Active skills:" in summary


@small
def test_when_the_window_holds_everything_compaction_still_folds_all_but_the_last_turn(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script(_reply("Hello.", 2000), _reply("Yes.", 2000), _reply("Sure.", 8000))  # short turns: all within the window
    for msg in ("Hi.", "Do you take cards?", "And Apple Pay?"):
        _chat(client, "s1", msg, cid)
    provider.script("Summary of the short exchange.", _reply("ok", 3000))
    _chat(client, "s1", "Thanks.", cid)
    messages = provider.requests[-1].messages
    assert "Summary of the short exchange." in messages[2]["content"]
    assert messages[3]["content"] == "And Apple Pay?" and messages[4]["content"] == "Sure.", "the last customer turn stays verbatim"
    assert not any(m["content"] in ("Hi.", "Do you take cards?") for m in messages[3:])


@small
def test_a_pending_handoff_is_settled_before_compaction_so_the_transcript_stays_valid(client, provider):
    cid = database.get_connection().execute(
        "SELECT customer_id FROM customers WHERE annual_payment_volume < 1000000 ORDER BY customer_id LIMIT 1"
    ).fetchone()[0]
    _talk(client, provider, "s1", cid, turns=3, prompt_tokens_last=2000)
    proposal = Completion(
        content="", finish_reason="tool_calls",
        tool_calls=(ToolCall(id="h1", name="request_handoff", arguments=json.dumps(
            {"team": "Deal Desk / Pricing", "reason": "Asks for a discount.", "evidence": "we need a volume discount"})),),
        usage=Usage(prompt_tokens=8000, completion_tokens=20, cache_miss_tokens=8000),
    )
    provider.script(proposal)
    r = _chat(client, "s1", "Actually, we need a volume discount.", cid)
    assert r.json()["pending_handoff"]

    provider.script("Summary.", _reply("Understood — moving on.", 3000))
    _chat(client, "s1", "Never mind that, back to the products.", cid)  # a new message declines the proposal
    messages = provider.requests[-1].messages
    assert "Summary." in messages[2]["content"]
    open_calls: set[str] = set()
    for m in messages[3:]:
        if m["role"] == "assistant":
            open_calls = {c["id"] for c in m.get("tool_calls") or ()}
        elif m["role"] == "tool":
            assert m["tool_call_id"] in open_calls, "every tool result follows the assistant message that asked for it"
    assert any(m["role"] == "tool" and m["tool_call_id"] == "h1" and "declin" in m["content"].lower() for m in messages[3:])
    assert database.pending_handoff("s1") is None


@small
def test_a_failed_summary_leaves_the_turn_and_the_working_memory_intact(client, provider):
    cid = first_customer(client)["customer_id"]
    _talk(client, provider, "s1", cid, turns=3, prompt_tokens_last=8000)
    provider.script(RuntimeError("flash is down"), _reply("Still here.", 8000))
    r = _chat(client, "s1", "Message 3: still there?", cid)
    assert r.status_code == 200 and r.json()["reply"] == "Still here."
    assert database.get_connection().execute("SELECT COUNT(*) FROM compactions").fetchone()[0] == 0
    assert _hooks("s1")["compaction_failed"] == 1
    assert any("Message 0:" in m["content"] for m in provider.requests[-1].messages), "nothing was thrown away"


@small
def test_reflection_reads_the_summary_as_context_not_as_the_customers_words(client, provider):
    cid = first_customer(client)["customer_id"]
    _talk(client, provider, "s1", cid, turns=3, prompt_tokens_last=8000)
    provider.script("Summary: they sell shoes online.", _reply("ok", 3000))
    _chat(client, "s1", "Message 3: thanks.", cid)
    provider.script(Completion(content="nothing new"))
    client.post("/sales-agent/end", json={"session_id": "s1"})
    task = provider.requests[-1].messages[-1]["content"]
    assert "Summary of the earlier conversation:" in task and "Customer: [Working memory" not in task
