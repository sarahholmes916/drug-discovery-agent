from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from drug_discovery_agent.config.models import PocketMinerRuntimeConfig
from drug_discovery_agent.pocketminer import runtime
from drug_discovery_agent.project.hashing import sha256_file


UPSTREAM_COMMIT = "187062df3c94127e991669768009141a08fd5d8b"
UPSTREAM_SHA256 = {
    "LICENSE": "3d09c75c21ed14a31d2433435fb35123544f10428b692ee7c5e86921f76fc7ec",
    "models/pocketminer.data-00000-of-00001": (
        "6f5ab62b9fb38b54040053ac321f3362d616bae9b31569249a032dbb50890b70"
    ),
    "models/pocketminer.index": (
        "09e36a62a987b14bc49cf7a1fa53fa734f85d85d088777f98c6aca253b47bf46"
    ),
    "src/gvp.py": "90c402b48c6eafdee795e943e8df5a48941f5e301b4d9585f50339e03069f458",
    "src/models.py": "cf7e2bd32e9501532732687f573a1c06e2bbe603d708d7b4e7d184c6a8493d24",
    "src/util.py": "0cadf4211e106c365f4ad6bc749b2831c21962de74509a449401149280508201",
    "src/validate_performance_on_xtals.py": (
        "7e229aa3afce836b053030240c8b8afb13e326d3acae1a898e3570dfc9a5c71c"
    ),
    "src/xtal_predict.py": (
        "8717eba2ae7d98a4dc0ac65fb363de67e869fe832c2c262c648b925feae30297"
    ),
}


def test_vendored_pocketminer_is_exact_pinned_upstream_content() -> None:
    config = PocketMinerRuntimeConfig()
    manifest = json.loads(runtime.VENDORED_MANIFEST.read_text(encoding="utf-8"))

    assert runtime.source_root(config) == runtime.VENDORED_HOME
    assert config.commit == UPSTREAM_COMMIT
    assert manifest["commit"] == UPSTREAM_COMMIT
    assert manifest["files"] == UPSTREAM_SHA256
    assert {
        relative_path: sha256_file(runtime.VENDORED_HOME / relative_path)
        for relative_path in UPSTREAM_SHA256
    } == UPSTREAM_SHA256


def test_native_windows_setup_uses_compatible_pinned_environment(
    tmp_path: Path, monkeypatch,
) -> None:
    home = tmp_path / "pocketminer"
    monkeypatch.setattr(runtime, "DEFAULT_HOME", home)
    monkeypatch.setattr(runtime.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        runtime,
        "inspect_installation",
        lambda config: {"available": True, "errors": []},
    )
    commands: list[list[object]] = []

    class FakeExecutor:
        def run(self, command, **kwargs):
            commands.append(list(command))
            if "create" in command:
                python = home / "environment" / "python.exe"
                python.parent.mkdir(parents=True)
                python.write_bytes(b"MZ")
            return SimpleNamespace(successful=True, stdout="", stderr="")

    report = runtime.setup(
        PocketMinerRuntimeConfig(),
        executor=FakeExecutor(),
        conda_executable="micromamba.exe",
    )

    assert report["available"] is True
    create = commands[0]
    assert create[:2] == ["micromamba.exe", "create"]
    assert "python=3.10" in create
    assert "mdtraj=1.9.7" in create
    assert "setuptools=60.5.0" in create
    assert "pip" in create
    assert "tensorflow=2.10" not in create
    assert commands[1] == [
        home / "environment" / "python.exe",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "tensorflow==2.10.1",
        "setuptools==60.5.0",
    ]
    assert (home / "installation.json").is_file()

    runtime.setup(
        PocketMinerRuntimeConfig(),
        executor=FakeExecutor(),
        conda_executable="micromamba.exe",
    )
    assert commands[2][:2] == ["micromamba.exe", "install"]


def test_native_mac_setup_retains_scientific_pins_and_posix_python(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "DEFAULT_HOME", tmp_path / "PocketMiner with spaces")
    monkeypatch.setattr(runtime.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(runtime, "inspect_installation", lambda _: {"available": True, "errors": []})
    commands = []
    class FakeExecutor:
        def run(self, command, **kwargs):
            commands.append(command)
            return SimpleNamespace(successful=True, stdout="", stderr="")
    config = PocketMinerRuntimeConfig()
    runtime.setup(config, executor=FakeExecutor(), conda_executable="/Tools with spaces/micromamba")
    assert "tensorflow=2.10" in commands[0]
    assert "mdtraj=1.9.7" in commands[0]
    assert "python=3.10" in commands[0]
    assert runtime.environment_python(config).as_posix().endswith("environment/bin/python")
