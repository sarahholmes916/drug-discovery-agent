from __future__ import annotations

from pathlib import Path
from typing import Sequence

from drug_discovery_agent.execution.commands import CancellationToken, CommandExecutor

from .models import VinaResult
from .parsing import parse_vina_stdout


def build_vina_command(
    *,
    receptor_pdbqt: str | Path,
    ligand_pdbqt: str | Path,
    output_pdbqt: str | Path,
    center: Sequence[float],
    size: Sequence[float],
    exhaustiveness: int,
    num_modes: int,
    seed: int | None = None,
) -> list[str]:
    if len(center) != 3 or len(size) != 3:
        raise ValueError("Vina center and size must each contain three values")
    if any(float(value) <= 0 for value in size):
        raise ValueError("Vina box dimensions must be positive")
    command = [
        "vina",
        "--receptor", str(receptor_pdbqt),
        "--ligand", str(ligand_pdbqt),
        "--center_x", str(center[0]),
        "--center_y", str(center[1]),
        "--center_z", str(center[2]),
        "--size_x", str(size[0]),
        "--size_y", str(size[1]),
        "--size_z", str(size[2]),
        "--exhaustiveness", str(exhaustiveness),
        "--num_modes", str(num_modes),
        "--out", str(output_pdbqt),
    ]
    if seed is not None:
        command.extend(["--seed", str(seed)])
    return command


def run_vina(
    ligand_id: str,
    *,
    receptor_pdbqt: str | Path,
    ligand_pdbqt: str | Path,
    output_pdbqt: str | Path,
    center: Sequence[float],
    size: Sequence[float],
    exhaustiveness: int,
    num_modes: int,
    seed: int | None = None,
    executor: CommandExecutor | None = None,
    cancellation: CancellationToken | None = None,
    timeout_seconds: float | None = None,
) -> VinaResult:
    output = Path(output_pdbqt)
    output.parent.mkdir(parents=True, exist_ok=True)
    executor = executor or CommandExecutor()
    command = build_vina_command(
        receptor_pdbqt=receptor_pdbqt,
        ligand_pdbqt=ligand_pdbqt,
        output_pdbqt=output,
        center=center,
        size=size,
        exhaustiveness=exhaustiveness,
        num_modes=num_modes,
        seed=seed,
    )
    result = executor.run(
        command,
        working_directory=output.parent,
        timeout_seconds=timeout_seconds,
        cancellation=cancellation,
    )
    if not result.successful or not output.is_file() or output.stat().st_size == 0:
        return VinaResult(
            ligand_id=ligand_id,
            status="FAILED",
            output_pdbqt=output if output.exists() else None,
            command=result,
            error=f"Vina failed with exit code {result.return_code}: {result.stderr.strip()}",
        )
    best, actual_seed, modes = parse_vina_stdout(result.stdout)
    if not modes:
        return VinaResult(
            ligand_id=ligand_id,
            status="NEEDS_REVIEW",
            output_pdbqt=output,
            command=result,
            error="Vina completed but no score rows were parsed",
        )
    return VinaResult(
        ligand_id=ligand_id,
        status="SUCCESS",
        output_pdbqt=output,
        best_affinity_kcal_mol=best,
        seed=actual_seed,
        modes=modes,
        command=result,
    )

