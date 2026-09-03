from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from drug_discovery_agent.boltz.inputs import (
    build_constrained_input, build_unconstrained_input, write_boltz_input,
)
from drug_discovery_agent.boltz.results import BoltzPrediction, parse_prediction_directory
from drug_discovery_agent.boltz.runner import boltz_execution_error, run_boltz
from drug_discovery_agent.execution.commands import CommandExecutor
from drug_discovery_agent.execution.scheduler import BoundedScheduler
from drug_discovery_agent.ligands.ingest import ingest_ligands
from drug_discovery_agent.ligands.prepare import PreparedLigand, prepare_ligand
from drug_discovery_agent.pipeline.orchestrator import PipelineContext, StageHandler, StageOutcome
from drug_discovery_agent.pocketminer.box import build_box
from drug_discovery_agent.pocketminer.clustering import smooth_scores, spatial_components
from drug_discovery_agent.pocketminer.geometry import attach_representatives
from drug_discovery_agent.pocketminer.models import CandidatePocket, PocketMinerRunMetadata, PocketMetrics
from drug_discovery_agent.pocketminer.parser import (
    parse_native_predictions, parse_normalized_scores, write_normalized_scores,
)
from drug_discovery_agent.pocketminer.ranking import rank_components
from drug_discovery_agent.pocketminer.runtime import inspect_installation, run_official
from drug_discovery_agent.pocketminer.selection import load_valid_selection
from drug_discovery_agent.pocketminer.visualization import write_probability_pdb
from drug_discovery_agent.plip.runner import PLIPJob, PLIPResult, run_plip_jobs
from drug_discovery_agent.project.hashing import stage_input_hash
from drug_discovery_agent.project.io import atomic_write_json, read_json
from drug_discovery_agent.project.manifest import ManifestStore, ProjectManifest
from drug_discovery_agent.project.state import FailureRecord, ItemState, ItemStatus, StageName, StageStatus
from drug_discovery_agent.ranking.consensus import MetricSpec, rank_weighted_consensus
from drug_discovery_agent.receptor.mapping import ResidueMapping, map_pocket_residues
from drug_discovery_agent.receptor.pocket import select_pocket_residues
from drug_discovery_agent.receptor.conversion import (
    convert_pdb_template_to_mmcif,
    convert_pdbqt_to_pdb,
    validate_coordinates,
)
from drug_discovery_agent.reporting.report import build_report
from drug_discovery_agent.reporting.workbook import append_analysis_workbook
from drug_discovery_agent.vina.distances import parse_receptor_pdbqt, residue_distances
from drug_discovery_agent.vina.interactions import analyze_interactions, binding_site_residues
from drug_discovery_agent.vina.models import VinaMode, VinaResult
from drug_discovery_agent.vina.poses import mode1_pose, parse_vina_poses
from drug_discovery_agent.vina.reconstruction import reconstruct_ligand, write_sdf
from drug_discovery_agent.vina.runner import run_vina
from drug_discovery_agent.vina.shortlist import rank_vina_results, shortlist_vina

from .tool_paths import managed_plip_environment


def _write(path: Path, value: object) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    atomic_write_json(path, value)


def _aggregate(statuses: list[str], message: str | None = None) -> StageOutcome:
    failed = sum(value == "FAILED" for value in statuses)
    review = sum(value == "NEEDS_REVIEW" for value in statuses)
    successful = sum(value in {"SUCCESS", "SKIPPED"} for value in statuses)
    if not statuses:
        return StageOutcome(StageStatus.FAILED, message or "stage selected no items", failed=1)
    if failed == len(statuses):
        status = StageStatus.FAILED
    elif failed or (review and successful):
        status = StageStatus.PARTIAL
    elif review:
        status = StageStatus.NEEDS_REVIEW
    else:
        status = StageStatus.SUCCESS
    return StageOutcome(status, message, completed=successful, total=len(statuses), failed=failed)


class LocalStageHandlers:
    def __init__(self, command_directory: str | Path | None = None) -> None:
        self.executor = CommandExecutor(command_directory)

    def handlers(self) -> dict[StageName, StageHandler]:
        return {
            StageName.INGEST_PROJECT: self.ingest_project,
            StageName.PREPARE_RECEPTOR: self.prepare_receptor,
            StageName.RUN_POCKETMINER: self.run_pocketminer,
            StageName.PARSE_POCKETMINER_SCORES: self.parse_pocketminer_scores,
            StageName.DETECT_CANDIDATE_POCKETS: self.detect_candidate_pockets,
            StageName.RANK_CANDIDATE_POCKETS: self.rank_candidate_pockets,
            StageName.AWAIT_POCKET_SELECTION: self.await_pocket_selection,
            StageName.CONFIRM_SELECTED_POCKET: self.confirm_selected_pocket,
            StageName.DEFINE_OR_IMPORT_POCKET: self.define_pocket,
            StageName.INGEST_LIGANDS: self.ingest_ligands,
            StageName.PREPARE_LIGANDS: self.prepare_ligands,
            StageName.RUN_VINA: self.run_vina_stage,
            StageName.QC_VINA: self.qc_vina,
            StageName.SHORTLIST_VINA: self.shortlist,
            StageName.PREPARE_BOLTZ_CONSTRAINED: self.prepare_boltz_constrained,
            StageName.PREPARE_BOLTZ_UNCONSTRAINED: self.prepare_boltz_unconstrained,
            StageName.RUN_BOLTZ_CONSTRAINED: self.run_boltz_constrained,
            StageName.RUN_BOLTZ_UNCONSTRAINED: self.run_boltz_unconstrained,
            StageName.QC_BOLTZ: self.qc_boltz,
            StageName.ANALYZE_VINA_POSES: self.analyze_vina,
            StageName.ANALYZE_BOLTZ_INTERACTIONS: self.analyze_boltz,
            StageName.ALIGN_AND_COMPARE_POSES: self.compare,
            StageName.RANK_CONSENSUS: self.rank,
            StageName.BUILD_REPORT: self.report,
        }

    @staticmethod
    def _record_failure(
        context: PipelineContext,
        stage: StageName,
        input_identifier: str,
        error: str,
        command=None,
    ) -> None:
        context.state_store.record_failure(
            context.run_state,
            FailureRecord(
                stage=stage,
                input_identifier=input_identifier,
                error_message=error,
                external_command=command.command if command else None,
                exit_code=command.return_code if command else None,
            ),
        )

    @staticmethod
    def _tool_versions(context: PipelineContext, *names: str) -> dict[str, object]:
        provenance = read_json(context.layout.provenance, {})
        packages = provenance.get("packages", {}) if isinstance(provenance, dict) else {}
        tools = provenance.get("tools", {}) if isinstance(provenance, dict) else {}
        managed = context.data.get("tool_versions", {})
        if not isinstance(managed, dict):
            managed = {}
        return {name: managed.get(name) or tools.get(name) or packages.get(name) for name in names}

    @staticmethod
    def _ref(context: PipelineContext, reference: str | None) -> Path:
        if not reference or reference not in context.local_references:
            raise ValueError(f"local reference is not registered: {reference}")
        path = context.local_references[reference]
        if not path.exists():
            raise FileNotFoundError(path)
        return path

    def _normalize_boltz_template(self, context: PipelineContext, template: Path) -> Path:
        if template.suffix.lower() in {".cif", ".mmcif"}:
            return template
        if template.suffix.lower() not in {".pdb", ".ent"}:
            raise ValueError(f"Boltz receptor template must be PDB or mmCIF: {template}")
        converted = context.layout.root / "receptor" / "boltz_template.cif"
        validation = convert_pdb_template_to_mmcif(
            template,
            converted,
            protein_sequence=context.config.target.protein_sequence,
            protein_chain=context.config.target.protein_chain,
        )
        ManifestStore(context.layout.root).register_artifact(
            "receptor:boltz_template_mmcif", "receptor_mmcif", converted
        )

        def recorded_path(path: Path) -> str:
            resolved = path.resolve()
            if resolved.is_relative_to(context.layout.root.resolve()):
                return resolved.relative_to(context.layout.root.resolve()).as_posix()
            return str(resolved)

        _write(
            context.layout.state / "boltz_template_conversion.json",
            {
                "source": recorded_path(template),
                "output": recorded_path(converted),
                "implementation": "gemmi-boltz-2.2.1-windows-compatibility",
                "coordinate_validation": asdict(validation),
            },
        )
        return converted

    def _boltz_template(self, context: PipelineContext) -> Path:
        cached = context.data.get("receptor_template")
        if isinstance(cached, Path) and cached.is_file():
            template = cached
        elif context.config.target.receptor_template_ref:
            template = self._ref(context, context.config.target.receptor_template_ref)
        else:
            generated = context.layout.root / "receptor" / "boltz_template.pdb"
            if generated.is_file():
                template = generated
            else:
                receptor = self._ref(context, context.config.target.receptor_ref)
                if receptor.suffix.lower() not in {".pdb", ".ent", ".cif", ".mmcif"}:
                    raise ValueError(
                        "Boltz receptor template is unavailable; PREPARE_RECEPTOR must run first"
                    )
                template = receptor
        normalized = self._normalize_boltz_template(context, template)
        context.data["receptor_template"] = normalized
        return normalized

    def ingest_project(self, context: PipelineContext) -> StageOutcome:
        for source in context.config.ligands:
            self._ref(context, source.source_ref)
        self._ref(context, context.config.target.receptor_ref)
        if context.config.reporting.source_workbook_ref:
            self._ref(context, context.config.reporting.source_workbook_ref)
        return StageOutcome(message="project references validated", completed=1, total=1)

    def prepare_receptor(self, context: PipelineContext) -> StageOutcome:
        receptor = self._ref(context, context.config.target.receptor_ref)
        context.data["receptor"] = receptor
        if context.config.target.receptor_pdbqt_ref:
            context.data["receptor_pdbqt"] = self._ref(context, context.config.target.receptor_pdbqt_ref)
        if context.config.target.receptor_template_ref:
            context.data["receptor_template"] = self._ref(context, context.config.target.receptor_template_ref)
        coordinate_validation = None
        if context.config.boltz.constrained.enabled or context.config.boltz.unconstrained.enabled:
            vina_receptor = self._ref(
                context,
                context.config.target.receptor_pdbqt_ref or context.config.target.receptor_ref,
            )
            if context.config.target.receptor_template_ref:
                template = self._ref(context, context.config.target.receptor_template_ref)
                coordinate_validation = validate_coordinates(vina_receptor, template, tolerance_angstrom=0.001)
            elif context.config.target.preparation.method == "meeko":
                template = context.layout.root / "receptor" / "boltz_template.pdb"
                coordinate_validation = convert_pdbqt_to_pdb(vina_receptor, template)
                ManifestStore(context.layout.root).register_artifact(
                    "receptor:boltz_template", "receptor_pdb", template
                )
            else:
                receptor_source = self._ref(context, context.config.target.receptor_ref)
                if receptor_source.suffix.lower() in {".pdb", ".ent", ".cif", ".mmcif"}:
                    template = receptor_source
                    coordinate_validation = validate_coordinates(vina_receptor, template, tolerance_angstrom=0.001)
                else:
                    template = context.layout.root / "receptor" / "boltz_template.pdb"
                    coordinate_validation = convert_pdbqt_to_pdb(vina_receptor, template)
                    ManifestStore(context.layout.root).register_artifact(
                        "receptor:boltz_template", "receptor_pdb", template
                    )
            context.data["receptor_template"] = template
            if not coordinate_validation.coordinate_identity_verified:
                raise ValueError(coordinate_validation.error or "Boltz receptor template moved Vina coordinates")
            template = self._normalize_boltz_template(context, template)
            context.data["receptor_template"] = template
        _write(context.layout.state / "receptor.json", {
            "receptor_ref": context.config.target.receptor_ref,
            "receptor_pdbqt_ref": context.config.target.receptor_pdbqt_ref,
            "receptor_template_ref": context.config.target.receptor_template_ref,
            "resolved_template": (
                template.relative_to(context.layout.root).as_posix()
                if coordinate_validation and template.resolve().is_relative_to(context.layout.root)
                else context.config.target.receptor_template_ref or context.config.target.receptor_ref
            ),
            "coordinate_validation": asdict(coordinate_validation) if coordinate_validation else None,
        })
        return StageOutcome(message="local receptor references resolved", completed=1, total=1)

    def _pocketminer_receptor(self, context: PipelineContext) -> Path:
        receptor = self._ref(context, context.config.target.receptor_ref)
        if receptor.suffix.lower() not in {".pdb", ".ent", ".cif", ".mmcif"}:
            raise ValueError("PocketMiner requires the original protein structure in PDB or mmCIF format")
        return receptor

    @staticmethod
    def _ranked_candidates(context: PipelineContext) -> list[CandidatePocket]:
        payload = read_json(context.layout.root / "pocketminer" / "candidates" / "ranked_pockets.json", {})
        return [CandidatePocket.model_validate(item) for item in payload.get("candidates", [])]

    def run_pocketminer(self, context: PipelineContext) -> StageOutcome:
        if context.config.pocket.mode != "pocketminer":
            return StageOutcome(StageStatus.SKIPPED, "PocketMiner mode is not active")
        receptor = self._pocketminer_receptor(context)
        raw = context.layout.root / "pocketminer" / "raw" / "predictions.npy"
        result = run_official(
            context.config.pocketminer.runtime,
            receptor=receptor,
            output_npy=raw,
            executor=self.executor,
            cancellation=context.cancellation,
            timeout_seconds=context.config.execution.command_timeout_seconds,
        )
        if not result.successful:
            raise RuntimeError(f"official PocketMiner inference failed: {(result.stderr or result.stdout).strip()[-1000:]}")
        report = inspect_installation(context.config.pocketminer.runtime)
        from drug_discovery_agent.project.hashing import sha256_file
        dependencies = report.get("dependencies") or {}
        metadata = PocketMinerRunMetadata(
            implementation=report["implementation"],
            repository_url=context.config.pocketminer.runtime.repository_url,
            commit=str(report["commit"]),
            python_version=str(dependencies.get("python", "unknown")),
            tensorflow_version=dependencies.get("tensorflow"),
            mdtraj_version=dependencies.get("mdtraj"),
            checkpoint_prefix=str(report["checkpoint_prefix"]),
            checkpoint_files=report["checkpoint_sha256"],
            raw_prediction_sha256=sha256_file(raw),
            receptor_sha256=sha256_file(receptor),
            command=result.command,
        )
        _write(context.layout.root / "pocketminer" / "raw" / "run_metadata.json", metadata)
        provenance = read_json(context.layout.provenance, {})
        _write(context.layout.provenance, {**provenance, "pocketminer": report})
        return StageOutcome(message="official PocketMiner residue propensities predicted", completed=1, total=1)

    def parse_pocketminer_scores(self, context: PipelineContext) -> StageOutcome:
        if context.config.pocket.mode not in {"pocketminer", "manual"}:
            return StageOutcome(StageStatus.SKIPPED, "pocket selection mode is not active")
        receptor = self._pocketminer_receptor(context)
        if context.config.pocket.mode == "pocketminer":
            scores = parse_native_predictions(
                context.layout.root / "pocketminer" / "raw" / "predictions.npy", receptor,
            )
            scores = attach_representatives(scores, receptor)
            smoothing = context.config.pocketminer.smoothing
            if smoothing.enabled:
                scores = smooth_scores(
                    scores, neighbor_count=smoothing.neighbor_count,
                    radius_angstrom=smoothing.radius_angstrom,
                )
        else:
            scores = []
        score_dir = context.layout.root / "pocketminer" / "scores"
        write_normalized_scores(scores, score_dir / "residue_scores.json", score_dir / "residue_scores.csv")
        write_probability_pdb(
            receptor, scores,
            context.layout.root / "pocketminer" / "visualization" / "receptor_pocketminer_scores.pdb",
        )
        return StageOutcome(message=f"normalized {len(scores)} residue probabilities", completed=len(scores), total=len(scores))

    def detect_candidate_pockets(self, context: PipelineContext) -> StageOutcome:
        if context.config.pocket.mode not in {"pocketminer", "manual"}:
            return StageOutcome(StageStatus.SKIPPED, "pocket selection mode is not active")
        receptor = self._pocketminer_receptor(context)
        scores = parse_normalized_scores(context.layout.root / "pocketminer" / "scores" / "residue_scores.json")
        clustering = context.config.pocketminer.clustering
        components = spatial_components(
            scores,
            threshold=clustering.score_threshold,
            edge_distance_angstrom=clustering.edge_distance_angstrom,
            minimum_residues=clustering.minimum_residues,
            hotspot_radius_angstrom=clustering.hotspot_radius_angstrom,
            maximum_core_residues=clustering.maximum_core_residues,
        )
        box_config = context.config.pocketminer.box
        boxes = [build_box(
            residues, receptor,
            padding_angstrom=box_config.padding_angstrom,
            minimum_size=box_config.minimum_size,
            maximum_size=box_config.maximum_size,
        ) for residues in components]
        temporary = rank_components(
            components, boxes=boxes,
            weights={"mean_score": 1.0, "max_score": 0.0, "residue_count": 0.0, "compactness": 0.0},
            count_saturation=context.config.pocketminer.ranking.count_saturation,
            compactness_scale_angstrom=context.config.pocketminer.ranking.compactness_scale_angstrom,
        )
        detected = []
        for index, item in enumerate(temporary, 1):
            metrics = item.metrics.model_copy(update={"ranking_score": 0.0, "ranking_contributions": {}})
            detected.append(item.model_copy(update={"pocket_id": f"detected_{index}", "rank": None, "metrics": metrics}))
        _write(context.layout.root / "pocketminer" / "candidates" / "detected_pockets.json", {
            "schema_version": 1,
            "method": "spatial_graph_hotspot_core_representative_coordinate",
            "parameters": clustering.model_dump(mode="json"),
            "candidates": [item.model_dump(mode="json") for item in detected],
        })
        return StageOutcome(message=f"detected {len(detected)} spatial candidate pockets", completed=len(detected), total=len(detected), candidate_count=len(detected))

    def rank_candidate_pockets(self, context: PipelineContext) -> StageOutcome:
        if context.config.pocket.mode not in {"pocketminer", "manual"}:
            return StageOutcome(StageStatus.SKIPPED, "pocket selection mode is not active")
        payload = read_json(context.layout.root / "pocketminer" / "candidates" / "detected_pockets.json", {})
        detected = [CandidatePocket.model_validate(item) for item in payload.get("candidates", [])]
        ranking = context.config.pocketminer.ranking
        ranked = rank_components(
            [item.residues for item in detected],
            boxes=[(item.center, item.size, item.bounds, item.atom_extent_bounds) for item in detected],
            weights=ranking.weights,
            count_saturation=ranking.count_saturation,
            compactness_scale_angstrom=ranking.compactness_scale_angstrom,
        )
        _write(context.layout.root / "pocketminer" / "candidates" / "ranked_pockets.json", {
            "schema_version": 1,
            "ranking": ranking.model_dump(mode="json"),
            "candidate_count": len(ranked),
            "max_displayed_candidates": context.config.pocketminer.max_displayed_candidates,
            "candidates": [item.model_dump(mode="json") for item in ranked],
        })
        return StageOutcome(message=f"ranked {len(ranked)} candidate pockets", completed=len(ranked), total=len(ranked), candidate_count=len(ranked))

    def await_pocket_selection(self, context: PipelineContext) -> StageOutcome:
        if context.config.pocket.mode not in {"pocketminer", "manual"}:
            return StageOutcome(StageStatus.SKIPPED, "interactive pocket selection is not active")
        candidates = self._ranked_candidates(context)
        selection = load_valid_selection(
            context.layout.state / "selected_pocket.json",
            candidates=candidates,
            receptor=self._pocketminer_receptor(context),
            pocketminer_config=context.config.pocketminer.model_dump(mode="json"),
        )
        if selection is None:
            return StageOutcome(
                StageStatus.AWAITING_USER_SELECTION,
                "candidate pockets are ready; explicit user confirmation is required",
                total=len(candidates), candidate_count=len(candidates),
            )
        context.data["selected_pocket"] = selection
        return StageOutcome(message=f"user selected {selection.pocket_id}", completed=1, total=1, candidate_count=len(candidates))

    def confirm_selected_pocket(self, context: PipelineContext) -> StageOutcome:
        if context.config.pocket.mode not in {"pocketminer", "manual"}:
            return StageOutcome(StageStatus.SKIPPED, "interactive pocket selection is not active")
        candidates = self._ranked_candidates(context)
        selection = load_valid_selection(
            context.layout.state / "selected_pocket.json",
            candidates=candidates,
            receptor=self._pocketminer_receptor(context),
            pocketminer_config=context.config.pocketminer.model_dump(mode="json"),
        )
        if selection is None:
            raise ValueError("selected pocket is missing or stale for the current receptor/configuration")
        if not selection.residues and context.config.boltz.constrained.enabled:
            raise ValueError("selected box contains no protein residues for constrained Boltz")
        context.data["selected_pocket"] = selection
        return StageOutcome(message=f"confirmed {selection.pocket_id} for downstream execution", completed=1, total=1)

    def define_pocket(self, context: PipelineContext) -> StageOutcome:
        config = context.config.pocket
        if config.mode == "none":
            _write(context.layout.state / "residue_mapping.json", [])
            return StageOutcome(StageStatus.SKIPPED, "workflow does not define a pocket")
        receptor_coordinates = self._ref(
            context,
            context.config.target.receptor_pdbqt_ref or context.config.target.receptor_ref,
        )
        residues = config.residues
        selected_pocket = None
        if config.mode in {"pocketminer", "manual"}:
            from drug_discovery_agent.pocketminer.models import PocketDefinition
            selected_pocket = PocketDefinition.model_validate(
                read_json(context.layout.state / "selected_pocket.json")
            )
            from drug_discovery_agent.config.models import PocketResidue
            residues = [PocketResidue(**item.residue.model_dump()) for item in selected_pocket.residues]
        selections = []
        if config.mode == "derive_from_vina_box":
            assert config.center is not None and config.vina_size is not None
            selections = select_pocket_residues(
                receptor_coordinates, center=config.center, size=config.vina_size,
                search_radius=config.contact_search_radius,
                maximum_residues=config.maximum_selected_residues,
            )
            residues = [item.residue for item in selections]
        if context.config.boltz.constrained.enabled:
            if not context.config.target.protein_sequence:
                raise ValueError("protein sequence is required for constrained residue mapping")
            mappings = map_pocket_residues(
                receptor_coordinates,
                context.config.target.protein_sequence,
                residues,
                protein_chain=context.config.target.protein_chain,
            )
        else:
            mappings = []
        payload = {
            "selected_pocket": selected_pocket.model_dump(mode="json") if selected_pocket else None,
            "selection": [
                {
                    **item.residue.model_dump(mode="json"),
                    "minimum_distance_to_center_angstrom": item.minimum_distance_to_center_angstrom,
                    "heavy_atoms_inside_vina_box": item.heavy_atoms_inside_vina_box,
                }
                for item in selections
            ],
            "mapping": [item.as_dict() for item in mappings],
        }
        _write(context.layout.state / "residue_mapping.json", payload)
        context.data["residue_mapping"] = mappings
        return StageOutcome(message=f"validated {len(mappings)} mapped pocket residues", completed=len(mappings), total=len(mappings))

    @staticmethod
    def _active_pocket_box(context: PipelineContext) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        if context.config.pocket.mode in {"pocketminer", "manual"}:
            from drug_discovery_agent.pocketminer.models import PocketDefinition
            selected = PocketDefinition.model_validate(read_json(context.layout.state / "selected_pocket.json"))
            return selected.final_center, selected.final_size
        center, size = context.config.pocket.center, context.config.pocket.vina_size
        if center is None or size is None:
            raise ValueError("active Vina pocket has no center and size")
        return center, size

    def ingest_ligands(self, context: PipelineContext) -> StageOutcome:
        sources = [(source, self._ref(context, source.source_ref)) for source in context.config.ligands]
        result = ingest_ligands(sources, context.layout.root / "ligands" / "source")
        manifest_store = ManifestStore(context.layout.root)
        manifest = manifest_store.load()
        manifest.ligands = result.records
        manifest_store.save(manifest)
        _write(context.layout.state / "ligand_ingestion.json", {
            "records": [record.model_dump(mode="json") for record in result.records],
            "output_files": {
                ligand_id: path.relative_to(context.layout.root).as_posix()
                for ligand_id, path in result.output_files.items()
            },
        })
        return _aggregate([record.status for record in result.records])

    def prepare_ligands(self, context: PipelineContext) -> StageOutcome:
        manifest_store = ManifestStore(context.layout.root)
        manifest = manifest_store.load()
        results = []
        tasks = []
        task_info = {}
        for ligand in manifest.ligands:
            if ligand.status == "FAILED":
                results.append(PreparedLigand(ligand_id=ligand.ligand_id, status="SKIPPED", error=ligand.error))
                continue
            source = context.layout.root / "ligands" / "source" / f"{ligand.legacy_name}.sdf"
            output_sdf = context.layout.root / "ligands" / "prepared_sdf" / f"{ligand.legacy_name}.sdf"
            output_pdbqt = context.layout.root / "ligands" / "prepared_pdbqt" / f"{ligand.legacy_name}.pdbqt"
            item_hash = stage_input_hash(
                [source],
                config={"random_seed": context.config.execution.conformer_random_seed},
                implementation="ligand-preparation-0.1.0",
                tool_versions=self._tool_versions(context, "rdkit", "meeko"),
            )
            existing = context.run_state.stages[StageName.PREPARE_LIGANDS].items.get(ligand.ligand_id)
            if context.state_store.reusable_item(existing, item_hash):
                results.append(PreparedLigand(ligand_id=ligand.ligand_id, status="SKIPPED",
                                              prepared_sdf=output_sdf, prepared_pdbqt=output_pdbqt))
                continue
            tasks.append((ligand.ligand_id, source, output_sdf, output_pdbqt))
            task_info[ligand.ligand_id] = (ligand, output_sdf, output_pdbqt, item_hash)

        def execute(task):
            ligand_id, source, output_sdf, output_pdbqt = task
            return prepare_ligand(
                ligand_id, source, output_sdf, output_pdbqt,
                executor=self.executor, cancellation=context.cancellation,
                random_seed=context.config.execution.conformer_random_seed,
                timeout_seconds=context.config.execution.command_timeout_seconds,
            )

        executed = BoundedScheduler(context.config.execution.ligand_workers).map(execute, tasks)
        results.extend(executed)
        for result in executed:
            ligand, output_sdf, output_pdbqt, item_hash = task_info[result.ligand_id]
            ligand.status, ligand.error = result.status, result.error
            ligand.modifications = result.modifications
            if result.status == "SUCCESS":
                ligand.prepared_sdf_id = f"prepared_sdf:{ligand.ligand_id}"
                ligand.prepared_pdbqt_id = f"prepared_pdbqt:{ligand.ligand_id}"
            outputs = (
                [output_sdf.relative_to(context.layout.root).as_posix(),
                 output_pdbqt.relative_to(context.layout.root).as_posix()]
                if result.status == "SUCCESS" else []
            )
            context.state_store.record_item(
                context.run_state,
                StageName.PREPARE_LIGANDS,
                ItemState(input_identifier=ligand.ligand_id, status=ItemStatus(result.status),
                          input_hash=item_hash, outputs=outputs, error=result.error),
            )
            if result.status == "FAILED":
                self._record_failure(context, StageName.PREPARE_LIGANDS, ligand.ligand_id,
                                     result.error or "ligand preparation failed", result.command)
        manifest_store.save(manifest)
        for result in executed:
            if result.status == "SUCCESS" and result.prepared_sdf and result.prepared_pdbqt:
                manifest_store.register_artifact(f"prepared_sdf:{result.ligand_id}", "prepared_sdf", result.prepared_sdf)
                manifest_store.register_artifact(f"prepared_pdbqt:{result.ligand_id}", "prepared_pdbqt", result.prepared_pdbqt)
        _write(context.layout.state / "ligand_preparation.json", [item.model_dump(mode="json") for item in results])
        return _aggregate([item.status for item in results])

    def run_vina_stage(self, context: PipelineContext) -> StageOutcome:
        if not context.config.vina.enabled:
            return StageOutcome(StageStatus.SKIPPED, "Vina disabled")
        receptor = self._ref(
            context,
            context.config.target.receptor_pdbqt_ref or context.config.target.receptor_ref,
        )
        if receptor.suffix.lower() != ".pdbqt":
            raise ValueError("Vina requires a receptor PDBQT local reference")
        manifest = ManifestStore(context.layout.root).load()
        profile = context.config.vina.active_profile
        center, size = self._active_pocket_box(context)
        results = []
        tasks = []
        task_info = {}
        for ligand in manifest.ligands:
            if ligand.status != "SUCCESS" or not ligand.prepared_pdbqt_id:
                continue
            prepared = context.layout.root / "ligands" / "prepared_pdbqt" / f"{ligand.legacy_name}.pdbqt"
            output = context.layout.root / "vina" / "docked" / f"{ligand.legacy_name}_out.pdbqt"
            item_hash = stage_input_hash(
                [receptor, prepared], config={
                    "center": center, "size": size,
                    "profile": profile.model_dump(mode="json"), "seed": context.config.vina.seed,
                }, implementation="vina-0.1.0",
                tool_versions=self._tool_versions(context, "vina"),
            )
            existing = context.run_state.stages[StageName.RUN_VINA].items.get(ligand.ligand_id)
            if context.state_store.reusable_item(existing, item_hash):
                result = VinaResult(ligand_id=ligand.ligand_id, status="SKIPPED", output_pdbqt=output)
                results.append(result)
            else:
                tasks.append((ligand.ligand_id, prepared, output))
                task_info[ligand.ligand_id] = (output, item_hash)

        def execute(task):
            ligand_id, prepared, output = task
            return run_vina(
                ligand_id, receptor_pdbqt=receptor, ligand_pdbqt=prepared,
                output_pdbqt=output, center=center,
                size=size, exhaustiveness=profile.exhaustiveness,
                num_modes=profile.num_modes, seed=context.config.vina.seed,
                executor=self.executor, cancellation=context.cancellation,
                timeout_seconds=context.config.execution.command_timeout_seconds,
            )

        executed = BoundedScheduler(context.config.execution.vina_workers).map(execute, tasks)
        results.extend(executed)
        for result in executed:
            output, item_hash = task_info[result.ligand_id]
            outputs = [output.relative_to(context.layout.root).as_posix()] if result.status == "SUCCESS" else []
            context.state_store.record_item(
                context.run_state, StageName.RUN_VINA,
                ItemState(input_identifier=result.ligand_id, status=ItemStatus(result.status),
                          input_hash=item_hash, outputs=outputs, error=result.error),
            )
            if result.status == "FAILED":
                self._record_failure(context, StageName.RUN_VINA, result.ligand_id,
                                     result.error or "Vina failed", result.command)
        _write(context.layout.state / "vina_results.json", [item.model_dump(mode="json") for item in results])
        manifest_store = ManifestStore(context.layout.root)
        for result in executed:
            if result.status == "SUCCESS" and result.output_pdbqt:
                manifest_store.register_artifact(f"vina_pose:{result.ligand_id}", "vina_pdbqt", result.output_pdbqt)
        return _aggregate([item.status for item in results])

    def qc_vina(self, context: PipelineContext) -> StageOutcome:
        manifest = ManifestStore(context.layout.root).load()
        rows, statuses = [], []
        for ligand in manifest.ligands:
            output = context.layout.root / "vina" / "docked" / f"{ligand.legacy_name}_out.pdbqt"
            if not output.exists():
                continue
            poses = parse_vina_poses(output, ligand.legacy_name)
            status = "SUCCESS" if poses and all(pose.atoms for pose in poses) else "NEEDS_REVIEW"
            statuses.append(status)
            rows.append({"ligand_id": ligand.ligand_id, "legacy_name": ligand.legacy_name,
                         "status": status, "mode_count": len(poses),
                         "affinities": [pose.affinity for pose in poses]})
        _write(context.layout.state / "vina_qc.json", rows)
        return _aggregate(statuses)

    def shortlist(self, context: PipelineContext) -> StageOutcome:
        raw = read_json(context.layout.state / "vina_results.json", [])
        results = [VinaResult.model_validate(item) for item in raw if item.get("status") != "SKIPPED"]
        # Resumed skipped items get their scores directly from the persisted PDBQT remarks.
        known = {item.ligand_id for item in results}
        manifest = ManifestStore(context.layout.root).load()
        for ligand in manifest.ligands:
            if ligand.ligand_id in known:
                continue
            path = context.layout.root / "vina" / "docked" / f"{ligand.legacy_name}_out.pdbqt"
            if path.exists():
                results.append(VinaResult(
                    ligand_id=ligand.ligand_id,
                    status="SUCCESS",
                    output_pdbqt=path,
                ))
        enriched = []
        for result in results:
            poses = (
                parse_vina_poses(result.output_pdbqt, result.ligand_id)
                if result.output_pdbqt and Path(result.output_pdbqt).is_file()
                else []
            )
            parsed_modes = [
                VinaMode(
                    mode=pose.mode,
                    affinity_kcal_mol=pose.affinity,
                    rmsd_lb=pose.rmsd_lb,
                    rmsd_ub=pose.rmsd_ub,
                )
                for pose in poses
                if pose.affinity is not None and pose.rmsd_lb is not None and pose.rmsd_ub is not None
            ]
            enriched.append(result.model_copy(update={
                "best_affinity_kcal_mol": (
                    result.best_affinity_kcal_mol
                    if result.best_affinity_kcal_mol is not None
                    else (parsed_modes[0].affinity_kcal_mol if parsed_modes else None)
                ),
                "modes": result.modes or parsed_modes,
                "heavy_atom_count": len(poses[0].heavy_atoms) if poses and poses[0].heavy_atoms else None,
            }))
        metric = context.config.analysis.vina_selection_metric
        selected = shortlist_vina(enriched, context.config.analysis.vina_shortlist, metric)
        selected_ids = {item.ligand_id for item in selected}
        ranked = [
            item.model_copy(update={"selected_for_downstream": item.ligand_id in selected_ids})
            for item in rank_vina_results(enriched, metric)
        ]
        _write(context.layout.state / "vina_ranking.json", [item.model_dump(mode="json") for item in ranked])
        _write(context.layout.state / "vina_shortlist.json", [item.model_dump(mode="json") for item in selected])
        if not selected:
            return StageOutcome(
                StageStatus.NEEDS_REVIEW,
                "no scored Vina ligands were available for shortlisting",
                total=len(results),
            )
        metric_label = {
            "best_affinity": "best Vina affinity",
            "mean_affinity": "mean Vina affinity",
            "ligand_efficiency": "Vina ligand efficiency",
        }[metric]
        return StageOutcome(
            completed=len(selected),
            total=len(results),
            message=(
                f"selected top {len(selected)} of {len(ranked)} scored Vina ligands by {metric_label}; "
                "only this subset advances downstream"
            ),
        )

    def _mappings(self, context: PipelineContext) -> list[ResidueMapping]:
        payload = read_json(context.layout.state / "residue_mapping.json", {})
        return [ResidueMapping(**item) for item in payload.get("mapping", [])]

    def _prepare_boltz(self, context: PipelineContext, constrained: bool) -> StageOutcome:
        config = context.config.boltz
        condition = config.constrained if constrained else config.unconstrained
        if not condition.enabled:
            return StageOutcome(StageStatus.SKIPPED, "Boltz condition disabled")
        template = self._boltz_template(context)
        manifest = ManifestStore(context.layout.root).load()
        by_id = {item.ligand_id: item for item in manifest.ligands}
        shortlist = read_json(context.layout.state / "vina_shortlist.json", [])
        directory = context.layout.root / ("boltz_constrained" if constrained else "boltz_unconstrained") / "inputs"
        mappings = self._mappings(context) if constrained else []
        statuses = []
        input_manifest = []
        mode = "vina_site_constrained" if constrained else "unconstrained"
        stage_name = (
            StageName.PREPARE_BOLTZ_CONSTRAINED
            if constrained else StageName.PREPARE_BOLTZ_UNCONSTRAINED
        )
        for selected in shortlist:
            ligand = by_id[selected["ligand_id"]]
            source_path = context.layout.root / "ligands" / "source" / f"{ligand.legacy_name}.sdf"
            if not ligand.canonical_smiles:
                error = "canonical SMILES is unavailable; Boltz input was not generated"
                item_hash = stage_input_hash(
                    [source_path, template], config={"mode": mode},
                    implementation=f"boltz-input-{mode}-0.1.1",
                )
                input_manifest.append({
                    "ligand_id": ligand.ligand_id, "legacy_name": ligand.legacy_name,
                    "input_file": None, "status": "NEEDS_REVIEW", "error": error,
                })
                context.state_store.record_item(
                    context.run_state, stage_name,
                    ItemState(input_identifier=ligand.ligand_id, status=ItemStatus.NEEDS_REVIEW,
                              input_hash=item_hash, error=error),
                )
                statuses.append("NEEDS_REVIEW")
                continue
            common = dict(
                protein_sequence=context.config.target.protein_sequence or "",
                ligand_smiles=ligand.canonical_smiles, receptor_template=template,
                template_chain=context.config.target.protein_chain,
                protein_id=config.protein_id, ligand_id=config.ligand_id,
            )
            if constrained:
                document = build_constrained_input(
                    **common, mapped_pocket_residues=mappings,
                    template_force=config.template_force, template_threshold=config.template_threshold,
                    pocket_force=config.pocket_force, pocket_max_distance=config.pocket_max_distance,
                )
            else:
                document = build_unconstrained_input(**common)
            input_path = directory / f"{ligand.legacy_name}.yaml"
            write_boltz_input(document, input_path)
            input_manifest.append({"ligand_id": ligand.ligand_id, "legacy_name": ligand.legacy_name,
                                   "input_file": input_path.name, "status": "SUCCESS"})
            item_hash = stage_input_hash(
                [input_path, template], config={"mode": mode},
                implementation=f"boltz-input-{mode}-0.1.1",
            )
            context.state_store.record_item(
                context.run_state, stage_name,
                ItemState(
                    input_identifier=ligand.ligand_id, status=ItemStatus.SUCCESS,
                    input_hash=item_hash,
                    outputs=[input_path.relative_to(context.layout.root).as_posix()],
                ),
            )
            statuses.append("SUCCESS")
        _write(context.layout.state / f"boltz_{mode}_inputs.json", input_manifest)
        return _aggregate(statuses)

    def prepare_boltz_constrained(self, context: PipelineContext) -> StageOutcome:
        return self._prepare_boltz(context, True)

    def prepare_boltz_unconstrained(self, context: PipelineContext) -> StageOutcome:
        return self._prepare_boltz(context, False)

    def _run_boltz(self, context: PipelineContext, mode: str) -> StageOutcome:
        stage_name = (
            StageName.RUN_BOLTZ_CONSTRAINED
            if mode == "vina_site_constrained"
            else StageName.RUN_BOLTZ_UNCONSTRAINED
        )
        base = context.layout.root / ("boltz_constrained" if mode == "vina_site_constrained" else "boltz_unconstrained")
        results, statuses = [], []
        results_path = context.layout.state / f"boltz_{mode}_results.json"
        previous_results = {
            item["ligand_id"]: item
            for item in read_json(results_path, [])
            if isinstance(item, dict) and item.get("ligand_id")
        }
        input_manifest = {
            item["input_file"]: item
            for item in read_json(context.layout.state / f"boltz_{mode}_inputs.json", [])
            if isinstance(item, dict) and item.get("input_file")
        }
        template = self._boltz_template(context)
        tasks = []
        for input_name, identity in sorted(input_manifest.items()):
            input_path = base / "inputs" / input_name
            item_hash = stage_input_hash(
                [input_path, template],
                config=context.config.boltz.model_dump(mode="json"),
                implementation=f"boltz-{mode}-0.1.2",
                tool_versions=self._tool_versions(context, "boltz"),
            )
            existing = context.run_state.stages[stage_name].items.get(identity["ligand_id"])
            previous = previous_results.get(identity["ligand_id"])
            if previous and context.state_store.reusable_item(existing, item_hash):
                results.append(previous)
                statuses.append("SKIPPED")
                continue
            attempt_root = base / "results" / input_path.stem / item_hash[:12]
            prior_attempts = sorted(attempt_root.glob("attempt_*")) if attempt_root.exists() else []
            output = attempt_root / f"attempt_{len(prior_attempts) + 1:04d}"
            tasks.append((input_path, output, identity, item_hash))

        def execute(task):
            input_path, output, identity, item_hash = task
            command = run_boltz(input_path, output, context.config.boltz, executor=self.executor,
                                cancellation=context.cancellation,
                                timeout_seconds=context.config.execution.command_timeout_seconds)
            execution_error = boltz_execution_error(command)
            if execution_error:
                return identity, command, None, item_hash, execution_error
            affinity = next(iter(output.rglob("affinity_*.json")), None)
            prediction_dir = affinity.parent if affinity else output
            try:
                prediction = parse_prediction_directory(
                    prediction_dir, ligand_id=identity["ligand_id"], mode=mode
                )
            except (OSError, ValueError) as exc:
                return identity, command, None, item_hash, f"Boltz result parsing failed: {exc}"
            return identity, command, prediction, item_hash, None

        executed = BoundedScheduler(context.config.execution.boltz_workers).map(execute, tasks)
        manifest_store = ManifestStore(context.layout.root)
        for identity, command, prediction, item_hash, execution_error in executed:
            if prediction is None:
                results.append({"ligand_id": identity["ligand_id"], "legacy_name": identity["legacy_name"],
                                "mode": mode, "status": "FAILED", "error": execution_error,
                                "command": command.model_dump(mode="json")})
                statuses.append("FAILED")
                context.state_store.record_item(
                    context.run_state, stage_name,
                    ItemState(input_identifier=identity["ligand_id"], status=ItemStatus.FAILED,
                              input_hash=item_hash, error=execution_error),
                )
                self._record_failure(context, stage_name,
                                     identity["ligand_id"], execution_error or "Boltz failed", command)
                continue

            output_paths = []
            for raw_path in [prediction.affinity_json, *(
                value
                for model in prediction.models
                for value in (model.structure, model.confidence_json)
            )]:
                if not raw_path:
                    continue
                path = Path(raw_path).resolve()
                if path.is_relative_to(context.layout.root):
                    output_paths.append(path.relative_to(context.layout.root).as_posix())
            status = "SUCCESS" if prediction.models else "NEEDS_REVIEW"
            error = None if prediction.models else "Boltz completed without parseable model structures"
            results.append({**prediction.model_dump(mode="json"), "legacy_name": identity["legacy_name"],
                            "status": status, **({"error": error} if error else {})})
            statuses.append(status)
            context.state_store.record_item(
                context.run_state, stage_name,
                ItemState(input_identifier=identity["ligand_id"], status=ItemStatus(status),
                          input_hash=item_hash, outputs=output_paths, error=error),
            )
            for model in prediction.models:
                structure = Path(model.structure)
                if structure.resolve().is_relative_to(context.layout.root):
                    manifest_store.register_artifact(
                        f"boltz:{mode}:{identity['ligand_id']}:model_{model.model_index}",
                        "boltz_structure",
                        structure,
                    )
        _write(results_path, results)
        return _aggregate(statuses)

    def run_boltz_constrained(self, context: PipelineContext) -> StageOutcome:
        return self._run_boltz(context, "vina_site_constrained")

    def run_boltz_unconstrained(self, context: PipelineContext) -> StageOutcome:
        return self._run_boltz(context, "unconstrained")

    def qc_boltz(self, context: PipelineContext) -> StageOutcome:
        rows, statuses = [], []
        for mode in ("vina_site_constrained", "unconstrained"):
            for item in read_json(context.layout.state / f"boltz_{mode}_results.json", []):
                model_count = len(item.get("models", []))
                status = "SUCCESS" if item.get("status") == "SUCCESS" and model_count else "NEEDS_REVIEW"
                rows.append({"ligand_id": item.get("ligand_id"), "mode": mode, "status": status,
                             "model_count": model_count})
                statuses.append(status)
        _write(context.layout.state / "boltz_qc.json", rows)
        return _aggregate(statuses)

    def analyze_vina(self, context: PipelineContext) -> StageOutcome:
        receptor_path = self._ref(context, context.config.target.receptor_pdbqt_ref or context.config.target.receptor_ref)
        if receptor_path.suffix.lower() != ".pdbqt":
            return StageOutcome(StageStatus.NEEDS_REVIEW, "Vina interaction analysis requires receptor PDBQT")
        receptor = parse_receptor_pdbqt(receptor_path)
        manifest = ManifestStore(context.layout.root).load()
        by_id = {item.ligand_id: item for item in manifest.ligands}
        results_path = context.layout.root / "interactions" / "vina" / "results.json"
        previous_results = {
            item["ligand_id"]: item
            for item in read_json(results_path, [])
            if isinstance(item, dict) and item.get("ligand_id")
        }
        rows, statuses = [], []
        for item in read_json(context.layout.state / "vina_shortlist.json", []):
            ligand = by_id[item["ligand_id"]]
            docked_path = context.layout.root / "vina" / "docked" / f"{ligand.legacy_name}_out.pdbqt"
            source_path = context.layout.root / "ligands" / "source" / f"{ligand.legacy_name}.sdf"
            structure_path = context.layout.root / "vina" / "structures" / f"{ligand.legacy_name}_vina_mode1.sdf"
            item_hash = stage_input_hash(
                [source_path, docked_path, receptor_path],
                config=context.config.analysis.thresholds.model_dump(mode="json"),
                implementation="vina-interaction-analysis-0.1.0",
                tool_versions=self._tool_versions(context, "rdkit"),
            )
            existing = context.run_state.stages[StageName.ANALYZE_VINA_POSES].items.get(ligand.ligand_id)
            previous = previous_results.get(ligand.ligand_id)
            if previous and context.state_store.reusable_item(existing, item_hash):
                rows.append(previous)
                statuses.append("SKIPPED")
                continue
            try:
                pose = mode1_pose(docked_path, ligand.legacy_name)
                reconstructed = reconstruct_ligand(source_path, pose)
                write_sdf(reconstructed.mol, structure_path)
                ManifestStore(context.layout.root).register_artifact(
                    f"vina_structure:{ligand.ligand_id}", "vina_sdf", structure_path
                )
                distances = residue_distances(pose, receptor,
                                              contact_cutoff=context.config.analysis.thresholds.contact_cutoff)
                interactions = analyze_interactions(reconstructed, receptor, context.config.analysis.thresholds)
                binding = binding_site_residues(reconstructed, receptor, interactions,
                                                cutoff=context.config.analysis.thresholds.binding_site_cutoff)
                status = "NEEDS_REVIEW" if reconstructed.bonds_over_2_2 else "SUCCESS"
                rows.append({"ligand_id": ligand.ligand_id, "legacy_name": ligand.legacy_name, "status": status,
                             "mapping": {"method": reconstructed.mapping_method,
                                         "median_bond_length_angstrom": reconstructed.median_bond_length,
                                         "max_bond_length_angstrom": reconstructed.max_bond_length,
                                         "bonds_over_2_2_angstrom": reconstructed.bonds_over_2_2},
                             "distances": [asdict(distance) for distance in distances],
                             "interactions": interactions, "binding_site_residues": binding})
            except Exception as exc:
                status = "FAILED"
                rows.append({"ligand_id": ligand.ligand_id, "legacy_name": ligand.legacy_name,
                             "status": status, "error": str(exc)})
                self._record_failure(
                    context, StageName.ANALYZE_VINA_POSES, ligand.ligand_id, str(exc)
                )
            outputs = (
                [structure_path.relative_to(context.layout.root).as_posix()]
                if structure_path.is_file() else []
            )
            context.state_store.record_item(
                context.run_state,
                StageName.ANALYZE_VINA_POSES,
                ItemState(
                    input_identifier=ligand.ligand_id,
                    status=ItemStatus(status),
                    input_hash=item_hash,
                    outputs=outputs,
                    error=rows[-1].get("error"),
                ),
            )
            statuses.append(status)
        _write(results_path, rows)
        return _aggregate(statuses)

    def analyze_boltz(self, context: PipelineContext) -> StageOutcome:
        results_path = context.layout.root / "interactions" / "boltz" / "results.json"
        previous_results = {
            f"{item['ligand_id']}:model_{item['model_index']}": item
            for item in read_json(results_path, [])
            if isinstance(item, dict) and item.get("ligand_id") is not None
            and item.get("model_index") is not None
        }
        jobs, results, statuses = [], [], []
        job_hashes = {}
        selected_ids = {
            item["ligand_id"]
            for item in read_json(context.layout.state / "vina_shortlist.json", [])
        }
        for mode in ("vina_site_constrained", "unconstrained"):
            for item in read_json(context.layout.state / f"boltz_{mode}_results.json", []):
                if item.get("status") != "SUCCESS" or item.get("ligand_id") not in selected_ids:
                    continue
                for model in item.get("models", []):
                    job = PLIPJob(
                        ligand_id=f"{mode}:{item['ligand_id']}",
                        model_index=model["model_index"],
                        structure=Path(model["structure"]),
                        output_directory=context.layout.root / "interactions" / "boltz" / mode /
                        item["ligand_id"] / f"model_{model['model_index']}",
                    )
                    identifier = f"{job.ligand_id}:model_{job.model_index}"
                    item_hash = stage_input_hash(
                        [job.structure], config={"native_plip": True},
                        implementation="native-plip-analysis-0.1.1",
                        tool_versions=self._tool_versions(context, "plip"),
                    )
                    existing = context.run_state.stages[
                        StageName.ANALYZE_BOLTZ_INTERACTIONS
                    ].items.get(identifier)
                    previous = previous_results.get(identifier)
                    if previous and context.state_store.reusable_item(existing, item_hash):
                        results.append(PLIPResult.model_validate(previous))
                        statuses.append("SKIPPED")
                    else:
                        jobs.append(job)
                        job_hashes[identifier] = item_hash
        executed = run_plip_jobs(
            jobs, executor=self.executor, cancellation=context.cancellation,
            timeout_seconds=context.config.execution.command_timeout_seconds,
            max_workers=context.config.execution.plip_workers,
            environment=managed_plip_environment(),
        )
        results.extend(executed)
        for item in executed:
            identifier = f"{item.ligand_id}:model_{item.model_index}"
            outputs = (
                [item.report_xml.resolve().relative_to(context.layout.root).as_posix()]
                if item.report_xml and item.report_xml.resolve().is_relative_to(context.layout.root)
                else []
            )
            context.state_store.record_item(
                context.run_state,
                StageName.ANALYZE_BOLTZ_INTERACTIONS,
                ItemState(
                    input_identifier=identifier,
                    status=ItemStatus(item.status),
                    input_hash=job_hashes[identifier],
                    outputs=outputs,
                    error=item.error,
                ),
            )
            if item.status == "FAILED":
                self._record_failure(context, StageName.ANALYZE_BOLTZ_INTERACTIONS,
                                     identifier,
                                     item.error or "PLIP failed", item.command)
            statuses.append(item.status)
        _write(results_path, [item.model_dump(mode="json") for item in results])
        return _aggregate(statuses)

    def compare(self, context: PipelineContext) -> StageOutcome:
        # Ligand atom correspondence between Vina chemistry and native Boltz
        # structures is not established by the available legacy corpus.
        rows = []
        for item in read_json(context.layout.state / "boltz_qc.json", []):
            rows.append({"ligand_id": item["ligand_id"], "mode": item["mode"], "status": "not_comparable",
                         "reason": "validated protein and ligand atom correspondence is unavailable; no RMSD reported"})
        _write(context.layout.root / "comparison" / "pose_comparisons.json", rows)
        return StageOutcome(StageStatus.SUCCESS, "non-comparable cases retained with reasons",
                            completed=len(rows), total=len(rows))

    def rank(self, context: PipelineContext) -> StageOutcome:
        rows = []
        for item in read_json(context.layout.state / "vina_ranking.json", []):
            rows.append({
                "ligand_id": item["ligand_id"],
                "vina_affinity": item.get("best_affinity_kcal_mol"),
                "vina_mean_affinity": item.get("mean_affinity_kcal_mol"),
                "vina_ligand_efficiency": item.get("ligand_efficiency_kcal_mol_per_heavy_atom"),
                "vina_selection_metric": item.get("selection_metric"),
                "vina_selection_value": item.get("selection_value"),
                "vina_rank": item.get("selection_rank"),
                "selected_for_downstream": item.get("selected_for_downstream", False),
            })
        by_id = {row["ligand_id"]: row for row in rows}
        for mode in ("vina_site_constrained", "unconstrained"):
            for item in read_json(context.layout.state / f"boltz_{mode}_results.json", []):
                row = by_id.setdefault(item["ligand_id"], {"ligand_id": item["ligand_id"]})
                row[f"{mode}_affinity"] = item.get("affinity_pred_value")
                confidences = [model.get("confidence_score") for model in item.get("models", [])
                               if model.get("confidence_score") is not None]
                row[f"{mode}_confidence"] = max(confidences) if confidences else None
        if context.config.ranking.policy == "weighted_consensus":
            specs = []
            for name, weight in context.config.ranking.weights.items():
                direction = "lower" if name == "vina_affinity" else "higher"
                specs.append(MetricSpec(name, direction, weight))
            ranked = rank_weighted_consensus(rows, specs)
        else:
            ranked = sorted(rows, key=lambda row: (
                row.get("vina_rank") is None,
                row.get("vina_rank") or float("inf"),
                row["ligand_id"],
            ))
        _write(context.layout.root / "comparison" / "ranking.json", ranked)
        return StageOutcome(completed=len(ranked), total=len(ranked))

    def report(self, context: PipelineContext) -> StageOutcome:
        rows = read_json(context.layout.root / "comparison" / "ranking.json", [])
        outputs = build_report(rows, context.layout.root / "reports",
                               title=context.config.project.display_name or context.config.project.id)
        if context.config.reporting.source_workbook_ref:
            workbook = append_analysis_workbook(
                self._ref(context, context.config.reporting.source_workbook_ref),
                context.layout.root / "reports" / context.config.reporting.output_workbook_name,
                read_json(context.layout.root / "interactions" / "vina" / "results.json", []),
            )
            outputs["workbook"] = workbook
        manifest_store = ManifestStore(context.layout.root)
        for kind, path in outputs.items():
            manifest_store.register_artifact(f"report:{kind}", f"report_{kind}", path)
        _write(context.layout.root / "reports" / "manifest.json",
               {key: path.relative_to(context.layout.root).as_posix() for key, path in outputs.items()})
        return StageOutcome(completed=len(rows), total=len(rows), message="local reports built")


def make_handlers(command_directory: str | Path | None = None) -> dict[StageName, Callable[[PipelineContext], StageOutcome]]:
    return LocalStageHandlers(command_directory).handlers()
