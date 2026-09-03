from __future__ import annotations

from drug_discovery_agent.config.models import ProjectConfig
from drug_discovery_agent.pipeline.orchestrator import workflow_stages
from drug_discovery_agent.project.state import StageName


def config_for(workflow: str) -> ProjectConfig:
    constrained = workflow in {"vina_to_constrained_boltz", "vina_to_both_boltz", "full"}
    unconstrained = workflow in {"vina_to_unconstrained_boltz", "vina_to_both_boltz", "full"}
    return ProjectConfig.model_validate({
        "project": {"id": "project_1"}, "workflow": workflow,
        "target": {"receptor_ref": "receptor", "receptor_pdbqt_ref": "pdbqt",
                   "receptor_template_ref": "template", "protein_sequence": "ACDE"},
        "pocket": {"mode": "explicit", "center": [1, 2, 3], "vina_size": [10, 10, 10]},
        "ligands": [{"source_ref": "ligands", "kind": "multi_sdf"}],
        "vina": {"enabled": True},
        "boltz": {"constrained": {"enabled": constrained}, "unconstrained": {"enabled": unconstrained}},
    })


def test_both_boltz_conditions_are_separate_stage_branches() -> None:
    stages = workflow_stages(config_for("vina_to_both_boltz"))
    assert StageName.PREPARE_BOLTZ_CONSTRAINED in stages
    assert StageName.PREPARE_BOLTZ_UNCONSTRAINED in stages
    assert StageName.RUN_BOLTZ_CONSTRAINED in stages
    assert StageName.RUN_BOLTZ_UNCONSTRAINED in stages


def test_vina_only_does_not_silently_run_boltz() -> None:
    stages = workflow_stages(config_for("vina_only"))
    assert not any("BOLTZ" in stage.value for stage in stages)

