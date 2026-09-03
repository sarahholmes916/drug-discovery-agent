from __future__ import annotations

import importlib.metadata
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from drug_discovery_agent import __version__

from .hashing import sha256_file, stable_json_hash
from .io import atomic_write_json


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _short_command(args: list[str], timeout: float = 5.0) -> str | None:
    executable = shutil.which(args[0])
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, *args[1:]], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or result.stderr).strip().splitlines()
    return text[0][:300] if text else None


def git_commit(repository: str | Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def collect_provenance(
    *,
    repository: str | Path,
    config: object,
    input_paths: Iterable[str | Path] = (),
) -> dict[str, object]:
    inputs = {Path(path).name: sha256_file(path) for path in input_paths}
    gpu = _short_command(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"])
    cuda = _short_command(["nvcc", "--version"])
    if cuda is None and shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=5)
            cuda_line = next((part.strip() for part in result.stdout.split("|") if "CUDA Version" in part), None)
            cuda = cuda_line
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "pipeline_version": __version__,
        "git_commit": git_commit(repository),
        "project_config_hash": stable_json_hash(config),
        "input_hashes": inputs,
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {
            "rdkit": _package_version("rdkit"),
            "meeko": _package_version("meeko"),
            "boltz": _package_version("boltz"),
            "plip": _package_version("plip"),
        },
        "tools": {
            "vina": _short_command(["vina", "--version"]),
            "meeko": _short_command(["mk_prepare_ligand.py", "--version"]),
            "boltz": _short_command(["boltz", "--help"]),
            "plip": _short_command(["plip", "--version"]),
        },
        "gpu_model_driver": gpu,
        "cuda_version": cuda,
        "external_command_records": "state/commands/*.json",
    }


def write_provenance(path: str | Path, payload: dict[str, object]) -> None:
    atomic_write_json(path, payload)
