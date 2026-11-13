from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from drug_discovery_agent.config.models import PocketMinerRuntimeConfig
from drug_discovery_agent.execution.commands import CancellationToken, CommandExecutor, CommandResult
from drug_discovery_agent.project.hashing import sha256_file
from drug_discovery_agent.project.io import atomic_write_json, read_json
from drug_discovery_agent.platform_support import tools_home, external_environment


DEFAULT_HOME = tools_home() / "pocketminer"
VENDORED_HOME = Path(__file__).resolve().parent.parent / "_vendor" / "pocketminer"
VENDORED_MANIFEST = VENDORED_HOME / "manifest.json"


def installation_root(config: PocketMinerRuntimeConfig) -> Path:
    configured = config.installation_root or os.environ.get("DRUG_AGENT_POCKETMINER_HOME")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_HOME.resolve()


def source_root(config: PocketMinerRuntimeConfig) -> Path:
    configured = config.installation_root or os.environ.get("DRUG_AGENT_POCKETMINER_HOME")
    return installation_root(config) / "source" if configured else VENDORED_HOME


def environment_python(config: PocketMinerRuntimeConfig) -> Path:
    if config.python_executable:
        return Path(config.python_executable).expanduser().resolve()
    root = installation_root(config) / "environment"
    return root / ("python.exe" if platform.system() == "Windows" else "bin/python")


def checkpoint_files(config: PocketMinerRuntimeConfig) -> list[Path]:
    prefix = source_root(config) / config.checkpoint_prefix
    return sorted(path for path in prefix.parent.glob(prefix.name + "*") if path.is_file())


def inspect_installation(config: PocketMinerRuntimeConfig) -> dict[str, object]:
    repository, python = source_root(config), environment_python(config)
    errors = []
    commit = None
    if repository == VENDORED_HOME:
        manifest = read_json(VENDORED_MANIFEST, {})
        commit = manifest.get("commit")
        declared_files = manifest.get("files", {})
        if not isinstance(declared_files, dict) or not declared_files:
            errors.append("included PocketMiner integrity manifest is missing or invalid")
        else:
            for relative_path, expected_sha256 in declared_files.items():
                path = repository / relative_path
                if not path.is_file():
                    errors.append(f"included PocketMiner file is missing: {relative_path}")
                elif sha256_file(path) != expected_sha256:
                    errors.append(f"included PocketMiner file failed integrity check: {relative_path}")
    elif (repository / ".git").is_dir():
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, timeout=5,
            )
            commit = result.stdout.strip() if result.returncode == 0 else None
            dirty = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=repository, capture_output=True, text=True, timeout=5,
            )
            if dirty.returncode != 0 or dirty.stdout.strip():
                errors.append("official PocketMiner checkout has modified tracked files")
        except (OSError, subprocess.SubprocessError):
            pass
    if commit != config.commit:
        errors.append(f"checkout commit is {commit or 'unavailable'}, expected {config.commit}")
    if not python.is_file():
        errors.append(f"PocketMiner Python is missing: {python}")
    checkpoints = checkpoint_files(config)
    if not checkpoints:
        errors.append(f"checkpoint prefix has no files: {config.checkpoint_prefix}")
    probe = None
    if not errors:
        adapter = Path(__file__).with_name("_official_adapter.py")
        try:
            result = subprocess.run(
                [str(python), str(adapter), "--repository", str(repository), "--probe"],
                capture_output=True, text=True, timeout=30,
                env=external_environment({"PYTHONDONTWRITEBYTECODE": "1"}),
            )
            if result.returncode == 0:
                probe = json.loads(result.stdout.strip().splitlines()[-1])
            else:
                errors.append((result.stderr or result.stdout).strip()[-500:])
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            errors.append(f"PocketMiner environment probe failed: {exc}")
    return {
        "available": not errors,
        "implementation": config.implementation,
        "repository": str(repository),
        "commit": commit,
        "expected_commit": config.commit,
        "python": str(python),
        "dependencies": probe,
        "checkpoint_prefix": config.checkpoint_prefix,
        "checkpoint_sha256": {path.name: sha256_file(path) for path in checkpoints},
        "errors": errors,
    }


def setup(
    config: PocketMinerRuntimeConfig,
    executor: CommandExecutor | None = None,
    *,
    conda_executable: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Verify the pinned upstream runtime and create its private environment."""
    report_progress = progress or (lambda message: None)
    conda = (
        conda_executable
        or shutil.which("micromamba")
        or shutil.which("mamba")
        or shutil.which("conda")
    )
    if conda is None:
        raise RuntimeError("PocketMiner setup requires micromamba, mamba, or conda on PATH")
    root, repository = installation_root(config), source_root(config)
    root.mkdir(parents=True, exist_ok=True)
    runner = executor or CommandExecutor(root / "setup-commands")
    if repository == VENDORED_HOME:
        report_progress("Checking the included pinned PocketMiner inference code and model")
    else:
        if not repository.exists():
            report_progress("Cloning the official PocketMiner source")
            result = runner.run(
                [
                    "git", "clone", "--filter=blob:none", "--branch", "pocket_pred",
                    "--single-branch", config.repository_url, str(repository),
                ],
                working_directory=root,
            )
            if not result.successful:
                raise RuntimeError(f"PocketMiner clone failed: {result.stderr.strip()}")
        report_progress("Checking out the pinned PocketMiner revision")
        result = runner.run(["git", "fetch", "origin", "pocket_pred"], working_directory=repository)
        if not result.successful:
            raise RuntimeError(f"PocketMiner pinned source fetch failed: {result.stderr.strip()}")
        result = runner.run(["git", "checkout", "--detach", config.commit], working_directory=repository)
        if not result.successful:
            raise RuntimeError(f"PocketMiner checkout verification failed: {result.stderr.strip()}")
    environment = installation_root(config) / "environment"
    environment_exists = environment_python(config).is_file()
    report_progress(
        "Repairing PocketMiner's private scientific environment"
        if environment_exists else
        "Creating PocketMiner's private scientific environment; this can take several minutes"
    )
    dependencies = [
        "python=3.10", "numpy=1.23", "scipy=1.9", "pandas=1.5",
        "mdtraj=1.9.7", "tqdm=4.64", "pyyaml=6", "setuptools=60.5.0",
    ]
    if platform.system() != "Windows":
        dependencies.append("tensorflow=2.10")
    else:
        dependencies.append("pip")
    result = runner.run(
        [
            conda, "install" if environment_exists else "create",
            "--yes", "--prefix", str(environment), "-c", "conda-forge",
            *dependencies,
        ],
        working_directory=root,
    )
    if not result.successful:
        action = "repair" if environment_exists else "creation"
        raise RuntimeError(f"PocketMiner environment {action} failed: {result.stderr.strip()}")
    if platform.system() == "Windows":
        report_progress("Installing PocketMiner's native Windows TensorFlow runtime")
        result = runner.run(
            [
                environment_python(config), "-m", "pip", "install",
                "--disable-pip-version-check", "--no-input", "tensorflow==2.10.1",
                "setuptools==60.5.0",
            ],
            working_directory=root,
        )
        if not result.successful:
            raise RuntimeError(f"PocketMiner TensorFlow installation failed: {result.stderr.strip()}")
    report_progress("Verifying PocketMiner and its model checkpoints")
    report = inspect_installation(config)
    if not report["available"]:
        raise RuntimeError("PocketMiner verification failed: " + "; ".join(report["errors"]))
    atomic_write_json(root / "installation.json", report)
    return report


def run_official(
    config: PocketMinerRuntimeConfig,
    *,
    receptor: str | Path,
    output_npy: str | Path,
    executor: CommandExecutor,
    cancellation: CancellationToken,
    timeout_seconds: float | None,
) -> CommandResult:
    report = inspect_installation(config)
    if not report["available"]:
        raise RuntimeError(
            "PocketMiner is not ready. Run `drug-agent pocketminer-setup`; details: "
            + "; ".join(report["errors"])
        )
    adapter = Path(__file__).with_name("_official_adapter.py")
    prefix = source_root(config) / config.checkpoint_prefix
    return executor.run([
        environment_python(config), adapter,
        "--repository", source_root(config),
        "--receptor", Path(receptor).resolve(),
        "--checkpoint", prefix,
        "--output", Path(output_npy).resolve(),
    ], working_directory=Path(output_npy).resolve().parent,
       environment={"PYTHONDONTWRITEBYTECODE": "1"},
       cancellation=cancellation, timeout_seconds=timeout_seconds)
