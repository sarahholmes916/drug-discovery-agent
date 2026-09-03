from __future__ import annotations

import numpy as np

from drug_discovery_agent.comparison.alignment import compare_poses, kabsch_alignment


def test_protein_alignment_precedes_ligand_rmsd() -> None:
    reference = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 2]], dtype=float)
    translation = np.array([4, -3, 2], dtype=float)
    mobile = reference + translation
    alignment = kabsch_alignment(reference, mobile)
    assert alignment.comparable
    assert alignment.protein_rmsd_angstrom == pytest.approx(0.0, abs=1e-10)


def test_no_atom_correspondence_returns_not_comparable() -> None:
    protein = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    result = compare_poses(reference_protein=protein, comparison_protein=protein,
                           reference_ligand=[[0, 0, 0]], comparison_ligand=[[0, 0, 0]],
                           atom_correspondence=None)
    assert result.status == "not_comparable"
    assert result.ligand_rmsd_angstrom is None


import pytest

