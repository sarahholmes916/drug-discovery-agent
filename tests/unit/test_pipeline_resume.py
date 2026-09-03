from __future__ import annotations

from pathlib import Path

from drug_discovery_agent.config.models import ProjectConfig
from drug_discovery_agent.execution.commands import CancellationToken
from drug_discovery_agent.pipeline.orchestrator import (
    PipelineContext,
    PipelineOrchestrator,
    StageOutcome,
    stage_fingerprint,
)
from drug_discovery_agent.project.io import atomic_write_json
from drug_discovery_agent.project.layout import create_project
from drug_discovery_agent.project.state import RunState, StageName, StateStore


def _config(*, workflow: str = "custom", custom_stages: list[str] | None = None) -> ProjectConfig:
    both = workflow == "vina_to_both_boltz"
    return ProjectConfig.model_validate({
        "project": {"id": "resume_project"},
        "workflow": workflow,
        "custom_stages": custom_stages or [],
        "target": {
            "receptor_ref": "receptor",
            "receptor_pdbqt_ref": "receptor_pdbqt",
            "receptor_template_ref": "template",
            "protein_sequence": "ACDE",
        },
        "pocket": {"mode": "explicit", "center": [1, 2, 3], "vina_size": [10, 10, 10]},
        "ligands": [{"source_ref": "ligands", "kind": "multi_sdf"}],
        "vina": {"enabled": workflow != "custom"},
        "boltz": {
            "constrained": {"enabled": both},
            "unconstrained": {"enabled": both},
        },
    })


def _context(tmp_path: Path, config: ProjectConfig) -> PipelineContext:
    sources = tmp_path / "sources"
    sources.mkdir()
    references = {
        "receptor": sources / "receptor.pdb",
        "receptor_pdbqt": sources / "receptor.pdbqt",
        "template": sources / "template.cif",
        "ligands": sources / "ligands.sdf",
    }
    for name, path in references.items():
        path.write_text(f"fixture {name}\n", encoding="utf-8")
    layout = create_project(tmp_path / "projects", config, references)
    state = RunState(run_id="run_resume", project_id=config.project.id)
    store = StateStore(layout.run_state, layout.root)
    store.save(state)
    return PipelineContext(
        config=config,
        layout=layout,
        run_state=state,
        state_store=store,
        cancellation=CancellationToken(),
        local_references=references,
    )


def test_successful_stage_is_reused_only_while_outputs_exist(tmp_path: Path) -> None:
    config = _config(custom_stages=[StageName.INGEST_PROJECT.value])
    context = _context(tmp_path, config)
    calls = 0

    def ingest(current: PipelineContext) -> StageOutcome:
        nonlocal calls
        calls += 1
        if not current.layout.local_references.exists():
            atomic_write_json(current.layout.local_references, {"schema_version": 1, "references": {}})
        return StageOutcome(completed=1, total=1)

    orchestrator = PipelineOrchestrator({StageName.INGEST_PROJECT: ingest})
    orchestrator.run(context)
    orchestrator.run(context)
    assert calls == 1

    context.layout.local_references.unlink()
    orchestrator.run(context)
    assert calls == 2


def test_constraint_change_invalidates_only_constrained_input_branch(tmp_path: Path) -> None:
    context = _context(tmp_path, _config(workflow="vina_to_both_boltz"))
    selected = {
        StageName.PREPARE_BOLTZ_CONSTRAINED,
        StageName.PREPARE_BOLTZ_UNCONSTRAINED,
    }
    constrained_before = stage_fingerprint(context, StageName.PREPARE_BOLTZ_CONSTRAINED, selected)
    unconstrained_before = stage_fingerprint(context, StageName.PREPARE_BOLTZ_UNCONSTRAINED, selected)

    context.config.boltz.template_force = False

    assert stage_fingerprint(context, StageName.PREPARE_BOLTZ_CONSTRAINED, selected) != constrained_before
    assert stage_fingerprint(context, StageName.PREPARE_BOLTZ_UNCONSTRAINED, selected) == unconstrained_before


def test_ligand_content_change_does_not_invalidate_receptor_branch(tmp_path: Path) -> None:
    context = _context(tmp_path, _config(workflow="vina_to_both_boltz"))
    selected = {StageName.PREPARE_RECEPTOR, StageName.INGEST_LIGANDS}
    receptor_before = stage_fingerprint(context, StageName.PREPARE_RECEPTOR, selected)
    ligands_before = stage_fingerprint(context, StageName.INGEST_LIGANDS, selected)

    context.local_references["ligands"].write_text("changed ligand content\n", encoding="utf-8")

    assert stage_fingerprint(context, StageName.PREPARE_RECEPTOR, selected) == receptor_before
    assert stage_fingerprint(context, StageName.INGEST_LIGANDS, selected) != ligands_before


def test_vina_selection_metric_invalidates_only_the_post_vina_gate(tmp_path: Path) -> None:
    context = _context(tmp_path, _config(workflow="vina_to_both_boltz"))
    selected = {StageName.RUN_VINA, StageName.SHORTLIST_VINA}
    vina_before = stage_fingerprint(context, StageName.RUN_VINA, selected)
    gate_before = stage_fingerprint(context, StageName.SHORTLIST_VINA, selected)

    context.config.analysis.vina_selection_metric = "mean_affinity"

    assert stage_fingerprint(context, StageName.RUN_VINA, selected) == vina_before
    assert stage_fingerprint(context, StageName.SHORTLIST_VINA, selected) != gate_before


def test_managed_tool_identity_prevents_transient_help_output_from_invalidating_boltz(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, _config(workflow="vina_to_both_boltz"))
    context.data["tool_versions"] = {
        "boltz": {"version": "2.2.1", "torch_version": "2.7.1+cu128"},
    }
    atomic_write_json(context.layout.provenance, {"tools": {"boltz": "transient help A"}})
    selected = {StageName.RUN_BOLTZ_CONSTRAINED}
    before = stage_fingerprint(context, StageName.RUN_BOLTZ_CONSTRAINED, selected)

    atomic_write_json(context.layout.provenance, {"tools": {"boltz": "transient help B"}})

    assert stage_fingerprint(context, StageName.RUN_BOLTZ_CONSTRAINED, selected) == before
