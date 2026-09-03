from __future__ import annotations

from pathlib import Path

from .geometry import bounds_for_points, protein_residue_atoms, weighted_center
from .models import PocketBounds, ResidueScore, Vector3


def build_box(
    residues: list[ResidueScore],
    receptor: str | Path,
    *,
    padding_angstrom: float,
    minimum_size: Vector3,
    maximum_size: Vector3,
) -> tuple[Vector3, Vector3, PocketBounds, PocketBounds]:
    """Use a score-weighted center and per-axis heavy-atom extent plus padding."""
    if padding_angstrom < 0 or any(low <= 0 or high < low for low, high in zip(minimum_size, maximum_size, strict=True)):
        raise ValueError("invalid pocket box limits")
    center = weighted_center(residues)
    grouped = protein_residue_atoms(receptor)
    atoms = [
        atom for item in residues for atom in grouped[item.residue.key]
        if atom.element.upper() not in {"H", "D"}
    ]
    atom_bounds = bounds_for_points((atom.x, atom.y, atom.z) for atom in atoms)
    required = tuple(
        2 * max(center[axis] - atom_bounds.minimum[axis], atom_bounds.maximum[axis] - center[axis])
        + 2 * padding_angstrom
        for axis in range(3)
    )
    size = tuple(
        min(maximum_size[axis], max(minimum_size[axis], required[axis]))
        for axis in range(3)
    )
    bounds = PocketBounds(
        minimum=tuple(center[axis] - size[axis] / 2 for axis in range(3)),
        maximum=tuple(center[axis] + size[axis] / 2 for axis in range(3)),
    )
    return center, size, bounds, atom_bounds
