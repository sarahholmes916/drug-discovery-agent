from __future__ import annotations

import pytest

from drug_discovery_agent.config.models import ReceptorPreparationConfig
from drug_discovery_agent.receptor.preparation import prepare_receptor_structure


PDB = """\
ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 20.00           C  
HETATM    2  O   HOH A 101       2.000   3.000   4.000  1.00 20.00           O  
HETATM    3 ZN    ZN A 201       3.000   4.000   5.000  1.00 20.00          ZN  
END
"""


def test_recommended_selection_stops_for_non_water_heterogens(tmp_path) -> None:
    source, output = tmp_path / "source.pdb", tmp_path / "selected.pdb"
    source.write_text(PDB, encoding="utf-8")
    with pytest.raises(ValueError, match="heterogens"):
        prepare_receptor_structure(
            source,
            output,
            protein_chain="A",
            settings=ReceptorPreparationConfig(method="meeko"),
        )


def test_explicit_remove_policy_removes_water_and_heterogens(tmp_path) -> None:
    source, output = tmp_path / "source.pdb", tmp_path / "selected.pdb"
    source.write_text(PDB, encoding="utf-8")
    prepare_receptor_structure(
        source,
        output,
        protein_chain="A",
        settings=ReceptorPreparationConfig(method="meeko", heterogens="remove"),
    )
    text = output.read_text(encoding="utf-8")
    assert "ALA" in text
    assert "HOH" not in text
    assert " ZN " not in text
