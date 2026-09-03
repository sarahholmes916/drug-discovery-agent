from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from apps.runner import tool_install
from apps.runner.tool_install import ToolInstallManager


def test_vina_managed_install_downloads_verifies_and_activates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DRUG_AGENT_TOOLS_HOME", str(tmp_path / "tools"))
    monkeypatch.setattr(tool_install.platform, "system", lambda: "Windows")
    monkeypatch.setattr(tool_install.platform, "machine", lambda: "AMD64")

    downloaded: list[str] = []

    def fake_download(url, destination, **kwargs) -> None:
        downloaded.append(url)
        destination.write_bytes(b"MZ" + b"\0" * 100_000)

    monkeypatch.setattr(tool_install, "_download", fake_download)
    monkeypatch.setattr(
        tool_install,
        "_sha256",
        lambda path: tool_install.VINA_SHA256["vina_1.2.7_win.exe"],
    )
    monkeypatch.setattr(
        tool_install.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="AutoDock Vina v1.2.7\n", stderr="",
        ),
    )

    messages: list[str] = []
    result = tool_install.install_vina(messages.append)

    assert "ready" in result
    assert (tmp_path / "tools" / "bin" / "vina.exe").is_file()
    assert downloaded == [
        "https://github.com/ccsb-scripps/AutoDock-Vina/releases/download/"
        "v1.2.7/vina_1.2.7_win.exe"
    ]
    assert any("Verifying" in message for message in messages)


def test_windows_catalog_offers_managed_pocketminer_without_source_zip(monkeypatch) -> None:
    monkeypatch.setattr(tool_install.platform, "system", lambda: "Windows")
    monkeypatch.setattr(tool_install.platform, "machine", lambda: "AMD64")

    catalog = tool_install.installation_catalog()

    assert catalog["AutoDock Vina"]["automatic"] is True
    assert catalog["AutoDock Vina"]["download_url"].endswith("vina_1.2.7_win.exe")
    assert catalog["PocketMiner"]["automatic"] is True
    assert catalog["PocketMiner"]["download_url"] is None
    assert catalog["PocketMiner"]["reason"] is None
    assert catalog["Boltz-2"]["automatic"] is True
    assert catalog["Boltz-2"]["tool_id"] == "boltz"
    assert catalog["PLIP"]["automatic"] is True
    assert catalog["PLIP"]["tool_id"] == "plip"


def test_pocketminer_install_uses_included_runtime_and_managed_environment(
    tmp_path: Path, monkeypatch,
) -> None:
    micromamba = tmp_path / "micromamba.exe"
    micromamba.write_bytes(b"MZ")
    monkeypatch.setattr(tool_install, "_managed_micromamba", lambda progress: micromamba)
    calls: list[tuple[object, str]] = []

    def fake_setup(config, *, conda_executable, progress):
        calls.append((config, conda_executable))
        progress("Verified included PocketMiner files")
        return {"available": True}

    monkeypatch.setattr(tool_install, "setup_pocketminer", fake_setup)
    messages: list[str] = []

    result = tool_install.install_pocketminer(messages.append)

    assert "included pinned runtime" in result
    assert len(calls) == 1
    assert calls[0][1] == str(micromamba)
    assert calls[0][0].commit == tool_install.POCKETMINER_COMMIT
    assert any("included pinned PocketMiner" in message for message in messages)


def test_boltz_managed_install_uses_pinned_wheel_and_publishes_launcher(
    tmp_path: Path, monkeypatch,
) -> None:
    tools_home = tmp_path / "tools"
    monkeypatch.setenv("DRUG_AGENT_TOOLS_HOME", str(tools_home))
    monkeypatch.setattr(tool_install.platform, "system", lambda: "Windows")
    monkeypatch.setattr(tool_install.platform, "machine", lambda: "AMD64")
    micromamba = tmp_path / "micromamba.exe"
    micromamba.write_bytes(b"MZ")
    monkeypatch.setattr(tool_install, "_managed_micromamba", lambda progress: micromamba)
    monkeypatch.setattr(
        tool_install,
        "_nvidia_gpu_runtime",
        lambda: ("NVIDIA GeForce RTX Test", "cu128"),
    )

    environment = tools_home / "boltz" / "environment"
    python = environment / "python.exe"
    launcher = environment / "Scripts" / "boltz.exe"

    downloads: list[str] = []

    def fake_download(url, destination, **kwargs) -> None:
        downloads.append(url)
        destination.write_bytes(b"wheel" * 25_000)

    monkeypatch.setattr(tool_install, "_download", fake_download)
    monkeypatch.setattr(tool_install, "_sha256", lambda path: tool_install.BOLTZ_WHEEL_SHA256)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if len(command) > 1 and command[1] == "create":
            python.parent.mkdir(parents=True)
            launcher.parent.mkdir(parents=True)
            python.write_bytes(b"MZ")
        if "-m" in command and command[command.index("-m") + 1] == "pip":
            launcher.write_bytes(b"MZ launcher")
        if "-c" in command:
            if "torch.cuda.is_available" in command[-1]:
                return SimpleNamespace(
                    returncode=0,
                    stdout=(
                        '{"available": true, "name": "NVIDIA GeForce RTX Test", '
                        '"torch": "2.7.1+cu128", "cuda": "12.8"}\n'
                    ),
                    stderr="",
                )
            return SimpleNamespace(returncode=0, stdout=f"{tool_install.BOLTZ_VERSION}\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(tool_install.subprocess, "run", fake_run)
    messages: list[str] = []

    result = tool_install.install_boltz(messages.append)

    assert "ready" in result
    assert downloads == [tool_install.BOLTZ_WHEEL_URL]
    assert (tools_home / "bin" / "boltz.exe").read_bytes() == b"MZ launcher"
    metadata = json.loads(
        (tools_home / "boltz" / "installation.json").read_text(encoding="utf-8")
    )
    assert metadata == {
        "cuda_extra": False,
        "gpu_enabled": True,
        "gpu_name": "NVIDIA GeForce RTX Test",
        "tool": "Boltz-2",
        "torch_cuda": "12.8",
        "torch_version": "2.7.1+cu128",
        "version": tool_install.BOLTZ_VERSION,
        "wheel_sha256": tool_install.BOLTZ_WHEEL_SHA256,
    }
    pip_commands = [command for command in commands if "-m" in command and "pip" in command]
    assert len(pip_commands) == 2
    assert all(command[0] == str(environment / "python.exe") for command in pip_commands)
    torch_command = next(command for command in pip_commands if "torch==2.7.1" in command)
    assert torch_command[-1] == "https://download.pytorch.org/whl/cu128"
    boltz_command = next(command for command in pip_commands if command[-1].startswith("boltz @ file:"))
    assert boltz_command[-1].startswith("boltz @ file:")
    assert commands.index(boltz_command) < commands.index(torch_command)
    assert any(len(command) > 1 and command[1] == "create" for command in commands)
    assert any("Verifying" in message for message in messages)


def test_plip_managed_install_pins_openbabel_and_verifies_inchikey(
    tmp_path: Path, monkeypatch,
) -> None:
    tools_home = tmp_path / "tools"
    monkeypatch.setenv("DRUG_AGENT_TOOLS_HOME", str(tools_home))
    monkeypatch.setattr(tool_install.platform, "system", lambda: "Windows")
    monkeypatch.setattr(tool_install.platform, "machine", lambda: "AMD64")
    micromamba = tmp_path / "micromamba.exe"
    micromamba.write_bytes(b"MZ")
    monkeypatch.setattr(tool_install, "_managed_micromamba", lambda progress: micromamba)

    environment = tools_home / "plip" / "environment"
    python = environment / "python.exe"
    launcher = environment / "Scripts" / "plip.exe"
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if len(command) > 1 and command[1] == "create":
            python.parent.mkdir(parents=True)
            launcher.parent.mkdir(parents=True)
            (environment / "Library" / "bin").mkdir(parents=True)
            (environment / "share" / "openbabel").mkdir(parents=True)
            python.write_bytes(b"MZ")
        if "-m" in command and command[command.index("-m") + 1] == "pip":
            launcher.write_bytes(b"MZ launcher")
        if "-c" in command:
            if "importlib.metadata" in command[-1]:
                return SimpleNamespace(
                    returncode=0, stdout=f"{tool_install.PLIP_VERSION}\n", stderr="",
                )
            return SimpleNamespace(returncode=0, stdout="OTMSDBZUPAUEDD-UHFFFAOYSA-N\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(tool_install.subprocess, "run", fake_run)
    messages: list[str] = []

    result = tool_install.install_plip(messages.append)

    assert "ready" in result
    assert (tools_home / "bin" / "plip.exe").read_bytes() == b"MZ launcher"
    create = next(command for command in commands if len(command) > 1 and command[1] == "create")
    assert f"openbabel={tool_install.OPENBABEL_VERSION}" in create
    pip = next(command for command in commands if "-m" in command and "pip" in command)
    assert f"plip=={tool_install.PLIP_VERSION}" in pip
    assert "--no-deps" in pip
    metadata = json.loads(
        (tools_home / "plip" / "installation.json").read_text(encoding="utf-8")
    )
    assert metadata == {
        "openbabel_version": tool_install.OPENBABEL_VERSION,
        "tool": "PLIP",
        "version": tool_install.PLIP_VERSION,
    }
    assert any("InChIKey" in message for message in messages)


def test_nvidia_runtime_selects_newest_supported_pytorch_cuda_wheel(monkeypatch) -> None:
    monkeypatch.setattr(tool_install.shutil, "which", lambda command: "/usr/bin/nvidia-smi")

    def fake_run(command, **kwargs):
        if "--query-gpu=name" in command:
            return SimpleNamespace(returncode=0, stdout="NVIDIA GeForce RTX 5090\n", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout="NVIDIA-SMI 596.49 Driver Version: 596.49 CUDA Version: 13.2\n",
            stderr="",
        )

    monkeypatch.setattr(tool_install.subprocess, "run", fake_run)
    assert tool_install._nvidia_gpu_runtime() == ("NVIDIA GeForce RTX 5090", "cu128")


def test_install_manager_reports_background_progress_and_reuses_active_task() -> None:
    release = False

    def installer(progress) -> str:
        nonlocal release
        progress("Downloading")
        while not release:
            time.sleep(0.001)
        return "Ready"

    manager = ToolInstallManager({"vina": installer})
    first = manager.start("vina")
    second = manager.start("vina")
    assert second["task_id"] == first["task_id"]

    release = True
    deadline = time.monotonic() + 2
    status = manager.status(first["task_id"])
    while status["status"] != "success" and time.monotonic() < deadline:
        time.sleep(0.005)
        status = manager.status(first["task_id"])
    assert status["message"] == "Ready"
