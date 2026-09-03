from __future__ import annotations

from pathlib import Path

from drug_discovery_agent.vina.parsing import parse_vina_stdout
from drug_discovery_agent.vina.poses import parse_vina_poses


FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_parse_vina_stdout_modes_rmsd_and_seed() -> None:
    stdout = """
    random seed: 1953981247
-----+------------+----------+----------
   1       -8.108      0.000      0.000
   2       -8.107      5.611     10.063
   3       -7.922      4.094      6.156
"""
    best, seed, modes = parse_vina_stdout(stdout)
    assert best == -8.108
    assert seed == 1953981247
    assert [(item.mode, item.rmsd_lb, item.rmsd_ub) for item in modes] == [
        (1, 0.0, 0.0), (2, 5.611, 10.063), (3, 4.094, 6.156),
    ]


def test_parse_saved_multimodel_vina_pdbqt() -> None:
    poses = parse_vina_poses(FIXTURES / "vina" / "structures_12233_out.pdbqt")
    assert [pose.mode for pose in poses] == [1, 2, 3]
    assert [pose.affinity for pose in poses] == [-8.108, -8.107, -7.922]
    assert all(len(pose.heavy_atoms) == 45 for pose in poses)
    assert poses[0].smiles_to_pdbqt[8] == 1
    assert poses[0].h_parent[1] == [14, 15]

