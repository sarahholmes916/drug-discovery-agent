from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass

from drug_discovery_agent.config.models import PocketMinerRuntimeConfig
from drug_discovery_agent.pocketminer.runtime import inspect_installation
from drug_discovery_agent.project.hashing import stable_json_hash

from .tool_paths import managed_command, managed_tool_metadata


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    available: bool
    version: str | None = None
    detail: str | None = None


def _python_package(display: str, module: str, distribution: str | None = None) -> Capability:
    available = importlib.util.find_spec(module) is not None
    version = None
    if available:
        try:
            version = importlib.metadata.version(distribution or module)
        except importlib.metadata.PackageNotFoundError:
            pass
    return Capability(display, available, version)


def _python_cli(display: str, module: str, command: str, version_args: list[str]) -> Capability:
    try:
        available = importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError):
        available = False
    if available:
        try:
            version = importlib.metadata.version("meeko")
        except importlib.metadata.PackageNotFoundError:
            version = None
        return Capability(display, True, version)
    return _command(display, command, version_args)


def _command(display: str, command: str, version_args: list[str]) -> Capability:
    executable = managed_command(command) or shutil.which(command)
    if not executable:
        return Capability(display, False)
    try:
        result = subprocess.run([executable, *version_args], capture_output=True, text=True, timeout=5)
        lines = (result.stdout or result.stderr).strip().splitlines()
        version = lines[0][:160] if lines else None
    except (OSError, subprocess.SubprocessError):
        version = None
    return Capability(display, True, version)


def _boltz_command() -> Capability:
    managed = managed_command("boltz")
    metadata = managed_tool_metadata("boltz") if managed else None
    if managed and metadata and isinstance(metadata.get("version"), str):
        if metadata.get("gpu_enabled") is True:
            gpu_name = metadata.get("gpu_name") or "NVIDIA GPU"
            torch_cuda = metadata.get("torch_cuda") or "unknown"
            mode = f"GPU: {gpu_name}; CUDA {torch_cuda}"
            return Capability("Boltz-2", True, f"{metadata['version']} ({mode})")
        return Capability(
            "Boltz-2",
            False,
            f"{metadata['version']} (GPU runtime unavailable)",
            "Run automatic Boltz setup again to install and verify CUDA-enabled PyTorch.",
        )
    return _command("Boltz-2", "boltz", ["--help"])


def _plip_command() -> Capability:
    managed = managed_command("plip")
    metadata = managed_tool_metadata("plip") if managed else None
    if managed and metadata and isinstance(metadata.get("version"), str):
        openbabel = metadata.get("openbabel_version") or "unknown"
        return Capability(
            "PLIP", True, f"{metadata['version']} (Open Babel {openbabel}; InChIKey verified)",
        )
    return _command("PLIP", "plip", ["--help"])


def _hardware() -> list[Capability]:
    cpu = Capability("CPU", True, detail=f"{os.cpu_count() or 1} logical cores; {platform.processor() or platform.machine()}")
    ram_detail = None
    try:
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                        ("total_physical", ctypes.c_ulonglong), ("available_physical", ctypes.c_ulonglong),
                        ("total_page_file", ctypes.c_ulonglong), ("available_page_file", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
                        ("available_extended_virtual", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if platform.system() == "Windows" and ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            ram_detail = f"{status.total_physical / (1024 ** 3):.1f} GiB total"
    except Exception:
        pass
    ram = Capability("RAM", ram_detail is not None, detail=ram_detail or "detection unavailable")
    gpu_tool = shutil.which("nvidia-smi")
    if not gpu_tool:
        gpu = Capability("GPU", False)
        cuda = Capability("CUDA", False)
    else:
        try:
            result = subprocess.run([gpu_tool, "--query-gpu=name,driver_version", "--format=csv,noheader"],
                                    capture_output=True, text=True, timeout=5)
            detail = result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else None
        except (OSError, subprocess.SubprocessError):
            detail = None
        gpu = Capability("GPU", detail is not None, detail=detail)
        cuda = Capability("CUDA", detail is not None, detail="NVIDIA driver detected" if detail else None)
    return [cpu, ram, gpu, cuda]


def collect_capabilities(pocketminer_runtime: PocketMinerRuntimeConfig | None = None) -> list[Capability]:
    pocketminer = inspect_installation(pocketminer_runtime or PocketMinerRuntimeConfig())
    checkpoint_hashes = pocketminer.get("checkpoint_sha256", {})
    checkpoint_identity = ",".join(f"{name}:{digest}" for name, digest in checkpoint_hashes.items())
    model_hash = stable_json_hash(checkpoint_hashes) if checkpoint_hashes else None
    return [
        Capability("Python", True, platform.python_version()),
        _python_package("NumPy", "numpy"),
        _python_package("RDKit", "rdkit"),
        _python_package("Meeko", "meeko"),
        _python_package("OpenPyXL", "openpyxl"),
        _command("AutoDock Vina", "vina", ["--version"]),
        _python_cli("Meeko CLI", "meeko.cli.mk_prepare_ligand", "mk_prepare_ligand.py", ["--version"]),
        _python_cli(
            "Meeko receptor CLI",
            "meeko.cli.mk_prepare_receptor",
            "mk_prepare_receptor.py",
            ["--help"],
        ),
        _boltz_command(),
        _plip_command(),
        Capability(
            "PocketMiner",
            bool(pocketminer["available"]),
            version=(
                f"Mickdub/gvp:pocket_pred@{pocketminer.get('commit')}; model_sha256={model_hash}"
                if pocketminer.get("commit") else None
            ),
            detail="; ".join(pocketminer.get("errors", [])) or f"checkpoint files: {checkpoint_identity}",
        ),
        *_hardware(),
    ]


def cloud_capabilities(capabilities: list[Capability]) -> dict[str, object]:
    """Return only non-sensitive booleans/versions; never system paths or files."""
    return {
        "tools": {
            item.name.lower().replace(" ", "_").replace("-", "_"): {
                "available": item.available,
                "version": item.version,
            }
            for item in capabilities
        }
    }


def capability_dicts(capabilities: list[Capability]) -> list[dict[str, object]]:
    return [asdict(item) for item in capabilities]
