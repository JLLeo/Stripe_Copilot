"""
Skills — markdown instruction files the model loads on demand.

    skills/<name>/SKILL.md
    ---
    name: <name>            must match the directory
    description: <one line> what the static prompt shows the model
    ---
    <body>                  what the model receives when it calls Skill(name)

The static prompt carries only the index of descriptions; a body enters the
conversation only as the result of a `Skill` tool call, so the model — not a
classifier — decides when a skill applies (ADR 0001). Skills shape behaviour;
they do not restrict which tools the model may use.

Frontmatter is validated when the harness is built, so a broken skill file
fails startup rather than a customer conversation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.harness.tools import Tool, ToolContext, ToolRegistry, ToolResult

SKILL_FILE = "SKILL.md"
_NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)


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


def register_skill_tool(registry: ToolRegistry, skills: dict[str, Skill]) -> Tool:
    names = list(skills)

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
            "Load the instructions for one area of Stripe's products before advising in it. "
            "Returns the skill's full guidance. Call it once per area per conversation, "
            "or again if you need to re-read it."
        ),
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "enum": names, "description": "The skill to load."}},
            "required": ["name"],
            "additionalProperties": False,
        },
        run=run,
        cacheable=False,  # a load is the point; it must always land in the conversation
    ))
