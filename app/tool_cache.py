"""
Tool Result Cache
==================
Per-session, TTL-bounded cache for tool call results.

Prevents redundant SQL queries and Milvus searches when the LLM calls the
same tool with the same arguments across turns in one conversation.

Cacheable tools are those whose output is stable within a session
(customer profiles, policies, pricing docs). Live searches are cached too
because the knowledge base does not change mid-conversation.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CACHE_TTL_SECONDS = 900        # 15 minutes — a conversation rarely outlives this
MAX_ENTRIES_PER_SESSION = 50   # bound memory per session
MAX_SESSIONS = 200             # bound total memory

# Tools whose results are safe to cache within a session.
# Excluded: check_escalation_tool (decision depends on current query).
CACHEABLE_TOOLS = frozenset({
    "search_product_info",
    "lookup_customer_tool",
    "lookup_product_usage_tool",
    "lookup_pricing_tool",
    "lookup_policy_tool",
})


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
@dataclass
class _Entry:
    value: str
    created_at: float
    hits: int = 0


@dataclass
class _SessionCache:
    entries: dict[str, _Entry] = field(default_factory=dict)
    last_access: float = field(default_factory=time.time)


# Module-level store: {session_id: _SessionCache}
_store: dict[str, _SessionCache] = {}

# Counters for observability
_stats = {"hits": 0, "misses": 0, "evictions": 0}


# ---------------------------------------------------------------------------
# Key building
# ---------------------------------------------------------------------------
def make_key(tool_name: str, args: dict) -> str:
    """Stable cache key from tool name + normalized arguments."""
    payload = json.dumps(args, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{tool_name}:{digest}"


def is_cacheable(tool_name: str) -> bool:
    return tool_name in CACHEABLE_TOOLS


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------
def get(session_id: str, tool_name: str, args: dict) -> str | None:
    """Return cached output, or None on miss/expiry."""
    if not session_id or not is_cacheable(tool_name):
        return None

    session = _store.get(session_id)
    if session is None:
        _stats["misses"] += 1
        return None

    key = make_key(tool_name, args)
    entry = session.entries.get(key)
    if entry is None:
        _stats["misses"] += 1
        return None

    if time.time() - entry.created_at > CACHE_TTL_SECONDS:
        del session.entries[key]
        _stats["misses"] += 1
        return None

    entry.hits += 1
    session.last_access = time.time()
    _stats["hits"] += 1
    return entry.value


def put(session_id: str, tool_name: str, args: dict, value: str) -> None:
    """Store a tool result. No-op for non-cacheable tools or error output."""
    if not session_id or not is_cacheable(tool_name):
        return
    if value.startswith("ERROR:"):
        return  # never cache failures

    _evict_stale_sessions()

    session = _store.setdefault(session_id, _SessionCache())
    session.last_access = time.time()

    # Bound per-session size — drop oldest entry
    if len(session.entries) >= MAX_ENTRIES_PER_SESSION:
        oldest = min(session.entries.items(), key=lambda kv: kv[1].created_at)
        del session.entries[oldest[0]]
        _stats["evictions"] += 1

    session.entries[make_key(tool_name, args)] = _Entry(
        value=value, created_at=time.time()
    )


def invalidate(session_id: str) -> None:
    """Drop all cached entries for one session."""
    _store.pop(session_id, None)


def clear_all() -> None:
    """Drop everything. Used by tests."""
    _store.clear()
    _stats.update({"hits": 0, "misses": 0, "evictions": 0})


def stats() -> dict:
    """Return cache counters plus current size."""
    total = _stats["hits"] + _stats["misses"]
    return {
        **_stats,
        "sessions": len(_store),
        "entries": sum(len(s.entries) for s in _store.values()),
        "hit_rate": round(_stats["hits"] / total, 3) if total else 0.0,
    }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------
def _evict_stale_sessions() -> None:
    """Drop sessions that exceeded TTL, then trim to MAX_SESSIONS by LRU."""
    now = time.time()
    stale = [
        sid for sid, s in _store.items()
        if now - s.last_access > CACHE_TTL_SECONDS
    ]
    for sid in stale:
        del _store[sid]
        _stats["evictions"] += 1

    if len(_store) > MAX_SESSIONS:
        by_age = sorted(_store.items(), key=lambda kv: kv[1].last_access)
        for sid, _ in by_age[: len(_store) - MAX_SESSIONS]:
            del _store[sid]
            _stats["evictions"] += 1
