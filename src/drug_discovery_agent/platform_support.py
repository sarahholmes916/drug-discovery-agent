"""Local platform policy. Existing installations are never moved implicitly."""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path


def architecture() -> str:
    value = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(value, value)


def data_home() -> Path:
    configured = os.environ.get("DRUG_AGENT_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    legacy = Path.home() / "DrugDiscoveryAgent"
    if legacy.exists() or platform.system() == "Windows":
        return legacy.resolve()
    if platform.system() == "Darwin":
        return (Path.home() / "Library" / "Application Support" / "DrugDiscoveryAgent").resolve()
    return (Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "DrugDiscoveryAgent").resolve()


def tools_home() -> Path:
    configured = os.environ.get("DRUG_AGENT_TOOLS_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    legacy = Path.home() / ".drug-agent" / "tools"
    if legacy.exists() or platform.system() == "Windows":
        return legacy.resolve()
    return data_home() / "tools"


def boltz_installation_limit() -> str | None:
    if platform.system() == "Darwin" and architecture() == "x64":
        return (
            "Automatic Boltz 2.2.1 setup is unavailable on Intel Macs: official "
            "PyTorch macOS x64 wheels stop at 2.2.x; this installer pins 2.7.1. "
            "An independently validated external CPU environment is required."
        )
    return None


def external_environment(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Keep PyInstaller's Linux libraries out of independent scientific runtimes."""
    environment = os.environ.copy()
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        original = environment.get("LD_LIBRARY_PATH_ORIG")
        if original is None:
            environment.pop("LD_LIBRARY_PATH", None)
        else:
            environment["LD_LIBRARY_PATH"] = original
    environment.update(overrides or {})
    return environment
