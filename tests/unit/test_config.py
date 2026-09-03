from __future__ import annotations

import pytest

from drug_discovery_agent.config.models import ProjectConfig


def base_config() -> dict:
    return {
        "project": {"id": "example_project"},
        "workflow": "vina_only",
        "target": {"receptor_ref": "receptor_01", "receptor_pdbqt_ref": "receptor_vina"},
        "pocket": {"mode": "explicit", "center": [1, 2, 3], "vina_size": [20, 20, 20]},
        "ligands": [{"source_ref": "ligand_set_01", "kind": "multi_sdf"}],
        "vina": {"enabled": True, "profile": "full"},
    }


def test_profiles_preserve_both_legacy_modes() -> None:
    config = ProjectConfig.model_validate(base_config())
    assert config.vina.profiles["fast"].exhaustiveness == 4
    assert config.vina.profiles["fast"].num_modes == 1
    assert config.vina.profiles["full"].exhaustiveness == 8
    assert config.vina.profiles["full"].num_modes == 3


def test_vina_requires_target_specific_box() -> None:
    raw = base_config()
    raw["pocket"] = {"mode": "none"}
    with pytest.raises(ValueError, match="Vina execution requires"):
        ProjectConfig.model_validate(raw)


def test_weighted_ranking_requires_explicit_weights() -> None:
    raw = base_config()
    raw["ranking"] = {"policy": "weighted_consensus"}
    with pytest.raises(ValueError, match="explicit weights"):
        ProjectConfig.model_validate(raw)


def test_cloud_projection_is_allowlisted() -> None:
    raw = base_config()
    raw["target"]["protein_sequence"] = "ACDEFG"
    config = ProjectConfig.model_validate(raw)
    payload = config.cloud_projection()
    text = str(payload).lower()
    assert "protein_sequence" not in text
    assert "receptor_01" not in text
    assert "ligand_set_01" not in text


def test_pocketminer_mode_defers_vina_box_until_user_selection() -> None:
    raw = base_config()
    raw["pocket"] = {"mode": "pocketminer"}
    config = ProjectConfig.model_validate(raw)
    assert config.pocket.center is None
    assert config.pocketminer.runtime.implementation == "Mickdub/gvp:pocket_pred"


def test_downstream_vina_selection_is_bounded_and_metric_is_validated() -> None:
    raw = base_config()
    raw["analysis"] = {"vina_shortlist": 50, "vina_selection_metric": "ligand_efficiency"}
    config = ProjectConfig.model_validate(raw)
    assert config.analysis.vina_shortlist == 50
    assert config.analysis.vina_selection_metric == "ligand_efficiency"

    raw["analysis"]["vina_shortlist"] = 51
    with pytest.raises(ValueError, match="less than or equal to 50"):
        ProjectConfig.model_validate(raw)

    raw["analysis"] = {"vina_shortlist": 10, "vina_selection_metric": "made_up"}
    with pytest.raises(ValueError, match="best_affinity"):
        ProjectConfig.model_validate(raw)
