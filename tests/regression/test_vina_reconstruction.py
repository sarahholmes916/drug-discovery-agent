from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from drug_discovery_agent.vina.poses import mode1_pose
from drug_discovery_agent.vina.reconstruction import reconstruct_ligand


pytestmark = pytest.mark.skipif(importlib.util.find_spec("rdkit") is None, reason="RDKit is optional")
FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_source_graph_and_vina_coordinate_reconstruction() -> None:
    pose = mode1_pose(FIXTURES / "vina" / "structures_12233_out.pdbqt", "structures_12233")
    ligand = reconstruct_ligand(FIXTURES / "ligands" / "structures_12233.sdf", pose)
    assert ligand.mol.GetNumHeavyAtoms() == 45
    assert ligand.bonds_over_2_2 == 0
    assert ligand.max_bond_length < 2.2

