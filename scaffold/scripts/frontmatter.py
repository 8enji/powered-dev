"""Zero-dependency YAML frontmatter parser.

Handles flat key: value pairs and one level of nested mappings.
All values are strings. No PyYAML required.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def parse_frontmatter(path: Path) -> dict[str, Any] | None:
    """Parse YAML frontmatter from a markdown file. Returns None if absent/malformed."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    block = text[4:end]
    return _parse_yaml_block(block)


def _strip_quotes(val: str) -> str:
    if len(val) >= 2 and (val[0] == val[-1] == '"' or val[0] == val[-1] == "'"):
        return val[1:-1]
    return val


def _parse_yaml_block(block: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    lines = block.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)", line)
        if not m:
            i += 1
            continue
        key = m.group(1)
        val = m.group(2).strip()
        if val:
            result[key] = _strip_quotes(val)
            i += 1
        else:
            nested: dict[str, str] = {}
            i += 1
            while i < len(lines):
                child = lines[i]
                cm = re.match(r"^  ([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)", child)
                if cm:
                    nested[cm.group(1)] = _strip_quotes(cm.group(2).strip())
                    i += 1
                else:
                    break
            result[key] = nested if nested else ""
    return result
