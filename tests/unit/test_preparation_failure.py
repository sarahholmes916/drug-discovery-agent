from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from drug_discovery_agent.execution.commands import CommandResult
from drug_discovery_agent.ligands import prepare as module


class FailingExecutor:
    def run(self, command, **kwargs):
        now = datetime.now(UTC)
        return CommandResult(command=list(command), working_directory=str(kwargs["working_directory"]),
                             return_code=2, stdout="", stderr="bad ligand", start_time=now,
                             end_time=now, duration_seconds=0.0)


def test_meeko_failure_is_retained(monkeypatch, tmp_path: Path) -> None:
    prepared = tmp_path / "prepared.sdf"

    def fake_rdkit(input_sdf, output_sdf, random_seed=42):
        Path(output_sdf).write_text("prepared", encoding="utf-8")
        return 4, False, []

    monkeypatch.setattr(module, "prepare_rdkit_sdf", fake_rdkit)
    result = module.prepare_ligand("lig_1", tmp_path / "source.sdf", prepared,
                                   tmp_path / "ligand.pdbqt", executor=FailingExecutor())
    assert result.status == "FAILED"
    assert "exit code 2" in result.error
    assert "bad ligand" in result.error


def test_frozen_companion_routes_ligand_preparation_through_itself(monkeypatch, tmp_path) -> None:
    companion = tmp_path / "DrugDiscoveryAgent-Companion.exe"
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(module.sys, "executable", str(companion))

    command = module._meeko_command(tmp_path / "prepared.sdf", tmp_path / "prepared.pdbqt")

    assert command == [
        str(companion),
        "--internal-prepare-ligand",
        "-i",
        str(tmp_path / "prepared.sdf"),
        "-o",
        str(tmp_path / "prepared.pdbqt"),
    ]


def test_source_install_falls_back_to_meeko_python_module(monkeypatch, tmp_path) -> None:
    monkeypatch.delattr(module.sys, "frozen", raising=False)
    monkeypatch.setattr(module.shutil, "which", lambda command: None)

    command = module._meeko_command(tmp_path / "prepared.sdf", tmp_path / "prepared.pdbqt")

    assert command[:3] == [module.sys.executable, "-m", "meeko.cli.mk_prepare_ligand"]
