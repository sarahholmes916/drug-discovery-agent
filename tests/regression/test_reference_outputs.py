from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_captured_interaction_reference_is_stable() -> None:
    data = json.loads((ROOT / "legacy" / "vina_analysis" / "reference_outputs" /
                       "reference_interactions.json").read_text(encoding="utf-8"))
    assert len(data["interactions"]) == 361
    assert len(data["binding_site_residues"]) == 1130
    assert len(data["ligand_summary"]) == 38
    categories = {row["Interaction Type"] for row in data["interactions"]}
    assert categories == {"Hydrophobic interaction", "Hydrogen bond", "Salt bridge",
                          "π-stacking", "π-cation interaction", "Halogen bond"}


def test_captured_mapping_failures_and_review_are_not_lost() -> None:
    rows = json.loads((ROOT / "legacy" / "vina_analysis" / "reference_outputs" /
                       "reference_mapping_validation.json").read_text(encoding="utf-8"))
    assert len(rows) == 40
    assert [row["molecule"] for row in rows if row["mapping_status"] == "Missing docking/SDF"] == [
        "midostaurin_fixed", "midostaurin",
    ]
    distorted = next(row for row in rows if row["molecule"] == "structures_1756")
    assert distorted["validation_flag"] == "Review PDBQT geometry"
    assert distorted["bonds_over_2_2A"] == 11
