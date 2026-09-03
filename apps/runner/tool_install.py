from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping
from urllib.request import Request, urlopen
from uuid import uuid4

from drug_discovery_agent.config.models import PocketMinerRuntimeConfig
from drug_discovery_agent.pocketminer.runtime import setup as setup_pocketminer

from .tool_paths import (
    activate_managed_tools,
    managed_bin,
    managed_plip_environment,
    managed_tools_home,
)


VINA_VERSION = "1.2.7"
VINA_SHA256 = {
    "vina_1.2.7_win.exe": "e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5",
    "vina_1.2.7_linux_x86_64": "f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644",
    "vina_1.2.7_mac_x86_64": "9f44ccbb163223613283a75d0be53235d9e63f4da08292cb7196144f9838b7f9",
    "vina_1.2.7_mac_aarch64": "823c2bbacf26d72183861322345f0a89736aca66c8e81054c66f93af5ad623f1",
}
MICROMAMBA_VERSION = "2.8.1-1"
MICROMAMBA_SHA256 = {
    "micromamba-linux-64": "77b7790ec97f64581118f103585b175df4306f95829b0fa6bfe4a19cc88a1182",
    "micromamba-linux-aarch64": "49aa29008cafa6cd6027ebd643fc43ca32c20740e60b0a05378c4e5bb837c217",
    "micromamba-osx-64": "d6fce18e56d7c6bf2331b0ee1b372a581c70f09b509cc9e924cdd131e053b58a",
    "micromamba-osx-arm64": "9618a2866a2ffb3d36b55e9520f64d63dcd6dc2e622a351ca3cbe8e2cc90c757",
    "micromamba-win-64": "b645a5259cb92b5869b0e60943390dd0d362cae45bc7e2f5ba8c7e4a4b06c7aa",
}
BOLTZ_VERSION = "2.2.1"
PLIP_VERSION = "3.0.1"
OPENBABEL_VERSION = "3.2.1"
BOLTZ_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/98/55/"
    "3eb80fdcf250a0d7bcfcccb584cae200d820fcc158dcdf3f2dbfa4662811/"
    f"boltz-{BOLTZ_VERSION}-py3-none-any.whl"
)
BOLTZ_WHEEL_SHA256 = "b8c62bbdede1922931d9203118f62c858f11aa699bf91fd4c05a5ed6a6d8b4fc"
TORCH_VERSION = "2.7.1"
PYTORCH_CUDA_INDEX = "https://download.pytorch.org/whl"
POCKETMINER_COMMIT = PocketMinerRuntimeConfig().commit
_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
Progress = Callable[[str], None]
Installer = Callable[[Progress], str]


class ToolInstallError(RuntimeError):
    pass


def _platform_key() -> tuple[str, str]:
    system = platform.system()
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        machine = "x86_64"
    elif machine in {"arm64", "aarch64"}:
        machine = "aarch64"
    return system, machine


def vina_download() -> tuple[str, str, str] | None:
    system, machine = _platform_key()
    asset = {
        ("Windows", "x86_64"): f"vina_{VINA_VERSION}_win.exe",
        ("Linux", "x86_64"): f"vina_{VINA_VERSION}_linux_x86_64",
        ("Darwin", "x86_64"): f"vina_{VINA_VERSION}_mac_x86_64",
        ("Darwin", "aarch64"): f"vina_{VINA_VERSION}_mac_aarch64",
    }.get((system, machine))
    if asset is None:
        return None
    return (
        f"https://github.com/ccsb-scripps/AutoDock-Vina/releases/download/"
        f"v{VINA_VERSION}/{asset}",
        asset,
        VINA_SHA256[asset],
    )


def installation_catalog() -> dict[str, dict[str, object]]:
    vina = vina_download()
    pocketminer_automatic = _micromamba_asset() is not None
    boltz_automatic = _micromamba_asset() is not None
    plip_automatic = _micromamba_asset() is not None
    return {
        "AutoDock Vina": {
            "tool_id": "vina",
            "automatic": vina is not None,
            "download_url": vina[0] if vina else None,
            "reason": None if vina else "No official Vina binary is available for this platform.",
        },
        "PocketMiner": {
            "tool_id": "pocketminer",
            "automatic": pocketminer_automatic,
            "download_url": None,
            "reason": (
                None if pocketminer_automatic else
                "Automatic PocketMiner setup is unavailable for this operating system and CPU."
            ),
        },
        "Boltz-2": {
            "tool_id": "boltz",
            "automatic": boltz_automatic,
            "download_url": "https://github.com/jwohlwend/boltz#installation",
            "reason": (
                None if boltz_automatic else
                "Automatic Boltz setup is not available for this operating system and CPU."
            ),
        },
        "PLIP": {
            "tool_id": "plip",
            "automatic": plip_automatic,
            "download_url": "https://github.com/pharmai/plip#1-install-plip",
            "reason": (
                None if plip_automatic else
                "Automatic PLIP setup is not available for this operating system and CPU."
            ),
        },
    }


def _download(url: str, destination: Path, *, maximum_bytes: int, progress: Progress) -> None:
    request = Request(url, headers={"User-Agent": "DrugDiscoveryAgent-Companion/0.1"})
    written = 0
    with urlopen(request, timeout=60) as response, destination.open("wb") as output:
        length = response.headers.get("Content-Length")
        expected = int(length) if length and length.isdigit() else None
        if expected is not None and expected > maximum_bytes:
            raise ToolInstallError("the official download is unexpectedly large")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > maximum_bytes:
                raise ToolInstallError("the official download exceeded the safety limit")
            output.write(chunk)
            if expected:
                progress(f"Downloading from the official release ({written * 100 // expected}%)")
    if written < 100_000:
        raise ToolInstallError("the official download was unexpectedly small")


def _validate_binary_header(path: Path, system: str) -> None:
    with path.open("rb") as binary:
        header = binary.read(4)
    valid = {
        "Windows": header[:2] == b"MZ",
        "Linux": header == b"\x7fELF",
        "Darwin": header in {
            b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
        },
    }.get(system, False)
    if not valid:
        raise ToolInstallError("the downloaded file is not a valid executable for this platform")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as binary:
        for chunk in iter(lambda: binary.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_vina(progress: Progress) -> str:
    selected = vina_download()
    if selected is None:
        raise ToolInstallError("AutoDock Vina has no official binary for this operating system and CPU")
    url, _, expected_sha256 = selected
    target_dir = activate_managed_tools()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / ("vina.exe" if platform.system() == "Windows" else "vina")
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.download")
    if platform.system() == "Windows":
        temporary = temporary.with_suffix(".exe")
    try:
        progress("Downloading AutoDock Vina from its official GitHub release")
        _download(url, temporary, maximum_bytes=_MAX_DOWNLOAD_BYTES, progress=progress)
        _validate_binary_header(temporary, platform.system())
        progress("Checking the official Vina file integrity")
        if _sha256(temporary) != expected_sha256:
            raise ToolInstallError("the downloaded Vina file did not match its pinned SHA-256 checksum")
        if platform.system() != "Windows":
            temporary.chmod(0o755)
        progress("Verifying the downloaded Vina executable")
        result = subprocess.run(
            [str(temporary), "--version"], capture_output=True, text=True, timeout=15,
        )
        version_text = (result.stdout or result.stderr).strip().splitlines()
        version = version_text[0][:160] if version_text else ""
        if result.returncode != 0 or VINA_VERSION not in version:
            raise ToolInstallError("the Vina executable failed its version check")
        os.replace(temporary, target)
        if platform.system() != "Windows":
            target.chmod(0o755)
        activate_managed_tools()
        return f"AutoDock Vina {VINA_VERSION} is installed and ready."
    finally:
        temporary.unlink(missing_ok=True)


def _micromamba_asset() -> tuple[str, str] | None:
    asset = {
        ("Linux", "x86_64"): "micromamba-linux-64",
        ("Linux", "aarch64"): "micromamba-linux-aarch64",
        ("Darwin", "x86_64"): "micromamba-osx-64",
        ("Darwin", "aarch64"): "micromamba-osx-arm64",
        ("Windows", "x86_64"): "micromamba-win-64",
    }.get(_platform_key())
    return (asset, MICROMAMBA_SHA256[asset]) if asset else None


def _managed_micromamba(progress: Progress) -> Path:
    selected = _micromamba_asset()
    if selected is None:
        raise ToolInstallError(
            "automatic managed-tool setup is unavailable for this operating system and CPU"
        )
    asset, expected_sha256 = selected
    executable_name = "micromamba.exe" if platform.system() == "Windows" else "micromamba"
    destination = managed_tools_home() / "micromamba" / "bin" / executable_name
    if destination.is_file() and _sha256(destination) == expected_sha256:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".micromamba-{uuid4().hex}{'.exe' if platform.system() == 'Windows' else ''}"
    )
    try:
        progress("Downloading the private environment manager for scientific tools")
        _download(
            f"https://github.com/mamba-org/micromamba-releases/releases/download/"
            f"{MICROMAMBA_VERSION}/{asset}",
            temporary,
            maximum_bytes=_MAX_DOWNLOAD_BYTES,
            progress=progress,
        )
        progress("Checking the environment manager file integrity")
        if _sha256(temporary) != expected_sha256:
            raise ToolInstallError("the environment manager did not match its pinned SHA-256 checksum")
        if platform.system() != "Windows":
            temporary.chmod(0o755)
        result = subprocess.run(
            [str(temporary), "--version"], capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            raise ToolInstallError("the managed environment manager failed verification")
        os.replace(temporary, destination)
        if platform.system() != "Windows":
            destination.chmod(0o755)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def install_pocketminer(progress: Progress) -> str:
    conda = _managed_micromamba(progress)
    progress("Verifying the included pinned PocketMiner inference code and model")
    setup_pocketminer(
        PocketMinerRuntimeConfig(),
        conda_executable=str(conda),
        progress=progress,
    )
    return "PocketMiner's included pinned runtime is installed and ready."


def _boltz_environment_paths() -> tuple[Path, Path, Path]:
    environment = managed_tools_home() / "boltz" / "environment"
    if platform.system() == "Windows":
        # Conda environments place python.exe at the environment root on Windows;
        # only installed console launchers live under Scripts.
        return environment, environment / "python.exe", environment / "Scripts" / "boltz.exe"
    return environment, environment / "bin" / "python", environment / "bin" / "boltz"


def _plip_environment_paths() -> tuple[Path, Path, Path]:
    environment = managed_tools_home() / "plip" / "environment"
    if platform.system() == "Windows":
        return environment, environment / "python.exe", environment / "Scripts" / "plip.exe"
    return environment, environment / "bin" / "python", environment / "bin" / "plip"


def _run_setup_command(command: list[str], *, environment: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolInstallError(f"automatic tool setup could not run: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no diagnostic output").strip()[-1000:]
        raise ToolInstallError(f"automatic tool setup failed: {detail}")
    return result


def _nvidia_gpu_runtime() -> tuple[str, str] | None:
    """Return the first NVIDIA GPU and newest compatible pinned PyTorch CUDA wheel."""
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None
    try:
        gpu_result = subprocess.run(
            [executable, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        runtime_result = subprocess.run(
            [executable], capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    names = gpu_result.stdout.strip().splitlines()
    match = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", runtime_result.stdout)
    if gpu_result.returncode != 0 or runtime_result.returncode != 0 or not names or not match:
        return None
    maximum_cuda = (int(match.group(1)), int(match.group(2)))
    cuda_tag = next(
        (
            tag for minimum, tag in (
                ((12, 8), "cu128"),
                ((12, 6), "cu126"),
                ((11, 8), "cu118"),
            )
            if maximum_cuda >= minimum
        ),
        None,
    )
    return (names[0].strip()[:160], cuda_tag) if cuda_tag else None


def _write_boltz_metadata(
    *,
    cuda_extra: bool,
    gpu_enabled: bool,
    gpu_name: str | None,
    torch_version: str | None,
    torch_cuda: str | None,
) -> None:
    metadata_path = managed_tools_home() / "boltz" / "installation.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = metadata_path.with_name(f".{metadata_path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                {
                    "tool": "Boltz-2",
                    "version": BOLTZ_VERSION,
                    "cuda_extra": cuda_extra,
                    "gpu_enabled": gpu_enabled,
                    "gpu_name": gpu_name,
                    "torch_version": torch_version,
                    "torch_cuda": torch_cuda,
                    "wheel_sha256": BOLTZ_WHEEL_SHA256,
                },
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, metadata_path)
    finally:
        temporary.unlink(missing_ok=True)


def install_boltz(progress: Progress) -> str:
    conda = _managed_micromamba(progress)
    environment_path, python_path, source_launcher = _boltz_environment_paths()
    environment = os.environ.copy()
    environment["MAMBA_ROOT_PREFIX"] = str(managed_tools_home() / "micromamba" / "root")

    environment_path.parent.mkdir(parents=True, exist_ok=True)
    if not python_path.is_file():
        progress("Creating Boltz's private Python 3.12 environment")
        _run_setup_command(
            [
                str(conda), "create", "--yes", "--prefix", str(environment_path),
                "--channel", "conda-forge", "python=3.12", "pip",
            ],
            environment=environment,
            timeout=1800,
        )

    download_directory = managed_tools_home() / "boltz" / "downloads"
    download_directory.mkdir(parents=True, exist_ok=True)
    wheel = download_directory / f"boltz-{BOLTZ_VERSION}-py3-none-any.whl"
    temporary_wheel = wheel.with_name(f".{wheel.name}.{uuid4().hex}.download")
    try:
        if not wheel.is_file() or _sha256(wheel) != BOLTZ_WHEEL_SHA256:
            progress("Downloading the pinned official Boltz package")
            _download(
                BOLTZ_WHEEL_URL,
                temporary_wheel,
                maximum_bytes=_MAX_DOWNLOAD_BYTES,
                progress=progress,
            )
            progress("Checking the official Boltz package integrity")
            if _sha256(temporary_wheel) != BOLTZ_WHEEL_SHA256:
                raise ToolInstallError(
                    "the downloaded Boltz package did not match its pinned SHA-256 checksum"
                )
            os.replace(temporary_wheel, wheel)

        nvidia_runtime = _nvidia_gpu_runtime()
        cuda_extra = platform.system() == "Linux" and nvidia_runtime is not None
        install_mode = (
            f"NVIDIA GPU support for {nvidia_runtime[0]}"
            if nvidia_runtime else "standard core support"
        )
        progress(f"Installing Boltz and its dependencies with {install_mode}")
        extras = "[cuda]" if cuda_extra else ""
        requirement = f"boltz{extras} @ {wheel.resolve().as_uri()}"
        _run_setup_command(
            [
                str(python_path), "-m", "pip", "install", "--disable-pip-version-check",
                "--no-input", "--upgrade", requirement,
            ],
            environment=environment,
            timeout=3600,
        )

        # Install the pinned CUDA build last. Installing Boltz after PyTorch can
        # replace the CUDA wheel with PyPI's CPU-only build while resolving
        # dependencies, which previously made an RTX GPU appear unavailable.
        if nvidia_runtime:
            detected_gpu, cuda_tag = nvidia_runtime
            progress(
                f"Installing CUDA-enabled PyTorch {TORCH_VERSION} for {detected_gpu}"
            )
            _run_setup_command(
                [
                    str(python_path), "-m", "pip", "install",
                    "--disable-pip-version-check", "--no-input", "--upgrade",
                    f"torch=={TORCH_VERSION}",
                    "--index-url", f"{PYTORCH_CUDA_INDEX}/{cuda_tag}",
                ],
                environment=environment,
                timeout=3600,
            )

        progress("Verifying the installed Boltz version")
        version_result = _run_setup_command(
            [
                str(python_path), "-c",
                "import importlib.metadata; print(importlib.metadata.version('boltz'))",
            ],
            environment=environment,
            timeout=30,
        )
        if version_result.stdout.strip() != BOLTZ_VERSION:
            raise ToolInstallError(
                f"Boltz installed version {version_result.stdout.strip() or 'unknown'}, "
                f"but version {BOLTZ_VERSION} is required"
            )
        if not source_launcher.is_file():
            raise ToolInstallError("Boltz installed without creating its command-line launcher")

        gpu_enabled = False
        gpu_name = None
        torch_version = None
        torch_cuda = None
        if nvidia_runtime:
            progress("Verifying that Boltz's PyTorch runtime can use the NVIDIA GPU")
            gpu_result = _run_setup_command(
                [
                    str(python_path), "-c",
                    (
                        "import json,torch; available=torch.cuda.is_available(); "
                        "print(json.dumps({'available':available,"
                        "'name':torch.cuda.get_device_name(0) if available else None,"
                        "'torch':torch.__version__,'cuda':torch.version.cuda}))"
                    ),
                ],
                environment=environment,
                timeout=120,
            )
            try:
                gpu_report = json.loads(gpu_result.stdout.strip().splitlines()[-1])
            except (IndexError, json.JSONDecodeError) as exc:
                raise ToolInstallError("PyTorch did not return a valid GPU verification result") from exc
            gpu_enabled = gpu_report.get("available") is True
            gpu_name = str(gpu_report.get("name"))[:160] if gpu_report.get("name") else None
            torch_version = (
                str(gpu_report.get("torch"))[:80] if gpu_report.get("torch") else None
            )
            torch_cuda = (
                str(gpu_report.get("cuda"))[:40] if gpu_report.get("cuda") else None
            )
            if not gpu_enabled:
                raise ToolInstallError(
                    "an NVIDIA GPU was detected, but the installed PyTorch runtime could not use it"
                )
        _run_setup_command(
            [str(source_launcher), "--help"],
            environment=environment,
            timeout=120,
        )

        target_directory = activate_managed_tools()
        target_directory.mkdir(parents=True, exist_ok=True)
        target = target_directory / ("boltz.exe" if platform.system() == "Windows" else "boltz")
        temporary_launcher = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            shutil.copy2(source_launcher, temporary_launcher)
            if platform.system() != "Windows":
                temporary_launcher.chmod(0o755)
            os.replace(temporary_launcher, target)
        finally:
            temporary_launcher.unlink(missing_ok=True)
        _write_boltz_metadata(
            cuda_extra=cuda_extra,
            gpu_enabled=gpu_enabled,
            gpu_name=gpu_name,
            torch_version=torch_version,
            torch_cuda=torch_cuda,
        )
        activate_managed_tools()
        return (
            f"Boltz {BOLTZ_VERSION} is installed with {install_mode} and ready. "
            "Boltz model weights download automatically on its first run."
        )
    finally:
        temporary_wheel.unlink(missing_ok=True)


def _write_plip_metadata() -> None:
    metadata_path = managed_tools_home() / "plip" / "installation.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = metadata_path.with_name(f".{metadata_path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                {
                    "tool": "PLIP",
                    "version": PLIP_VERSION,
                    "openbabel_version": OPENBABEL_VERSION,
                },
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, metadata_path)
    finally:
        temporary.unlink(missing_ok=True)


def install_plip(progress: Progress) -> str:
    """Install PLIP with a matched Open Babel build in a private environment."""
    conda = _managed_micromamba(progress)
    environment_path, python_path, source_launcher = _plip_environment_paths()
    environment = os.environ.copy()
    environment["MAMBA_ROOT_PREFIX"] = str(managed_tools_home() / "micromamba" / "root")
    scientific_packages = [
        "python=3.12",
        "pip",
        "numpy",
        "lxml",
        f"openbabel={OPENBABEL_VERSION}",
    ]
    environment_path.parent.mkdir(parents=True, exist_ok=True)
    if python_path.is_file():
        progress("Updating PLIP's private Open Babel environment")
        environment_command = [
            str(conda), "install", "--yes", "--prefix", str(environment_path),
            "--channel", "conda-forge", "--strict-channel-priority", *scientific_packages,
        ]
    else:
        progress("Creating PLIP's private Open Babel environment")
        environment_command = [
            str(conda), "create", "--yes", "--prefix", str(environment_path),
            "--channel", "conda-forge", "--strict-channel-priority", *scientific_packages,
        ]
    _run_setup_command(environment_command, environment=environment, timeout=1800)
    plip_environment = managed_plip_environment(environment_path)
    if plip_environment is None:
        raise ToolInstallError("PLIP's private Open Babel activation paths are unavailable")
    environment.update(plip_environment)

    progress(f"Installing pinned PLIP {PLIP_VERSION}")
    _run_setup_command(
        [
            str(python_path), "-m", "pip", "install", "--disable-pip-version-check",
            "--no-input", "--upgrade", "--no-deps", f"plip=={PLIP_VERSION}",
        ],
        environment=environment,
        timeout=900,
    )
    if not source_launcher.is_file():
        raise ToolInstallError("PLIP installed without creating its command-line launcher")

    progress("Verifying PLIP and Open Babel InChIKey support")
    version_result = _run_setup_command(
        [
            str(python_path), "-c",
            "import importlib.metadata; print(importlib.metadata.version('plip'))",
        ],
        environment=environment,
        timeout=30,
    )
    if version_result.stdout.strip() != PLIP_VERSION:
        raise ToolInstallError(
            f"PLIP installed version {version_result.stdout.strip() or 'unknown'}, "
            f"but version {PLIP_VERSION} is required"
        )
    inchikey_result = _run_setup_command(
        [
            str(python_path), "-c",
            (
                "from openbabel import pybel; "
                "key=pybel.readstring('smi','CC').write('inchikey').strip(); "
                "assert len(key)==27, key; print(key)"
            ),
        ],
        environment=environment,
        timeout=30,
    )
    if len(inchikey_result.stdout.strip()) != 27:
        raise ToolInstallError("Open Babel did not return a valid InChIKey")
    _run_setup_command([str(source_launcher), "--help"], environment=environment, timeout=30)

    target_directory = activate_managed_tools()
    target_directory.mkdir(parents=True, exist_ok=True)
    target = target_directory / ("plip.exe" if platform.system() == "Windows" else "plip")
    temporary_launcher = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        shutil.copy2(source_launcher, temporary_launcher)
        if platform.system() != "Windows":
            temporary_launcher.chmod(0o755)
        os.replace(temporary_launcher, target)
    finally:
        temporary_launcher.unlink(missing_ok=True)
    _write_plip_metadata()
    activate_managed_tools()
    return (
        f"PLIP {PLIP_VERSION} with Open Babel {OPENBABEL_VERSION} and verified "
        "InChIKey support is installed and ready."
    )


@dataclass(slots=True)
class InstallTask:
    task_id: str
    tool_id: str
    status: str = "queued"
    message: str = "Waiting to start"


class ToolInstallManager:
    def __init__(self, installers: Mapping[str, Installer] | None = None) -> None:
        self._installers = dict(installers or {
            "vina": install_vina,
            "pocketminer": install_pocketminer,
            "boltz": install_boltz,
            "plip": install_plip,
        })
        self._tasks: dict[str, InstallTask] = {}
        self._active: dict[str, str] = {}
        self._lock = threading.Lock()

    def catalog(self) -> dict[str, dict[str, object]]:
        catalog = installation_catalog()
        supported_ids = set(self._installers)
        return {
            name: details for name, details in catalog.items()
            if details["tool_id"] in supported_ids
        }

    def start(self, tool_id: str) -> dict[str, str]:
        installer = self._installers.get(tool_id)
        if installer is None:
            raise KeyError(tool_id)
        with self._lock:
            active_id = self._active.get(tool_id)
            if active_id and self._tasks[active_id].status in {"queued", "installing"}:
                return asdict(self._tasks[active_id])
            task = InstallTask(task_id=uuid4().hex, tool_id=tool_id)
            self._tasks[task.task_id] = task
            self._active[tool_id] = task.task_id

        def update(message: str) -> None:
            with self._lock:
                task.message = message[:500]

        def run() -> None:
            with self._lock:
                task.status = "installing"
                task.message = "Starting automatic setup"
            try:
                message = installer(update)
            except Exception as exc:
                with self._lock:
                    task.status = "failed"
                    task.message = str(exc)[:500] or "Automatic setup failed"
            else:
                with self._lock:
                    task.status = "success"
                    task.message = message[:500]

        threading.Thread(
            target=run, daemon=True, name=f"install-{tool_id}-{task.task_id[:8]}",
        ).start()
        return asdict(task)

    def status(self, task_id: str) -> dict[str, str]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            return asdict(task)
