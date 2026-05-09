# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2"]
# ///
"""LM Studio sandbox MCP server.

Exposes read_file / write_file / list_dir tools restricted to LM_MCP_ROOT.
Every path is resolved and checked to be inside the root before any I/O,
so the model cannot escape via .. or absolute paths or symlinks.
"""

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

_root_env = os.environ.get("LM_MCP_ROOT")
if not _root_env:
    raise SystemExit("LM_MCP_ROOT environment variable is required")

ROOT = Path(_root_env).resolve()
if not ROOT.is_dir():
    raise SystemExit(f"LM_MCP_ROOT is not an existing directory: {ROOT}")

mcp = FastMCP("lm-fs")


def _safe(path: str) -> Path:
    p = Path(path)
    target = (p if p.is_absolute() else ROOT / p).resolve()
    if target != ROOT and ROOT not in target.parents:
        raise ValueError(f"path escapes sandbox root: {target}")
    return target


@mcp.tool()
def read_file(path: str) -> str:
    """Read a UTF-8 text file inside the sandbox. Path is relative to the sandbox root (or absolute, but must still lie inside the root)."""
    return _safe(path).read_text(encoding="utf-8")


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Overwrite (or create) a UTF-8 text file inside the sandbox. Parent directories are created automatically. Returns a short confirmation string."""
    target = _safe(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {target.relative_to(ROOT) if target != ROOT else '.'}"


@mcp.tool()
def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Replace an exact occurrence of old_string with new_string inside a UTF-8 text file. Fails if old_string is not found, or if it occurs more than once and replace_all is False (in which case the model should provide more surrounding context to make the match unique). The file must already exist."""
    target = _safe(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        raise ValueError("old_string not found in file")
    if count > 1 and not replace_all:
        raise ValueError(
            f"old_string occurs {count} times; include more surrounding context to make it unique, or pass replace_all=True"
        )
    target.write_text(text.replace(old_string, new_string), encoding="utf-8")
    rel = target.relative_to(ROOT) if target != ROOT else "."
    return f"replaced {count if replace_all else 1} occurrence(s) in {rel}"


@mcp.tool()
def list_dir(path: str = ".") -> list[str]:
    """List entries inside a directory in the sandbox. Directory names are returned with a trailing slash. Use '.' for the sandbox root."""
    target = _safe(path)
    if not target.is_dir():
        raise ValueError(f"not a directory: {target}")
    return sorted(
        f"{e.name}/" if e.is_dir() else e.name
        for e in target.iterdir()
    )


if __name__ == "__main__":
    mcp.run()
