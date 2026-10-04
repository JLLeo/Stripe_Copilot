"""
Skills — markdown instruction files the model loads on demand.

    skills/<name>/SKILL.md
    ---
    name: <name>            must match the directory
    description: <one line> what the static prompt shows the model
    ---
    <body>                  what the model receives when it calls Skill(name)

The static prompt carries only the index of descriptions. A body enters the
conversation in one of two ways: as the result of a `Skill` tool call the model
makes, or primed by the harness before the model's first call of a turn
(`primed_message`, chosen in priming.py). Either way it enters a Session at
most once — a `Skill` call for a body already in the conversation is answered
with a short note instead of a second copy (`skill_already_in_context`).
Skills shape behaviour; they do not restrict which tools the model may use.

Frontmatter is validated when the harness is built, so a broken skill file
fails startup rather than a customer conversation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.harness.hooks import HookEvent, HookRegistry, Replace, ToolUseContext
from app.harness.tools import Tool, ToolContext, ToolRegistry, ToolResult

SKILL_FILE = "SKILL.md"
_NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)

PRIMED_MARKER = (
    "[Skills primed by the harness: {names}. Their instructions follow and stay in this conversation — "
    "do not call Skill for them. Load any other skill you need as usual.]"
)
_PRIMED_NAMES = re.compile(r"\A\[Skills primed by the harness: ([a-z0-9_, ]+)\.")
FINGERPRINT_CHARS = 200  # enough of a body's opening to recognise it in a message, whatever was appended after it
ALREADY_IN_CONTEXT = (
    "Already in context: the {name} skill's instructions are earlier in this conversation. "
    "Follow them from there; there is nothing new to load."
)
# Tools whose arguments no skill informs: pairing one with a Skill call in the same response loses
# nothing, so it is not a tool chosen without its instructions. get_my_profile takes no arguments;
# no skill's instructions mention list_products or remember. capture_lead is not here: the
# discovery skill says when to call it and what to record.
UNINFORMED_TOOLS = frozenset({"get_my_profile", "list_products", "remember"})


class SkillLoadError(ValueError):
    """A skill file is missing, malformed, or contradicts its directory."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path


def load_skills(directory: Path) -> dict[str, Skill]:
    """Load and validate every `<dir>/<name>/SKILL.md`, sorted by name."""
    directory = Path(directory)
    if not directory.is_dir():
        raise SkillLoadError(f"skills directory not found: {directory}")
    skills: dict[str, Skill] = {}
    for skill_dir in sorted(p for p in directory.iterdir() if p.is_dir()):
        path = skill_dir / SKILL_FILE
        if not path.exists():
            raise SkillLoadError(f"{skill_dir.name}: no {SKILL_FILE}")
        skills[skill_dir.name] = _parse(path, expected_name=skill_dir.name)
    if not skills:
        raise SkillLoadError(f"no skills found under {directory}")
    return skills


def _parse(path: Path, expected_name: str) -> Skill:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if not match:
        raise SkillLoadError(f"{path}: missing YAML frontmatter (--- ... ---)")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillLoadError(f"{path}: frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise SkillLoadError(f"{path}: frontmatter must be a mapping")

    name = str(meta.get("name", "")).strip()
    description = " ".join(str(meta.get("description", "")).split())
    body = match.group(2).strip()
    if not _NAME.match(name):
        raise SkillLoadError(f"{path}: 'name' must be a short snake_case identifier, got {name!r}")
    if name != expected_name:
        raise SkillLoadError(f"{path}: name {name!r} does not match its directory {expected_name!r}")
    if not description:
        raise SkillLoadError(f"{path}: 'description' is required — it is all the model sees until it loads the skill")
    if len(description) > 200:
        raise SkillLoadError(f"{path}: 'description' must be one line (≤200 chars); move detail into the body")
    if not body:
        raise SkillLoadError(f"{path}: body is empty")
    return Skill(name=name, description=description, body=body, path=path)


def skills_index(skills: dict[str, Skill]) -> str:
    """The section of the static prompt that advertises skills — descriptions only."""
    lines = [
        "Skills. Before advising in one of these areas, load its skill with the Skill tool and follow it; "
        "load more than one when a question spans areas:"
    ]
    lines += [f"- {s.name}: {s.description}" for s in skills.values()]
    return "\n".join(lines)


def register_skill_tool(registry: ToolRegistry, hooks: HookRegistry, skills: dict[str, Skill]) -> Tool:
    """The Skill tool, and the guardrail that keeps each body to one copy per Session."""
    names = list(skills)
    hooks.register(HookEvent.PRE_TOOL_USE, skill_already_in_context)

    def run(ctx: ToolContext, args: dict) -> ToolResult:
        skill = skills.get(args.get("name", ""))
        if skill is None:
            return ToolResult.error(
                f"No skill named {args.get('name')!r}. Available skills: {', '.join(names)}."
            )
        return ToolResult(content=skill.body, meta={"skill": skill.name})

    return registry.register(Tool(
        name="Skill",
        description=(
            "Load the instructions for one area of Stripe's products before advising in it or calling other tools for it, "
            "so those calls follow the instructions. Returns the skill's full guidance. "
            "Instructions already in this conversation — loaded earlier, or primed by the harness — need no second load."
        ),
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "enum": names, "description": "The skill to load."}},
            "required": ["name"],
            "additionalProperties": False,
        },
        run=run,
        cacheable=False,  # a body is either in the conversation or not; skill_already_in_context decides, not the cache
    ))


# ---------------------------------------------------------------------------
# At most once per Session
# ---------------------------------------------------------------------------
def primed_message(names: list[str], skills: dict[str, Skill]) -> dict[str, Any]:
    """The harness-authored message that puts skill bodies into the conversation, most probable first.

    A `system` message, never `user`: everything that reads working memory as the customer's
    words — handoff evidence, the compaction summariser, reflection — reads `user` rows only.
    """
    parts = [PRIMED_MARKER.format(names=", ".join(names))]
    parts += [f"## Skill: {name}\n\n{skills[name].body}" for name in names]
    return {"role": "system", "content": "\n\n".join(parts)}


def primed_names(message: dict[str, Any]) -> list[str]:
    """The skills a primed message carries, read back from its marker; [] for any other message."""
    if message.get("role") != "system":
        return []
    match = _PRIMED_NAMES.match(message.get("content") or "")
    return [n.strip() for n in match.group(1).split(",")] if match else []


def skills_in_context(working_memory: list[dict[str, Any]], skills: dict[str, Skill]) -> set[str]:
    """The skills whose bodies are in working memory now — a `Skill` result or a primed message.

    Read from the messages themselves, so a body that compaction folded away is no longer in
    context and may be loaded (or primed) again.
    """
    carriers = [m.get("content") or "" for m in working_memory if m["role"] in ("tool", "system")]
    return {name for name, s in skills.items() if any(s.body[:FINGERPRINT_CHARS] in text for text in carriers)}


def skill_already_in_context(ctx: ToolUseContext) -> Replace | None:
    """PreToolUse: a `Skill` call for a body the conversation already holds gets a short note, not a second copy.

    Never a Deny: the model asked for instructions it has, and the answer is where they are.
    """
    if ctx.tool.name != "Skill":
        return None
    name = ctx.arguments.get("name", "")
    if name not in ctx.turn.skills_in_context:
        return None
    ctx.turn.redundant_skill_calls += 1
    return Replace(ToolResult(content=ALREADY_IN_CONTEXT.format(name=name)))


def requested_skill(arguments: str) -> str:
    """The skill a `Skill` call asks for, from its raw arguments; "?" when they do not name one."""
    try:
        name = json.loads(arguments).get("name")
    except (TypeError, ValueError, AttributeError):
        return "?"
    return str(name) if name else "?"


def skill_paired_with_tool(call_names: list[str]) -> bool:
    """A response that loads a skill and, in the same breath, calls a tool that skill would inform —
    a tool chosen without its instructions. Counted on every turn's first response."""
    return "Skill" in call_names and any(n != "Skill" and n not in UNINFORMED_TOOLS for n in call_names)
