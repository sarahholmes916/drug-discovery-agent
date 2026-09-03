from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .poses import PDBQTAtom, VinaPose, parse_pdbqt_atom


@dataclass(slots=True)
class ProteinModel:
    atoms: list[PDBQTAtom]
    by_residue: dict[tuple[str, int, str], list[PDBQTAtom]]


@dataclass(frozen=True, slots=True)
class ResidueDistance:
    chain: str
    residue_number: int
    residue_name: str
    minimum_distance: float
    contact: bool


def parse_receptor_pdbqt(path: str | Path) -> ProteinModel:
    atoms = [
        parse_pdbqt_atom(line)
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith(("ATOM", "HETATM"))
    ]
    by_residue: dict[tuple[str, int, str], list[PDBQTAtom]] = {}
    for atom in atoms:
        by_residue.setdefault((atom.chain, atom.resid, atom.resname), []).append(atom)
    return ProteinModel(atoms, by_residue)


def residue_distances(
    pose: VinaPose,
    receptor: ProteinModel,
    *,
    contact_cutoff: float = 4.0,
) -> list[ResidueDistance]:
    if contact_cutoff <= 0:
        raise ValueError("contact cutoff must be positive")
    ligand = np.asarray([atom.coord for atom in pose.heavy_atoms], dtype=float)
    if ligand.size == 0:
        raise ValueError("Vina pose contains no heavy atoms")
    rows: list[ResidueDistance] = []
    for (chain, residue_number, residue_name), atoms in sorted(
        receptor.by_residue.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])
    ):
        protein = np.asarray([atom.coord for atom in atoms if atom.element != "H"], dtype=float)
        if protein.size == 0:
            continue
        distance = float(np.sqrt(np.square(protein[:, None, :] - ligand[None, :, :]).sum(axis=2).min()))
        rows.append(
            ResidueDistance(chain, residue_number, residue_name, distance, distance < contact_cutoff)
        )
    return rows

