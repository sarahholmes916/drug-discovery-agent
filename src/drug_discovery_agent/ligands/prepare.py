from __future__ import annotations

import shutil
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from drug_discovery_agent.execution.commands import CancellationToken, CommandExecutor, CommandResult
from drug_discovery_agent.project.manifest import ModificationRecord


class PreparedLigand(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    ligand_id: str
    status: str
    prepared_sdf: Path | None = None
    prepared_pdbqt: Path | None = None
    explicit_hydrogen_count: int = 0
    used_existing_3d: bool = False
    modifications: list[ModificationRecord] = Field(default_factory=list)
    command: CommandResult | None = None
    error: str | None = None


def _rdkit() -> tuple[object, object]:
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError as exc:
        raise RuntimeError("RDKit is required for ligand preparation") from exc
    return Chem, AllChem


def prepare_rdkit_sdf(
    input_sdf: str | Path,
    output_sdf: str | Path,
    *,
    random_seed: int = 42,
) -> tuple[int, bool, list[ModificationRecord]]:
    Chem, AllChem = _rdkit()
    supplier = Chem.SDMolSupplier(str(input_sdf), removeHs=False)
    molecule = next((item for item in supplier if item is not None), None)
    if molecule is None:
        raise ValueError(f"RDKit could not read {input_sdf}")

    initial_h = sum(atom.GetAtomicNum() == 1 for atom in molecule.GetAtoms())
    molecule = Chem.AddHs(molecule, addCoords=True)
    final_h = sum(atom.GetAtomicNum() == 1 for atom in molecule.GetAtoms())
    modifications: list[ModificationRecord] = []
    if final_h > initial_h:
        modifications.append(
            ModificationRecord(
                kind="explicit_hydrogens",
                description=f"RDKit represented {final_h - initial_h} implicit hydrogens explicitly",
                changes_scientific_identity=False,
                before=str(initial_h),
                after=str(final_h),
            )
        )

    existing_3d = False
    if molecule.GetNumConformers() > 0:
        try:
            existing_3d = bool(molecule.GetConformer().Is3D())
        except Exception:
            existing_3d = False
    if not existing_3d:
        result = AllChem.EmbedMolecule(molecule, randomSeed=random_seed)
        if result != 0:
            raise ValueError(f"3D embedding failed for {Path(input_sdf).name}")
        modifications.append(
            ModificationRecord(
                kind="conformer_generation",
                description=f"RDKit generated a 3D conformer with random seed {random_seed}",
                changes_scientific_identity=False,
            )
        )
        try:
            optimization_status = AllChem.UFFOptimizeMolecule(molecule)
            modifications.append(
                ModificationRecord(
                    kind="geometry_optimization",
                    description=f"RDKit UFF optimization returned status {optimization_status}",
                    changes_scientific_identity=False,
                )
            )
        except Exception as exc:
            modifications.append(
                ModificationRecord(
                    kind="geometry_optimization_failed",
                    description=f"UFF optimization was attempted but failed: {exc}",
                    changes_scientific_identity=False,
                )
            )

    output = Path(output_sdf)
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = Chem.SDWriter(str(output))
    try:
        writer.write(molecule)
    finally:
        writer.close()
    verification = Chem.SDMolSupplier(str(output), removeHs=False)
    verified = next((item for item in verification if item is not None), None)
    verified_h = sum(atom.GetAtomicNum() == 1 for atom in verified.GetAtoms()) if verified is not None else 0
    if verified is None or verified_h == 0:
        raise ValueError(f"no explicit H atoms found after processing {Path(input_sdf).name}")
    return verified_h, existing_3d, modifications


def _meeko_command(input_sdf: Path, output_pdbqt: Path) -> list[str]:
    arguments = ["-i", str(input_sdf), "-o", str(output_pdbqt)]
    if getattr(sys, "frozen", False):
        return [sys.executable, "--internal-prepare-ligand", *arguments]
    executable = shutil.which("mk_prepare_ligand.py") or shutil.which("mk_prepare_ligand")
    if executable:
        return [executable, *arguments]
    return [sys.executable, "-m", "meeko.cli.mk_prepare_ligand", *arguments]


def prepare_ligand(
    ligand_id: str,
    input_sdf: str | Path,
    output_sdf: str | Path,
    output_pdbqt: str | Path,
    *,
    executor: CommandExecutor | None = None,
    cancellation: CancellationToken | None = None,
    random_seed: int = 42,
    timeout_seconds: float | None = None,
) -> PreparedLigand:
    executor = executor or CommandExecutor()
    command = None
    modifications: list[ModificationRecord] = []
    try:
        hydrogen_count, existing_3d, modifications = prepare_rdkit_sdf(
            input_sdf, output_sdf, random_seed=random_seed
        )
        pdbqt = Path(output_pdbqt)
        pdbqt.parent.mkdir(parents=True, exist_ok=True)
        command = executor.run(
            _meeko_command(Path(output_sdf), pdbqt),
            working_directory=pdbqt.parent,
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
        )
        if not command.successful or not pdbqt.is_file() or pdbqt.stat().st_size == 0:
            raise RuntimeError(
                f"Meeko ligand preparation failed with exit code {command.return_code}: "
                f"{command.stderr.strip()}"
            )
        return PreparedLigand(
            ligand_id=ligand_id,
            status="SUCCESS",
            prepared_sdf=Path(output_sdf),
            prepared_pdbqt=pdbqt,
            explicit_hydrogen_count=hydrogen_count,
            used_existing_3d=existing_3d,
            modifications=modifications,
            command=command,
        )
    except Exception as exc:
        return PreparedLigand(
            ligand_id=ligand_id,
            status="FAILED",
            prepared_sdf=Path(output_sdf) if Path(output_sdf).exists() else None,
            prepared_pdbqt=Path(output_pdbqt) if Path(output_pdbqt).exists() else None,
            modifications=modifications,
            command=command,
            error=str(exc),
        )
