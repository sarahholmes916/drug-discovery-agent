from __future__ import annotations

from pathlib import Path

import pytest

from drug_discovery_agent.boltz.inputs import (
    build_constrained_input, build_unconstrained_input, load_boltz_input,
    validate_constrained_input, validate_unconstrained_input,
)
from drug_discovery_agent.receptor.mapping import ResidueMapping


FIXTURES = Path(__file__).parents[1] / "fixtures" / "boltz"


def _sequences(document: dict) -> tuple[str, str]:
    return document["sequences"][0]["protein"]["sequence"], document["sequences"][1]["ligand"]["smiles"]


def test_historical_unconstrained_input_has_no_pocket() -> None:
    historical = load_boltz_input(FIXTURES / "unconstrained" / "ns1_structures_12233" / "input_original.yaml")
    validate_unconstrained_input(historical)
    assert "constraints" not in historical


def test_generated_unconstrained_input_remains_distinct() -> None:
    historical = load_boltz_input(FIXTURES / "unconstrained" / "ns1_structures_12233" / "input_original.yaml")
    protein, smiles = _sequences(historical)
    generated = build_unconstrained_input(
        protein_sequence=protein, ligand_smiles=smiles,
        receptor_template=historical["templates"][0]["pdb"], template_chain="A",
    )
    validate_unconstrained_input(generated)
    assert "constraints" not in generated
    assert generated["properties"] == historical["properties"]


def test_unconstrained_validator_rejects_accidental_constraint() -> None:
    historical = load_boltz_input(FIXTURES / "unconstrained" / "ns1_structures_12233" / "input_original.yaml")
    historical["constraints"] = [{"pocket": {"binder": "L", "contacts": [["A", 6]]}}]
    with pytest.raises(ValueError, match="must not contain"):
        validate_unconstrained_input(historical)


def test_constrained_input_contains_exact_mapping_and_forces() -> None:
    historical = load_boltz_input(FIXTURES / "ns1_structures_12233.yaml")
    protein, smiles = _sequences(historical)
    positions = [6, 7, 8, 9, 10, 11, 57, 58, 59, 60, 64, 65]
    mappings = [ResidueMapping("A", 78 + position, "", "ALA", position, position, "A")
                for position in positions]
    generated = build_constrained_input(
        protein_sequence=protein, ligand_smiles=smiles,
        receptor_template=historical["templates"][0]["cif"], template_chain="A",
        mapped_pocket_residues=mappings,
    )
    validate_constrained_input(generated, expected_positions=[("A", value) for value in positions])
    pocket = generated["constraints"][0]["pocket"]
    assert pocket["contacts"] == [["A", value] for value in positions]
    assert pocket["force"] is True
    assert generated["templates"][0]["force"] is True

