from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class ComparisonModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AlignmentResult(ComparisonModel):
    comparable: bool
    reason: str | None = None
    atom_count: int = 0
    protein_rmsd_angstrom: float | None = None
    rotation: list[list[float]] | None = None
    translation: list[float] | None = None


class ComparisonResult(ComparisonModel):
    status: str
    reason: str | None = None
    alignment: AlignmentResult
    ligand_rmsd_angstrom: float | None = None
    contact_jaccard: float | None = None
    interaction_type_jaccard: float | None = None
    pocket_occupancy_consistent: bool | None = None
    shared_contacts: list[str] = Field(default_factory=list)


def kabsch_alignment(reference: Sequence[Sequence[float]], mobile: Sequence[Sequence[float]]) -> AlignmentResult:
    fixed, moving = np.asarray(reference, dtype=float), np.asarray(mobile, dtype=float)
    if fixed.shape != moving.shape or fixed.ndim != 2 or fixed.shape[1] != 3:
        return AlignmentResult(comparable=False, reason=f"protein coordinate shape mismatch: {fixed.shape} vs {moving.shape}")
    if len(fixed) < 3:
        return AlignmentResult(comparable=False, reason="at least three corresponding protein atoms are required")
    fixed_center, moving_center = fixed.mean(axis=0), moving.mean(axis=0)
    covariance = (moving - moving_center).T @ (fixed - fixed_center)
    first, _, second = np.linalg.svd(covariance)
    correction = np.eye(3)
    correction[-1, -1] = np.sign(np.linalg.det(first @ second))
    rotation = first @ correction @ second
    translation = fixed_center - moving_center @ rotation
    aligned = moving @ rotation + translation
    rmsd = float(np.sqrt(np.mean(np.sum((fixed - aligned) ** 2, axis=1))))
    return AlignmentResult(comparable=True, atom_count=len(fixed), protein_rmsd_angstrom=rmsd,
                           rotation=rotation.tolist(), translation=translation.tolist())


def _jaccard(first: set[str], second: set[str]) -> float | None:
    union = first | second
    return len(first & second) / len(union) if union else None


def compare_poses(
    *,
    reference_protein: Sequence[Sequence[float]],
    comparison_protein: Sequence[Sequence[float]],
    reference_ligand: Sequence[Sequence[float]],
    comparison_ligand: Sequence[Sequence[float]],
    atom_correspondence: Iterable[tuple[int, int]] | None,
    reference_contacts: Iterable[str] = (),
    comparison_contacts: Iterable[str] = (),
    reference_interaction_types: Iterable[str] = (),
    comparison_interaction_types: Iterable[str] = (),
    reference_pocket_center: Sequence[float] | None = None,
    pocket_radius: float | None = None,
) -> ComparisonResult:
    alignment = kabsch_alignment(reference_protein, comparison_protein)
    if not alignment.comparable:
        return ComparisonResult(status="not_comparable", reason=alignment.reason, alignment=alignment)
    correspondence = list(atom_correspondence or [])
    if not correspondence:
        return ComparisonResult(status="not_comparable", reason="ligand atom correspondence is unavailable", alignment=alignment)
    fixed_ligand, moving_ligand = np.asarray(reference_ligand, dtype=float), np.asarray(comparison_ligand, dtype=float)
    try:
        fixed_indices = np.asarray([first for first, _ in correspondence], dtype=int)
        moving_indices = np.asarray([second for _, second in correspondence], dtype=int)
        if len(set(fixed_indices)) != len(fixed_indices) or len(set(moving_indices)) != len(moving_indices):
            raise ValueError("ligand atom correspondence is not one-to-one")
        rotation, translation = np.asarray(alignment.rotation), np.asarray(alignment.translation)
        transformed = moving_ligand @ rotation + translation
        delta = fixed_ligand[fixed_indices] - transformed[moving_indices]
    except (IndexError, ValueError) as exc:
        return ComparisonResult(status="not_comparable", reason=str(exc), alignment=alignment)
    rmsd = float(np.sqrt(np.mean(np.sum(delta ** 2, axis=1))))
    first_contacts, second_contacts = set(reference_contacts), set(comparison_contacts)
    first_types, second_types = set(reference_interaction_types), set(comparison_interaction_types)
    occupancy = None
    if reference_pocket_center is not None and pocket_radius is not None:
        if pocket_radius <= 0:
            raise ValueError("pocket radius must be positive")
        center = np.asarray(reference_pocket_center, dtype=float)
        occupancy = bool(np.linalg.norm(fixed_ligand.mean(axis=0) - center) <= pocket_radius
                         and np.linalg.norm(transformed.mean(axis=0) - center) <= pocket_radius)
    return ComparisonResult(
        status="comparable", alignment=alignment, ligand_rmsd_angstrom=rmsd,
        contact_jaccard=_jaccard(first_contacts, second_contacts),
        interaction_type_jaccard=_jaccard(first_types, second_types),
        pocket_occupancy_consistent=occupancy,
        shared_contacts=sorted(first_contacts & second_contacts),
    )

