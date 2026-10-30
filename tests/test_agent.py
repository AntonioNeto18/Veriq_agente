"""Montagem do agente ADK, sem chamar o modelo."""

import asyncio

from google.adk.skills import load_skill_from_dir
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset

from agent_veriq.agent import build_agent, build_skill_toolset
from agent_veriq.config import SKILL_NAMES, SKILLS_DIR
from agent_veriq.tools import ALL_TOOLS


def test_skills_have_valid_frontmatter_and_single_responsibility():
    for name in SKILL_NAMES:
        skill = load_skill_from_dir(SKILLS_DIR / name)
        assert skill.name == name
        assert 20 < len(skill.description) < 400
        assert skill.instructions.strip()
        assert not skill.resources.list_scripts()


def test_skill_references_are_available_on_demand():
    analysis = load_skill_from_dir(SKILLS_DIR / "openapi-analysis")
    assert set(analysis.resources.list_references()) == {"version-differences.md", "refs-and-security.md"}


def test_skill_toolset_never_exposes_script_execution():
    names = [tool.name for tool in asyncio.run(build_skill_toolset().get_tools())]
    assert names == ["list_skills", "load_skill", "load_skill_resource"]


def test_agent_wiring(monkeypatch):
    monkeypatch.setenv("VERIQ_MODEL", "modelo-de-teste")
    agent = build_agent()
    assert agent.name == "veriq"
    assert agent.model == "modelo-de-teste"
    assert "NUNCA executa requisições" in agent.instruction
    function_tools = [tool for tool in agent.tools if callable(tool)]
    assert function_tools == ALL_TOOLS
    assert sum(isinstance(tool, SkillToolset) for tool in agent.tools) == 1


def test_function_tool_declarations_are_generated():
    for function in ALL_TOOLS:
        declaration = FunctionTool(function)._get_declaration()
        assert declaration.name == function.__name__
        assert declaration.description
