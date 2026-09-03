from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from drug_discovery_agent.config.models import ReceptorPreparationConfig
from drug_discovery_agent.execution.commands import CommandExecutor, CommandResult
from drug_discovery_agent.receptor.structure import StructureAtom, parse_structure


_WATER_RESIDUES = {"HOH", "WAT", "H2O", "DOD"}


@dataclass(frozen=True, slots=True)
class PreparedReceptor:
    source: Path
    selected_structure: Path
    pdbqt: Path
    command: CommandResult


def _residue_labels(atoms: list[StructureAtom], limit: int = 8) -> str:
    labels: list[str] = []
    for atom in atoms:
        label = f"{atom.chain}:{atom.residue_name}{atom.residue_number}"
        if label not in labels:
            labels.append(label)
        if len(labels) == limit:
            break
    return ", ".join(labels)


def _write_selected_pdb(atoms: list[StructureAtom], output: Path) -> None:
    lines = []
    for atom in atoms:
        chain = atom.chain if len(atom.chain) == 1 else "A"
        atom_name = atom.atom_name[:4]
        lines.append(
            f"{atom.record:<6}{atom.serial:>5} {atom_name:^4}{atom.alternate_location[:1]:1}"
            f"{atom.residue_name[:3]:>3} {chain:1}{atom.residue_number:>4}{atom.insertion_code[:1]:1}   "
            f"{atom.x:>8.3f}{atom.y:>8.3f}{atom.z:>8.3f}{atom.occupancy:>6.2f}{0.0:>6.2f}"
            f"          {atom.element[:2]:>2}"
        )
    lines.extend(["TER", "END"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare_receptor_structure(
    source: str | Path,
    selected_output: str | Path,
    *,
    protein_chain: str,
    settings: ReceptorPreparationConfig,
) -> Path:
    """Apply only user-approved structural selection before Meeko parameterization."""
    source_path = Path(source)
    if len(protein_chain) != 1:
        raise ValueError(
            "automatic Vina receptor preparation currently requires a one-character chain ID; "
            "upload a curated PDBQT for multi-character mmCIF chain IDs"
        )
    atoms = [atom for atom in parse_structure(source_path) if atom.chain == protein_chain]
    if not atoms:
        raise ValueError(f"no receptor atoms remained for protein chain {protein_chain!r}")

    if settings.remove_waters:
        atoms = [atom for atom in atoms if atom.residue_name.upper() not in _WATER_RESIDUES]
    heterogens = [
        atom for atom in atoms
        if atom.record == "HETATM" and atom.residue_name.upper() not in _WATER_RESIDUES
    ]
    if settings.heterogens == "review":
        if heterogens:
            raise ValueError(
                "receptor preparation needs review because non-water heterogens were found "
                f"({_residue_labels(heterogens)}). Choose whether to keep or remove them."
            )
    elif settings.heterogens == "remove":
        atoms = [atom for atom in atoms if atom not in heterogens]

    alternate_locations = {atom.alternate_location for atom in atoms if atom.alternate_location}
    if settings.alternate_locations == "review":
        if alternate_locations:
            raise ValueError(
                "receptor preparation needs review because alternate atom locations were found "
                f"({', '.join(sorted(alternate_locations))}). Choose conformer A or upload a curated PDBQT."
            )
    else:
        atoms = [atom for atom in atoms if atom.alternate_location in {"", "A"}]
        atoms = [replace(atom, alternate_location="") for atom in atoms]
    if not atoms:
        raise ValueError("no receptor atoms remained after applying preparation settings")
    output = Path(selected_output)
    _write_selected_pdb(atoms, output)
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("receptor selection did not produce a PDB file")
    return output


def _meeko_command(input_pdb: Path, output_pdbqt: Path) -> list[str]:
    arguments = ["--read_pdb", str(input_pdb), "--write_pdbqt", str(output_pdbqt)]
    if getattr(sys, "frozen", False):
        return [sys.executable, "--internal-prepare-receptor", *arguments]
    executable = shutil.which("mk_prepare_receptor.py")
    if executable:
        return [executable, *arguments]
    return [sys.executable, "-m", "meeko.cli.mk_prepare_receptor", *arguments]


def prepare_receptor_pdbqt(
    source: str | Path,
    selected_output: str | Path,
    pdbqt_output: str | Path,
    *,
    protein_chain: str,
    settings: ReceptorPreparationConfig,
    executor: CommandExecutor | None = None,
) -> PreparedReceptor:
    if settings.method != "meeko":
        raise ValueError("automatic preparation requires the Meeko preparation method")
    selected = prepare_receptor_structure(
        source,
        selected_output,
        protein_chain=protein_chain,
        settings=settings,
    )
    pdbqt = Path(pdbqt_output)
    pdbqt.parent.mkdir(parents=True, exist_ok=True)
    command = (executor or CommandExecutor()).run(
        _meeko_command(selected, pdbqt),
        working_directory=pdbqt.parent,
    )
    if not command.successful or not pdbqt.is_file() or pdbqt.stat().st_size == 0:
        detail = command.stderr.strip() or command.stdout.strip() or "no PDBQT was written"
        raise RuntimeError(f"Meeko receptor preparation failed: {detail}")
    return PreparedReceptor(Path(source), selected, pdbqt, command)
