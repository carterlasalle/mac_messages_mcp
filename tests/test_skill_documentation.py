# Copyright (c) 2023 Carter Lasalle
"""The agent skill must stay in step with the server's tool surface."""

import re
from pathlib import Path

from mac_messages_mcp import server

SKILL_PATH = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "mac-messages"
    / "SKILL.md"
)

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_TOOL_REFERENCE = re.compile(r"\btool_[a-z0-9_]+\b")


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _server_tools() -> set[str]:
    return {
        name
        for name in vars(server)
        if name.startswith("tool_") and callable(getattr(server, name))
    }


def test_skill_frontmatter_declares_name_and_description():
    match = _FRONTMATTER.match(_skill_text())
    assert match, "SKILL.md must open with a YAML frontmatter block"
    frontmatter = match.group(1)
    assert re.search(r"^name:\s*\S", frontmatter, re.MULTILINE)
    assert re.search(r"^description:\s*\S", frontmatter, re.MULTILINE)


def test_skill_documents_every_server_tool():
    documented = set(_TOOL_REFERENCE.findall(_skill_text()))
    undocumented = _server_tools() - documented
    assert not undocumented, f"tools missing from SKILL.md: {sorted(undocumented)}"


def test_skill_references_no_unknown_tools():
    documented = set(_TOOL_REFERENCE.findall(_skill_text()))
    unknown = documented - set(vars(server))
    assert not unknown, f"SKILL.md references unknown symbols: {sorted(unknown)}"
