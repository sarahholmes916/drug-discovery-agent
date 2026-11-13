from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from drug_discovery_agent import platform_support as support
from apps.runner import doctor, tool_install
from drug_discovery_agent.boltz.runner import build_boltz_command
from drug_discovery_agent.config.models import BoltzConfig


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("DRUG_AGENT_HOME", raising=False)
    monkeypatch.delenv("DRUG_AGENT_TOOLS_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return tmp_path


def test_mac_paths_and_existing_projects(isolated_home, monkeypatch):
    monkeypatch.setattr(support.platform, "system", lambda: "Darwin")
    assert support.data_home() == isolated_home / "Library/Application Support/DrugDiscoveryAgent"
    assert support.tools_home() == support.data_home() / "tools"
    old = isolated_home / "DrugDiscoveryAgent"
    old.mkdir()
    (old / "registry.json").write_text('{"projects":{"old":"unchanged"}}')
    assert support.data_home() == old
    assert "unchanged" in (support.data_home() / "registry.json").read_text()
    tools = isolated_home / ".drug-agent/tools"
    tools.mkdir(parents=True)
    assert support.tools_home() == tools


def test_explicit_paths_take_precedence(isolated_home, monkeypatch):
    monkeypatch.setenv("DRUG_AGENT_HOME", str(isolated_home / "Research Data"))
    monkeypatch.setenv("DRUG_AGENT_TOOLS_HOME", str(isolated_home / "Scientific Tools"))
    assert support.data_home().name == "Research Data"
    assert support.tools_home().name == "Scientific Tools"


def test_frozen_linux_child_restores_original_library_path(monkeypatch):
    monkeypatch.setattr(support.sys, "frozen", True, raising=False)
    monkeypatch.setattr(support.sys, "platform", "linux")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundle:/original")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/original")
    assert support.external_environment()["LD_LIBRARY_PATH"] == "/original"
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG")
    assert "LD_LIBRARY_PATH" not in support.external_environment()


@pytest.mark.parametrize("system,machine,asset", [
    ("Windows", "AMD64", "win.exe"), ("Darwin", "arm64", "mac_aarch64"),
    ("Darwin", "x86_64", "mac_x86_64"), ("Linux", "x86_64", "linux_x86_64"),
])
def test_native_vina_selection(system, machine, asset, monkeypatch):
    monkeypatch.setattr(support.platform, "system", lambda: system)
    monkeypatch.setattr(support.platform, "machine", lambda: machine)
    url, filename, digest = tool_install.vina_download()
    assert filename.endswith(asset)
    assert url.endswith(filename) and len(digest) == 64


def test_intel_mac_boltz_explains_unavailable_install(monkeypatch):
    monkeypatch.setattr(support.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(support.platform, "machine", lambda: "x86_64")
    item = tool_install.installation_catalog()["Boltz-2"]
    assert not item["automatic"]
    assert "Intel" in item["reason"]
    with pytest.raises(tool_install.ToolInstallError, match="Intel"):
        tool_install.install_boltz(lambda _: None)


def test_cpu_runtime_is_available_without_cuda(monkeypatch):
    monkeypatch.setattr(doctor, "managed_command", lambda _: Path("boltz"))
    monkeypatch.setattr(doctor, "managed_tool_metadata", lambda _: {
        "version": "2.2.1", "gpu_enabled": False, "cpu_verified": True,
    })
    capability = doctor._boltz_command()
    assert capability.available
    assert "CPU" in capability.version
    assert "accelerator" in capability.detail


def test_mac_default_boltz_accelerator_requires_explicit_cpu_selection(monkeypatch):
    monkeypatch.setattr(support.platform, "system", lambda: "Darwin")
    with pytest.raises(ValueError, match="Select boltz.accelerator: cpu explicitly"):
        build_boltz_command("input.yaml", "output", BoltzConfig())


def test_apple_silicon_boltz_install_uses_cpu_pins_and_posix_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(support.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(support.platform, "machine", lambda: "arm64")
    monkeypatch.setenv("DRUG_AGENT_TOOLS_HOME", str(tmp_path / "Tools with spaces"))
    monkeypatch.setattr(tool_install, "_managed_micromamba", lambda _: tmp_path / "micromamba")
    monkeypatch.setattr(tool_install, "_download", lambda url, destination, **kwargs: destination.write_bytes(b"wheel"))
    monkeypatch.setattr(tool_install, "_sha256", lambda _: tool_install.BOLTZ_WHEEL_SHA256)
    environment, python, launcher = tool_install._boltz_environment_paths()
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        python.parent.mkdir(parents=True, exist_ok=True)
        python.touch()
        launcher.write_text("#!/bin/sh\nexit 0\n")
        output = tool_install.BOLTZ_VERSION if "-c" in command and "metadata" in command[-1] else tool_install.TORCH_VERSION
        return SimpleNamespace(returncode=0, stdout=output, stderr="")
    monkeypatch.setattr(tool_install.subprocess, "run", run)
    tool_install.install_boltz(lambda _: None)
    assert python == environment / "bin/python"
    assert any("torch==2.7.1" in command for command in commands)
    assert not any("--index-url" in command or any("[cuda]" in part for part in command) for command in commands)
    metadata = json.loads((support.tools_home() / "boltz/installation.json").read_text())
    assert metadata["cpu_verified"] is True and not metadata["gpu_enabled"]
    assert list((support.tools_home() / "setup-commands").glob("*.json"))


@pytest.mark.parametrize("system", ["Darwin", "Linux"])
def test_cpu_commands_disable_cuda_kernels_without_changing_science(system, monkeypatch):
    monkeypatch.setattr(support.platform, "system", lambda: system)
    config = BoltzConfig(accelerator="cpu")
    command = build_boltz_command("input with spaces.yaml", "output with spaces", config)
    assert "--no_kernels" in command
    assert command[command.index("--accelerator") + 1] == "cpu"
    assert command[command.index("--sampling_steps") + 1] == str(config.sampling_steps)
