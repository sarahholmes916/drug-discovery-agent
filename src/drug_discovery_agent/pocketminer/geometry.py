from __future__ import annotations

from collections import defaultdict
from math import dist, sqrt
from pathlib import Path
from typing import Iterable

from drug_discovery_agent.receptor.structure import StructureAtom, parse_structure

from .models import PocketBounds, ResidueIdentity, ResidueScore, Vector3


BACKBONE = {"N", "CA", "C", "O", "OXT"}


def protein_residue_atoms(path: str | Path) -> dict[tuple[str, int, str, str], list[StructureAtom]]:
    grouped: dict[tuple[str, int, str, str], list[StructureAtom]] = defaultdict(list)
    for atom in parse_structure(path):
        if atom.record == "ATOM":
            grouped[(atom.chain, atom.residue_number, atom.insertion_code, atom.residue_name)].append(atom)
    if not grouped:
        raise ValueError("receptor contains no protein ATOM residues")
    return dict(grouped)


def centroid(atoms: Iterable[StructureAtom]) -> Vector3:
    values = list(atoms)
    if not values:
        raise ValueError("cannot compute a centroid from no atoms")
    count = len(values)
    return (
        sum(atom.x for atom in values) / count,
        sum(atom.y for atom in values) / count,
        sum(atom.z for atom in values) / count,
    )


def residue_representative(atoms: list[StructureAtom]) -> tuple[Vector3, str]:
    heavy = [atom for atom in atoms if atom.element.upper() not in {"H", "D"}]
    sidechain = [atom for atom in heavy if atom.atom_name.upper() not in BACKBONE]
    if sidechain:
        return centroid(sidechain), "sidechain_heavy_centroid"
    if heavy:
        # Glycine and incomplete residues deliberately use their heavy-atom centroid.
        return centroid(heavy), "heavy_atom_centroid"
    ca = next((atom for atom in atoms if atom.atom_name.upper() == "CA"), None)
    if ca:
        return (ca.x, ca.y, ca.z), "ca"
    raise ValueError("residue has no usable representative atom")


def attach_representatives(scores: list[ResidueScore], receptor: str | Path) -> list[ResidueScore]:
    atoms_by_residue = protein_residue_atoms(receptor)
    result = []
    for item in scores:
        atoms = atoms_by_residue.get(item.residue.key)
        if not atoms:
            raise ValueError(f"PocketMiner residue is absent from receptor: {item.residue.key}")
        coordinate, method = residue_representative(atoms)
        result.append(item.model_copy(update={
            "representative_coordinate": coordinate,
            "representative_method": method,
        }))
    return result


def bounds_for_points(points: Iterable[Vector3]) -> PocketBounds:
    values = list(points)
    if not values:
        raise ValueError("cannot calculate bounds from no points")
    return PocketBounds(
        minimum=tuple(min(point[axis] for point in values) for axis in range(3)),
        maximum=tuple(max(point[axis] for point in values) for axis in range(3)),
    )


def extent(bounds: PocketBounds) -> Vector3:
    return tuple(bounds.maximum[axis] - bounds.minimum[axis] for axis in range(3))


def weighted_center(residues: list[ResidueScore]) -> Vector3:
    if any(item.representative_coordinate is None for item in residues):
        raise ValueError("all pocket residues need representative coordinates")
    weights = [item.active_score for item in residues]
    total = sum(weights)
    if total <= 0:
        weights = [1.0] * len(residues)
        total = float(len(residues))
    return tuple(
        sum(item.representative_coordinate[axis] * weight for item, weight in zip(residues, weights, strict=True)) / total  # type: ignore[index]
        for axis in range(3)
    )


def rms_distance(points: Iterable[Vector3], center: Vector3) -> float:
    values = list(points)
    return sqrt(sum(dist(point, center) ** 2 for point in values) / len(values))


def residues_inside_box(
    receptor: str | Path,
    *,
    center: Vector3,
    size: Vector3,
    scores: dict[tuple[str, int, str, str], ResidueScore] | None = None,
) -> list[ResidueScore]:
    grouped = protein_residue_atoms(receptor)
    half = tuple(value / 2 for value in size)
    selected = []
    for key, atoms in grouped.items():
        heavy = [atom for atom in atoms if atom.element.upper() not in {"H", "D"}]
        if not any(all(abs((atom.x, atom.y, atom.z)[axis] - center[axis]) <= half[axis] for axis in range(3)) for atom in heavy):
            continue
        existing = (scores or {}).get(key)
        coordinate, method = residue_representative(atoms)
        selected.append(existing or ResidueScore(
            residue=ResidueIdentity(chain=key[0], residue_number=key[1], insertion_code=key[2], residue_name=key[3]),
            score=0.0,
            representative_coordinate=coordinate,
            representative_method=method,
        ))
    return selected
