from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from drug_discovery_agent.config.models import PocketResidue

from .structure import parse_structure


@dataclass(frozen=True, slots=True)
class PocketSelection:
    residue: PocketResidue
    minimum_distance_to_center_angstrom: float
    heavy_atoms_inside_vina_box: int


def select_pocket_residues(
    receptor_path: str | Path,
    *,
    center: Sequence[float],
    size: Sequence[float],
    search_radius: float,
    maximum_residues: int,
) -> list[PocketSelection]:
    if len(center) != 3 or len(size) != 3:
        raise ValueError("center and size must contain three values")
    if search_radius <= 0 or maximum_residues < 1 or any(float(value) <= 0 for value in size):
        raise ValueError("pocket selection radius, dimensions, and maximum must be positive")
    center_array, half_size = np.asarray(center, dtype=float), np.asarray(size, dtype=float) / 2.0
    residues: dict[tuple[str, int, str, str], list[object]] = {}
    for atom in parse_structure(receptor_path):
        if atom.record == "ATOM":
            residues.setdefault((atom.chain, atom.residue_number, atom.insertion_code, atom.residue_name), []).append(atom)
    candidates = []
    for (chain, number, insertion, name), atoms in residues.items():
        heavy = [atom for atom in atoms if atom.element.upper() != "H"]
        coordinates = np.asarray([(atom.x, atom.y, atom.z) for atom in heavy], dtype=float)
        minimum = float(np.linalg.norm(coordinates - center_array, axis=1).min())
        inside = int(np.all(np.abs(coordinates - center_array) <= half_size, axis=1).sum())
        if minimum <= search_radius:
            candidates.append(
                PocketSelection(PocketResidue(chain=chain, residue_number=number, insertion_code=insertion,
                                              residue_name=name), minimum, inside)
            )
    nearest = sorted(candidates, key=lambda item: (item.minimum_distance_to_center_angstrom,
                                                   item.residue.chain, item.residue.residue_number))[:maximum_residues]
    return sorted(nearest, key=lambda item: (item.residue.chain, item.residue.residue_number,
                                             item.residue.insertion_code))
