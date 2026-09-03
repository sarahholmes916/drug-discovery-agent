from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from drug_discovery_agent.config.models import ProjectConfig, WorkflowName
from drug_discovery_agent.execution.commands import CancellationToken
from drug_discovery_agent.project.hashing import sha256_file, stable_json_hash
from drug_discovery_agent.project.io import read_json
from drug_discovery_agent.project.layout import ProjectLayout
from drug_discovery_agent.project.state import ItemStatus, RunState, StageName, StageStatus, StateStore


BASE = [
    StageName.INGEST_PROJECT, StageName.PREPARE_RECEPTOR,
    StageName.RUN_POCKETMINER, StageName.PARSE_POCKETMINER_SCORES,
    StageName.DETECT_CANDIDATE_POCKETS, StageName.RANK_CANDIDATE_POCKETS,
    StageName.AWAIT_POCKET_SELECTION, StageName.CONFIRM_SELECTED_POCKET,
    StageName.DEFINE_OR_IMPORT_POCKET, StageName.INGEST_LIGANDS,
    StageName.PREPARE_LIGANDS, StageName.RUN_VINA, StageName.QC_VINA,
    StageName.SHORTLIST_VINA,
]
FINISH = [StageName.RANK_CONSENSUS, StageName.BUILD_REPORT]


STAGE_DEPENDENCIES: dict[StageName, tuple[StageName, ...]] = {
    StageName.INGEST_PROJECT: (),
    StageName.PREPARE_RECEPTOR: (StageName.INGEST_PROJECT,),
    StageName.RUN_POCKETMINER: (StageName.PREPARE_RECEPTOR,),
    StageName.PARSE_POCKETMINER_SCORES: (StageName.RUN_POCKETMINER,),
    StageName.DETECT_CANDIDATE_POCKETS: (StageName.PARSE_POCKETMINER_SCORES,),
    StageName.RANK_CANDIDATE_POCKETS: (StageName.DETECT_CANDIDATE_POCKETS,),
    StageName.AWAIT_POCKET_SELECTION: (StageName.RANK_CANDIDATE_POCKETS,),
    StageName.CONFIRM_SELECTED_POCKET: (StageName.AWAIT_POCKET_SELECTION,),
    StageName.DEFINE_OR_IMPORT_POCKET: (StageName.PREPARE_RECEPTOR, StageName.CONFIRM_SELECTED_POCKET),
    StageName.INGEST_LIGANDS: (StageName.INGEST_PROJECT,),
    StageName.PREPARE_LIGANDS: (StageName.INGEST_LIGANDS,),
    StageName.RUN_VINA: (
        StageName.PREPARE_RECEPTOR,
        StageName.DEFINE_OR_IMPORT_POCKET,
        StageName.PREPARE_LIGANDS,
    ),
    StageName.QC_VINA: (StageName.RUN_VINA,),
    StageName.SHORTLIST_VINA: (StageName.QC_VINA,),
    StageName.PREPARE_BOLTZ_CONSTRAINED: (
        StageName.SHORTLIST_VINA,
        StageName.DEFINE_OR_IMPORT_POCKET,
        StageName.PREPARE_RECEPTOR,
    ),
    StageName.PREPARE_BOLTZ_UNCONSTRAINED: (
        StageName.SHORTLIST_VINA,
        StageName.PREPARE_RECEPTOR,
    ),
    StageName.RUN_BOLTZ_CONSTRAINED: (StageName.PREPARE_BOLTZ_CONSTRAINED,),
    StageName.RUN_BOLTZ_UNCONSTRAINED: (StageName.PREPARE_BOLTZ_UNCONSTRAINED,),
    StageName.QC_BOLTZ: (StageName.RUN_BOLTZ_CONSTRAINED, StageName.RUN_BOLTZ_UNCONSTRAINED),
    StageName.ANALYZE_VINA_POSES: (
        StageName.SHORTLIST_VINA,
        StageName.PREPARE_RECEPTOR,
    ),
    StageName.ANALYZE_BOLTZ_INTERACTIONS: (
        StageName.QC_BOLTZ,
        StageName.RUN_BOLTZ_CONSTRAINED,
        StageName.RUN_BOLTZ_UNCONSTRAINED,
    ),
    StageName.ALIGN_AND_COMPARE_POSES: (
        StageName.ANALYZE_VINA_POSES,
        StageName.ANALYZE_BOLTZ_INTERACTIONS,
    ),
    StageName.RANK_CONSENSUS: (
        StageName.SHORTLIST_VINA,
        StageName.QC_BOLTZ,
        StageName.ALIGN_AND_COMPARE_POSES,
    ),
    StageName.BUILD_REPORT: (StageName.RANK_CONSENSUS,),
}


STAGE_OUTPUTS: dict[StageName, tuple[str, ...]] = {
    StageName.INGEST_PROJECT: ("project.yaml", "state/local_refs.json"),
    StageName.PREPARE_RECEPTOR: ("state/receptor.json",),
    StageName.RUN_POCKETMINER: ("pocketminer/raw/predictions.npy", "pocketminer/raw/run_metadata.json"),
    StageName.PARSE_POCKETMINER_SCORES: (
        "pocketminer/scores/residue_scores.json", "pocketminer/scores/residue_scores.csv",
        "pocketminer/visualization/receptor_pocketminer_scores.pdb",
    ),
    StageName.DETECT_CANDIDATE_POCKETS: ("pocketminer/candidates/detected_pockets.json",),
    StageName.RANK_CANDIDATE_POCKETS: ("pocketminer/candidates/ranked_pockets.json",),
    StageName.AWAIT_POCKET_SELECTION: ("state/selected_pocket.json",),
    StageName.CONFIRM_SELECTED_POCKET: ("state/selected_pocket.json",),
    StageName.DEFINE_OR_IMPORT_POCKET: ("state/residue_mapping.json",),
    StageName.INGEST_LIGANDS: ("state/ligand_ingestion.json", "state/manifest.json"),
    StageName.PREPARE_LIGANDS: ("state/ligand_preparation.json",),
    StageName.RUN_VINA: ("state/vina_results.json",),
    StageName.QC_VINA: ("state/vina_qc.json",),
    StageName.SHORTLIST_VINA: ("state/vina_ranking.json", "state/vina_shortlist.json"),
    StageName.PREPARE_BOLTZ_CONSTRAINED: ("state/boltz_vina_site_constrained_inputs.json",),
    StageName.PREPARE_BOLTZ_UNCONSTRAINED: ("state/boltz_unconstrained_inputs.json",),
    StageName.RUN_BOLTZ_CONSTRAINED: ("state/boltz_vina_site_constrained_results.json",),
    StageName.RUN_BOLTZ_UNCONSTRAINED: ("state/boltz_unconstrained_results.json",),
    StageName.QC_BOLTZ: ("state/boltz_qc.json",),
    StageName.ANALYZE_VINA_POSES: ("interactions/vina/results.json",),
    StageName.ANALYZE_BOLTZ_INTERACTIONS: ("interactions/boltz/results.json",),
    StageName.ALIGN_AND_COMPARE_POSES: ("comparison/pose_comparisons.json",),
    StageName.RANK_CONSENSUS: ("comparison/ranking.json",),
    StageName.BUILD_REPORT: (
        "reports/results.json",
        "reports/results.csv",
        "reports/report.html",
        "reports/manifest.json",
    ),
}


def _stage_config(config: ProjectConfig, stage: StageName) -> object:
    """Return only configuration that can influence a stage's scientific result."""
    if stage == StageName.INGEST_PROJECT:
        return {"project_id": config.project.id}
    if stage == StageName.PREPARE_RECEPTOR:
        return {
            "target_refs": config.target.model_dump(
                include={"receptor_ref", "receptor_pdbqt_ref", "receptor_template_ref"}, mode="json"
            ),
            "boltz_enabled": config.boltz.constrained.enabled or config.boltz.unconstrained.enabled,
        }
    if stage in {
        StageName.RUN_POCKETMINER,
        StageName.PARSE_POCKETMINER_SCORES,
        StageName.DETECT_CANDIDATE_POCKETS,
        StageName.RANK_CANDIDATE_POCKETS,
        StageName.AWAIT_POCKET_SELECTION,
        StageName.CONFIRM_SELECTED_POCKET,
    }:
        return {"mode": config.pocket.mode, "pocketminer": config.pocketminer.model_dump(mode="json")}
    if stage == StageName.DEFINE_OR_IMPORT_POCKET:
        return {
            "pocket": config.pocket.model_dump(mode="json"),
            "protein_sequence": config.target.protein_sequence,
            "protein_chain": config.target.protein_chain,
            "constrained": config.boltz.constrained.enabled,
        }
    if stage == StageName.INGEST_LIGANDS:
        return [item.model_dump(mode="json") for item in config.ligands]
    if stage == StageName.PREPARE_LIGANDS:
        return {"conformer_random_seed": config.execution.conformer_random_seed}
    if stage == StageName.RUN_VINA:
        return {
            "vina": config.vina.model_dump(mode="json"),
            "center": config.pocket.center,
            "size": config.pocket.vina_size,
        }
    if stage == StageName.SHORTLIST_VINA:
        return {
            "downstream_ligand_count": config.analysis.vina_shortlist,
            "selection_metric": config.analysis.vina_selection_metric,
        }
    if stage in {StageName.PREPARE_BOLTZ_CONSTRAINED, StageName.PREPARE_BOLTZ_UNCONSTRAINED}:
        projection = {
            "target": config.target.model_dump(
                include={"protein_sequence", "protein_chain", "receptor_template_ref"}, mode="json"
            ),
            "protein_id": config.boltz.protein_id,
            "ligand_id": config.boltz.ligand_id,
        }
        if stage == StageName.PREPARE_BOLTZ_CONSTRAINED:
            projection["constraints"] = {
                "template_force": config.boltz.template_force,
                "template_threshold": config.boltz.template_threshold,
                "pocket_force": config.boltz.pocket_force,
                "pocket_max_distance": config.boltz.pocket_max_distance,
            }
        return projection
    if stage in {StageName.RUN_BOLTZ_CONSTRAINED, StageName.RUN_BOLTZ_UNCONSTRAINED}:
        return config.boltz.model_dump(mode="json")
    if stage == StageName.ANALYZE_VINA_POSES:
        return config.analysis.thresholds.model_dump(mode="json")
    if stage == StageName.ANALYZE_BOLTZ_INTERACTIONS:
        return {"analyze_all_downstream_ligands": True}
    if stage == StageName.ALIGN_AND_COMPARE_POSES:
        return {"alignment_mode": config.analysis.alignment_mode}
    if stage == StageName.RANK_CONSENSUS:
        return config.ranking.model_dump(mode="json")
    if stage == StageName.BUILD_REPORT:
        return {
            "title": config.project.display_name or config.project.id,
            "reporting": config.reporting.model_dump(mode="json"),
        }
    return {}


def _reference_hashes(context: "PipelineContext", stage: StageName) -> dict[str, object]:
    references: list[str] = []
    if stage == StageName.PREPARE_RECEPTOR:
        references = [
            value
            for value in (
                context.config.target.receptor_ref,
                context.config.target.receptor_pdbqt_ref,
                context.config.target.receptor_template_ref,
            )
            if value
        ]
    elif stage in {StageName.RUN_POCKETMINER, StageName.PARSE_POCKETMINER_SCORES}:
        references = [context.config.target.receptor_ref]
    elif stage == StageName.INGEST_LIGANDS:
        references = [item.source_ref for item in context.config.ligands]
    elif stage == StageName.BUILD_REPORT and context.config.reporting.source_workbook_ref:
        references = [context.config.reporting.source_workbook_ref]
    result: dict[str, object] = {}
    for reference in sorted(set(references)):
        path = context.local_references.get(reference)
        if path is None or not path.exists():
            result[reference] = None
        elif path.is_file():
            result[reference] = sha256_file(path)
        else:
            result[reference] = {
                child.relative_to(path).as_posix(): sha256_file(child)
                for child in sorted(path.rglob("*"))
                if child.is_file()
            }
    if stage in {StageName.AWAIT_POCKET_SELECTION, StageName.CONFIRM_SELECTED_POCKET}:
        selection = context.layout.state / "selected_pocket.json"
        result["selected_pocket"] = sha256_file(selection) if selection.is_file() else None
    return result


def _stage_tool_versions(context: "PipelineContext", stage: StageName) -> dict[str, object]:
    if stage == StageName.RUN_POCKETMINER:
        from drug_discovery_agent.pocketminer.runtime import inspect_installation
        report = inspect_installation(context.config.pocketminer.runtime)
        return {
            "pocketminer": {
                "implementation": report.get("implementation"),
                "commit": report.get("commit"),
                "checkpoint_sha256": report.get("checkpoint_sha256"),
                "dependencies": report.get("dependencies"),
            }
        }
    names = {
        StageName.PREPARE_LIGANDS: ("rdkit", "meeko"),
        StageName.RUN_VINA: ("vina",),
        StageName.RUN_BOLTZ_CONSTRAINED: ("boltz",),
        StageName.RUN_BOLTZ_UNCONSTRAINED: ("boltz",),
        StageName.ANALYZE_BOLTZ_INTERACTIONS: ("plip",),
    }.get(stage, ())
    provenance = read_json(context.layout.provenance, {})
    packages = provenance.get("packages", {}) if isinstance(provenance, dict) else {}
    tools = provenance.get("tools", {}) if isinstance(provenance, dict) else {}
    managed = context.data.get("tool_versions", {})
    if not isinstance(managed, dict):
        managed = {}
    return {name: managed.get(name) or tools.get(name) or packages.get(name) for name in names}


def stage_fingerprint(context: "PipelineContext", stage: StageName, selected: set[StageName]) -> str:
    dependencies = {
        dependency.value: context.run_state.stages.get(dependency).input_hash
        if context.run_state.stages.get(dependency) else None
        for dependency in STAGE_DEPENDENCIES.get(stage, ())
        if dependency in selected
    }
    if stage in {StageName.RUN_BOLTZ_CONSTRAINED, StageName.RUN_BOLTZ_UNCONSTRAINED}:
        implementation_revision = "0.1.2"
    elif stage == StageName.ANALYZE_BOLTZ_INTERACTIONS:
        implementation_revision = "0.1.1"
    elif stage in {StageName.PREPARE_BOLTZ_CONSTRAINED, StageName.PREPARE_BOLTZ_UNCONSTRAINED}:
        implementation_revision = "0.1.1"
    else:
        implementation_revision = "0.1.0"
    return stable_json_hash({
        "implementation": f"drug-discovery-agent-{implementation_revision}:{stage.value}",
        "config": _stage_config(context.config, stage),
        "references": _reference_hashes(context, stage),
        "tools": _stage_tool_versions(context, stage),
        "dependencies": dependencies,
    })


def stage_outputs_exist(context: "PipelineContext", stage: StageName) -> bool:
    state = context.run_state.stages.get(stage)
    if state is None:
        return False
    if any(not (context.layout.root / relative).is_file() for relative in STAGE_OUTPUTS.get(stage, ())):
        return False
    if (
        stage == StageName.BUILD_REPORT
        and context.config.reporting.source_workbook_ref
        and not (context.layout.root / "reports" / context.config.reporting.output_workbook_name).is_file()
    ):
        return False
    if stage == StageName.INGEST_LIGANDS:
        ingestion = read_json(context.layout.state / "ligand_ingestion.json", {})
        output_files = ingestion.get("output_files", {}) if isinstance(ingestion, dict) else {}
        if not output_files or any(
            not (context.layout.root / relative).is_file() for relative in output_files.values()
        ):
            return False
    for item in state.items.values():
        if item.status == ItemStatus.SUCCESS and not context.state_store.reusable_item(item, item.input_hash):
            return False
    return True


def workflow_stages(config: ProjectConfig) -> list[StageName]:
    if config.workflow == WorkflowName.CUSTOM:
        return [StageName(value) for value in config.custom_stages]
    if config.workflow == WorkflowName.VINA_ONLY:
        return [*BASE, StageName.ANALYZE_VINA_POSES, *FINISH]
    constrained = [StageName.PREPARE_BOLTZ_CONSTRAINED, StageName.RUN_BOLTZ_CONSTRAINED]
    unconstrained = [StageName.PREPARE_BOLTZ_UNCONSTRAINED, StageName.RUN_BOLTZ_UNCONSTRAINED]
    shared = [StageName.QC_BOLTZ, StageName.ANALYZE_VINA_POSES,
              StageName.ANALYZE_BOLTZ_INTERACTIONS, StageName.ALIGN_AND_COMPARE_POSES]
    if config.workflow == WorkflowName.VINA_TO_CONSTRAINED_BOLTZ:
        return [*BASE, *constrained, *shared, *FINISH]
    if config.workflow == WorkflowName.VINA_TO_UNCONSTRAINED_BOLTZ:
        return [*BASE, *unconstrained, *shared, *FINISH]
    return [*BASE, *constrained, *unconstrained, *shared, *FINISH]


@dataclass(slots=True)
class StageOutcome:
    status: StageStatus = StageStatus.SUCCESS
    message: str | None = None
    completed: int = 0
    total: int = 0
    failed: int = 0
    candidate_count: int | None = None


@dataclass(slots=True)
class PipelineContext:
    config: ProjectConfig
    layout: ProjectLayout
    run_state: RunState
    state_store: StateStore
    cancellation: CancellationToken
    local_references: Mapping[str, Path]
    data: dict[str, object] = field(default_factory=dict)


StageHandler = Callable[[PipelineContext], StageOutcome]
ProgressHandler = Callable[[StageName, StageOutcome], None]


class PipelineOrchestrator:
    def __init__(self, handlers: Mapping[StageName, StageHandler]) -> None:
        self.handlers = dict(handlers)

    def run(self, context: PipelineContext, progress: ProgressHandler | None = None) -> RunState:
        selected = workflow_stages(context.config)
        selected_set = set(selected)
        for stage_name in selected:
            if context.run_state.cancellation_requested or context.cancellation.cancelled:
                context.run_state.status = StageStatus.CANCELLED
                context.state_store.save(context.run_state)
                return context.run_state
            handler = self.handlers.get(stage_name)
            if handler is None:
                raise RuntimeError(f"no implementation registered for selected stage {stage_name}")
            stage = context.run_state.stages.get(stage_name)
            input_hash = stage_fingerprint(context, stage_name, selected_set)
            if (
                stage
                and stage.status == StageStatus.SUCCESS
                and stage.input_hash == input_hash
                and stage_outputs_exist(context, stage_name)
            ):
                outcome = StageOutcome(StageStatus.SKIPPED, "already completed")
                if progress:
                    progress(stage_name, outcome)
                continue
            if stage and stage.status in {StageStatus.FAILED, StageStatus.PARTIAL, StageStatus.CANCELLED,
                                         StageStatus.NEEDS_REVIEW, StageStatus.SKIPPED, StageStatus.SUCCESS,
                                         StageStatus.AWAITING_USER_SELECTION}:
                context.state_store.transition(context.run_state, stage_name, StageStatus.READY)
            elif not stage or stage.status == StageStatus.PENDING:
                context.state_store.transition(context.run_state, stage_name, StageStatus.READY)
            context.state_store.transition(
                context.run_state, stage_name, StageStatus.RUNNING, input_hash=input_hash
            )
            try:
                outcome = handler(context)
            except Exception as exc:
                outcome = StageOutcome(StageStatus.FAILED, str(exc), failed=1)
            context.state_store.transition(context.run_state, stage_name, outcome.status, message=outcome.message)
            if progress:
                progress(stage_name, outcome)
            if outcome.status in {
                StageStatus.FAILED, StageStatus.CANCELLED, StageStatus.AWAITING_USER_SELECTION,
            }:
                context.run_state.status = outcome.status
                context.state_store.save(context.run_state)
                return context.run_state
        terminal_states = [context.run_state.stages[name].status for name in selected]
        if any(status == StageStatus.NEEDS_REVIEW for status in terminal_states):
            context.run_state.status = StageStatus.NEEDS_REVIEW
        elif any(status == StageStatus.PARTIAL for status in terminal_states):
            context.run_state.status = StageStatus.PARTIAL
        else:
            context.run_state.status = StageStatus.SUCCESS
        context.state_store.save(context.run_state)
        return context.run_state
