"""
Unit tests for the Skill registry.

Validates config integrity — the kind of bugs that silently break the agent:
tool name typos, missing scenarios, inconsistent escalation config.
"""

import pytest

from app.kg_builder import get_knowledge_graph
from app.skills import SKILL_REGISTRY, SkillConfig, get_skill, list_scenarios
from app.tools import TOOL_BY_NAME, get_tools_for_skill


pytestmark = pytest.mark.unit


# =========================================================================
# Registry integrity
# =========================================================================
def test_registry_not_empty():
    assert len(SKILL_REGISTRY) >= 12


def test_all_skills_have_required_fields():
    for sid, skill in SKILL_REGISTRY.items():
        assert skill.scenario_id == sid, f"{sid}: scenario_id mismatch"
        assert skill.display_name, f"{sid}: missing display_name"
        assert skill.system_prompt, f"{sid}: missing system_prompt"
        assert isinstance(skill.required_tools, tuple), f"{sid}: required_tools must be tuple"
        assert isinstance(skill.optional_tools, tuple), f"{sid}: optional_tools must be tuple"
        assert isinstance(skill.escalation_triggers, tuple), f"{sid}: triggers must be tuple"


def test_general_inquiry_exists():
    """Fallback scenario must always exist."""
    assert "general_inquiry" in SKILL_REGISTRY


def test_out_of_scope_exists():
    assert "out_of_scope" in SKILL_REGISTRY


def test_escalation_request_exists():
    assert "escalation_request" in SKILL_REGISTRY


# =========================================================================
# Tool name validity — catches typos
# =========================================================================
def test_all_referenced_tools_exist():
    """Every tool name in a skill must exist in TOOL_BY_NAME."""
    valid_tools = set(TOOL_BY_NAME.keys())
    for sid, skill in SKILL_REGISTRY.items():
        for tool_name in skill.required_tools:
            assert tool_name in valid_tools, (
                f"{sid}: required tool '{tool_name}' not in registry. "
                f"Valid: {sorted(valid_tools)}"
            )
        for tool_name in skill.optional_tools:
            assert tool_name in valid_tools, (
                f"{sid}: optional tool '{tool_name}' not in registry. "
                f"Valid: {sorted(valid_tools)}"
            )


def test_no_tool_in_both_required_and_optional():
    for sid, skill in SKILL_REGISTRY.items():
        overlap = set(skill.required_tools) & set(skill.optional_tools)
        assert not overlap, f"{sid}: tools in both required and optional: {overlap}"


def test_get_tools_for_skill_returns_valid_tools():
    for sid, skill in SKILL_REGISTRY.items():
        tools = get_tools_for_skill(skill.required_tools, skill.optional_tools)
        expected_count = len(set(skill.required_tools) | set(skill.optional_tools))
        assert len(tools) == expected_count, (
            f"{sid}: expected {expected_count} tools, got {len(tools)}"
        )


# =========================================================================
# Iteration limits
# =========================================================================
def test_max_iterations_sane():
    for sid, skill in SKILL_REGISTRY.items():
        assert 0 <= skill.max_iterations <= 10, (
            f"{sid}: max_iterations={skill.max_iterations} out of range"
        )


def test_zero_iteration_skills_have_no_required_tools():
    """If max_iterations=0, the ReAct loop is skipped — required tools would never run."""
    for sid, skill in SKILL_REGISTRY.items():
        if skill.max_iterations == 0:
            assert not skill.required_tools, (
                f"{sid}: max_iterations=0 but has required_tools {skill.required_tools} "
                "(they would never be called)"
            )


def test_skills_with_tools_have_nonzero_iterations():
    for sid, skill in SKILL_REGISTRY.items():
        if skill.required_tools:
            assert skill.max_iterations > 0, (
                f"{sid}: has required_tools but max_iterations=0"
            )


# =========================================================================
# Escalation config
# =========================================================================
def test_escalation_triggers_are_multiword_or_specific():
    """
    Triggers should be specific phrases, not single common words.
    Prevents false-positive escalations like 'human' matching 'human error'.
    """
    too_generic = {"help", "issue", "problem", "question", "need", "want"}
    for sid, skill in SKILL_REGISTRY.items():
        for trigger in skill.escalation_triggers:
            assert trigger.lower() not in too_generic, (
                f"{sid}: trigger '{trigger}' is too generic — will cause false positives"
            )


def test_escalation_triggers_lowercase_safe():
    """Triggers are matched case-insensitively; ensure no leading/trailing spaces."""
    for sid, skill in SKILL_REGISTRY.items():
        for trigger in skill.escalation_triggers:
            assert trigger == trigger.strip(), f"{sid}: trigger '{trigger}' has whitespace"
            assert len(trigger) >= 3, f"{sid}: trigger '{trigger}' too short"


def test_escalation_triggers_routed_in_escalation_module():
    """Every trigger must have a team mapping in escalation.TEAM_ROUTING."""
    from app.escalation import TEAM_ROUTING
    for sid, skill in SKILL_REGISTRY.items():
        for trigger in skill.escalation_triggers:
            assert trigger in TEAM_ROUTING, (
                f"{sid}: trigger '{trigger}' has no team in TEAM_ROUTING"
            )


# =========================================================================
# Scenario / KG alignment
# =========================================================================
SYNTHETIC_SCENARIOS = {"out_of_scope", "general_inquiry"}


def test_scenarios_exist_in_knowledge_graph():
    """Product scenarios must have a KG node. Synthetic fallbacks are exempt."""
    graph = get_knowledge_graph()
    for sid in SKILL_REGISTRY:
        if sid in SYNTHETIC_SCENARIOS:
            continue
        node = graph.get_node(sid)
        assert node is not None, f"Skill '{sid}' has no corresponding KG node"


def test_list_scenarios_matches_registry():
    assert set(list_scenarios()) == set(SKILL_REGISTRY.keys())


# =========================================================================
# get_skill behavior
# =========================================================================
def test_get_skill_returns_correct_skill():
    skill = get_skill("marketplace")
    assert skill.scenario_id == "marketplace"


def test_get_skill_falls_back_to_general_inquiry():
    skill = get_skill("nonexistent_scenario_xyz")
    assert skill.scenario_id == "general_inquiry"


def test_skill_config_is_immutable():
    """SkillConfig is frozen — prevents accidental runtime mutation."""
    skill = get_skill("marketplace")
    with pytest.raises((AttributeError, TypeError)):
        skill.max_iterations = 99
