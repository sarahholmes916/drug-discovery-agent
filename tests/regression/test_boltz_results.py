from __future__ import annotations

from pathlib import Path

from drug_discovery_agent.boltz.results import parse_prediction_directory


ROOT = Path(__file__).parents[2]


def test_all_five_constrained_models_and_metrics_are_preserved() -> None:
    prediction = parse_prediction_directory(
        ROOT / "legacy" / "boltz" / "example_predictions" / "ns1_structures_12233",
        ligand_id="structures_12233", mode="vina_site_constrained",
    )
    assert [model.model_index for model in prediction.models] == [0, 1, 2, 3, 4]
    assert prediction.affinity_pred_value == 0.3271985650062561
    assert prediction.models[0].confidence_score == 0.435476690530777
    assert prediction.models[4].ligand_iptm == 0.7262257933616638


def test_unconstrained_metrics_are_parsed_separately() -> None:
    prediction = parse_prediction_directory(
        ROOT / "legacy" / "boltz" / "unconstrained" / "example_predictions" / "ns1_structures_12233",
        ligand_id="structures_12233", mode="unconstrained",
    )
    assert prediction.mode == "unconstrained"
    assert prediction.affinity_pred_value == 0.47490590810775757
    assert prediction.models[0].confidence_score == 0.9101083874702454

