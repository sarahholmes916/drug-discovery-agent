from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any
from drug_discovery_agent.platform_support import tools_home


def managed_tools_home() -> Path:
    return tools_home()


def managed_bin() -> Path:
    return managed_tools_home() / "bin"


def managed_command(command: str) -> Path | None:
    suffix = ".exe" if platform.system() == "Windows" else ""
    candidate = managed_bin() / f"{command}{suffix}"
    return candidate if candidate.is_file() else None


def managed_tool_metadata(tool_id: str) -> dict[str, Any] | None:
    """Read non-sensitive identity metadata for a companion-managed tool."""
    path = managed_tools_home() / tool_id / "installation.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def managed_plip_environment(environment_root: str | Path | None = None) -> dict[str, str] | None:
    """Return the activation variables needed by the private Open Babel build."""
    root = Path(environment_root) if environment_root else managed_tools_home() / "plip" / "environment"
    if not root.is_dir():
        return None
    data_candidates = [root / "share" / "openbabel", root / "Library" / "share" / "openbabel"]
    if platform.system() == "Windows":
        plugin_candidates = [root / "Library" / "bin"]
        path_candidates = [root / "Library" / "bin", root / "Scripts", root]
    else:
        plugin_candidates = sorted((root / "lib" / "openbabel").glob("*"), reverse=True)
        path_candidates = [root / "bin"]
    data = next((candidate for candidate in data_candidates if candidate.is_dir()), None)
    plugins = next((candidate for candidate in plugin_candidates if candidate.is_dir()), None)
    if data is None or plugins is None:
        return None
    current_path = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    additions = [str(candidate) for candidate in path_candidates if candidate.is_dir()]
    combined = [*additions, *current_path]
    deduplicated: list[str] = []
    seen: set[str] = set()
    for entry in combined:
        normalized = os.path.normcase(os.path.abspath(entry))
        if normalized not in seen:
            seen.add(normalized)
            deduplicated.append(entry)
    return {
        "BABEL_DATADIR": str(data),
        "BABEL_LIBDIR": str(plugins),
        "PATH": os.pathsep.join(deduplicated),
    }


def activate_managed_tools() -> Path:
    """Make companion-managed executables visible to all child processes."""
    directory = managed_bin()
    current = os.environ.get("PATH", "")
    entries = [entry for entry in current.split(os.pathsep) if entry]
    normalized = {os.path.normcase(os.path.abspath(entry)) for entry in entries}
    if os.path.normcase(os.path.abspath(directory)) not in normalized:
        os.environ["PATH"] = os.pathsep.join([str(directory), *entries])
    return directory
