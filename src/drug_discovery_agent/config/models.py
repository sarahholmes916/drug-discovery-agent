from __future__ import annotations

from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator


Vector3 = tuple[float, float, float]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class WorkflowName(StrEnum):
    VINA_ONLY = "vina_only"
    VINA_TO_CONSTRAINED_BOLTZ = "vina_to_constrained_boltz"
    VINA_TO_UNCONSTRAINED_BOLTZ = "vina_to_unconstrained_boltz"
    VINA_TO_BOTH_BOLTZ = "vina_to_both_boltz"
    FULL = "full"
    CUSTOM = "custom"


class ProjectInfo(StrictModel):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")]
    display_name: str | None = None
    guidance_notes: list[str] = Field(default_factory=list)


class ReceptorPreparationConfig(StrictModel):
    method: Literal["meeko", "provided_pdbqt"] = "provided_pdbqt"
    remove_waters: bool = True
    heterogens: Literal["review", "remove", "keep"] = "review"
    alternate_locations: Literal["review", "use_a"] = "review"
    charge_model: Literal["gasteiger"] = "gasteiger"
    custom_instructions: str | None = None


class TargetConfig(StrictModel):
    receptor_ref: str
    receptor_pdbqt_ref: str | None = None
    receptor_template_ref: str | None = None
    protein_sequence: str | None = None
    protein_chain: str = "A"
    preparation: ReceptorPreparationConfig = Field(default_factory=ReceptorPreparationConfig)

    @model_validator(mode="after")
    def normalize_sequence(self) -> "TargetConfig":
        if self.protein_sequence is not None:
            sequence = "".join(self.protein_sequence.split()).upper()
            if not sequence or any(letter not in "ACDEFGHIKLMNPQRSTVWYX" for letter in sequence):
                raise ValueError("protein_sequence must contain one-letter amino-acid codes")
            object.__setattr__(self, "protein_sequence", sequence)
        return self


class PocketResidue(StrictModel):
    chain: str
    residue_number: int
    residue_name: str
    insertion_code: str = ""
    sequence_position: PositiveInt | None = None


class PocketConfig(StrictModel):
    mode: Literal["explicit", "imported", "derive_from_vina_box", "pocketminer", "manual", "none"] = "none"
    center: Vector3 | None = None
    vina_size: Vector3 | None = None
    residues: list[PocketResidue] = Field(default_factory=list)
    contact_search_radius: float = Field(default=8.0, gt=0)
    maximum_selected_residues: PositiveInt = 12

    @model_validator(mode="after")
    def validate_box(self) -> "PocketConfig":
        if (self.center is None) != (self.vina_size is None):
            raise ValueError("pocket center and vina_size must be provided together")
        if self.vina_size is not None and any(value <= 0 for value in self.vina_size):
            raise ValueError("all Vina box dimensions must be positive")
        if self.center is not None and not all(isfinite(value) for value in (*self.center, *self.vina_size)):
            raise ValueError("pocket center and size must be finite")
        if self.mode == "explicit" and not (self.center and self.vina_size):
            raise ValueError("explicit pocket mode requires center and vina_size")
        return self


class PocketMinerSmoothingConfig(StrictModel):
    enabled: bool = True
    neighbor_count: PositiveInt = 10
    radius_angstrom: float = Field(default=10.0, gt=0)


class PocketMinerClusteringConfig(StrictModel):
    method: Literal["spatial_graph"] = "spatial_graph"
    score_threshold: float = Field(default=0.5, ge=0, le=1)
    edge_distance_angstrom: float = Field(default=8.0, gt=0)
    minimum_residues: PositiveInt = 2
    hotspot_radius_angstrom: float = Field(default=8.0, gt=0)
    maximum_core_residues: PositiveInt = 12

    @model_validator(mode="after")
    def core_can_meet_minimum(self) -> "PocketMinerClusteringConfig":
        if self.maximum_core_residues < self.minimum_residues:
            raise ValueError("maximum_core_residues must be at least minimum_residues")
        return self


class PocketMinerRankingConfig(StrictModel):
    method: Literal["weighted_interpretable"] = "weighted_interpretable"
    weights: dict[str, float] = Field(default_factory=lambda: {
        "mean_score": 0.40,
        "max_score": 0.20,
        "residue_count": 0.20,
        "compactness": 0.20,
    })
    count_saturation: PositiveInt = 12
    compactness_scale_angstrom: float = Field(default=8.0, gt=0)

    @model_validator(mode="after")
    def exact_weights(self) -> "PocketMinerRankingConfig":
        expected = {"mean_score", "max_score", "residue_count", "compactness"}
        if set(self.weights) != expected:
            raise ValueError(f"PocketMiner ranking weights must contain exactly {sorted(expected)}")
        if any(value < 0 for value in self.weights.values()) or sum(self.weights.values()) <= 0:
            raise ValueError("PocketMiner ranking weights must be non-negative with a positive sum")
        return self


class PocketMinerBoxConfig(StrictModel):
    method: Literal["score_weighted_centroid_heavy_atom_extent"] = "score_weighted_centroid_heavy_atom_extent"
    padding_angstrom: float = Field(default=7.0, ge=0)
    minimum_size: Vector3 = (18.0, 18.0, 18.0)
    maximum_size: Vector3 = (40.0, 40.0, 40.0)

    @model_validator(mode="after")
    def size_limits(self) -> "PocketMinerBoxConfig":
        if not all(isfinite(value) for value in (*self.minimum_size, *self.maximum_size)):
            raise ValueError("PocketMiner box limits must be finite")
        if any(low <= 0 or high < low for low, high in zip(self.minimum_size, self.maximum_size, strict=True)):
            raise ValueError("PocketMiner box limits must be positive and max >= min on every axis")
        return self


class PocketMinerRuntimeConfig(StrictModel):
    implementation: Literal["Mickdub/gvp:pocket_pred"] = "Mickdub/gvp:pocket_pred"
    repository_url: str = "https://github.com/Mickdub/gvp.git"
    commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")] = "187062df3c94127e991669768009141a08fd5d8b"
    checkpoint_prefix: str = "models/pocketminer"
    installation_root: str | None = None
    python_executable: str | None = None


class PocketMinerConfig(StrictModel):
    smoothing: PocketMinerSmoothingConfig = Field(default_factory=PocketMinerSmoothingConfig)
    clustering: PocketMinerClusteringConfig = Field(default_factory=PocketMinerClusteringConfig)
    ranking: PocketMinerRankingConfig = Field(default_factory=PocketMinerRankingConfig)
    box: PocketMinerBoxConfig = Field(default_factory=PocketMinerBoxConfig)
    max_displayed_candidates: PositiveInt = 5
    runtime: PocketMinerRuntimeConfig = Field(default_factory=PocketMinerRuntimeConfig)


class VinaProfile(StrictModel):
    exhaustiveness: PositiveInt
    num_modes: PositiveInt


class VinaConfig(StrictModel):
    enabled: bool = False
    profile: str = "full"
    profiles: dict[str, VinaProfile] = Field(
        default_factory=lambda: {
            "fast": VinaProfile(exhaustiveness=4, num_modes=1),
            "full": VinaProfile(exhaustiveness=8, num_modes=3),
        }
    )
    seed: int | None = None

    @model_validator(mode="after")
    def selected_profile_exists(self) -> "VinaConfig":
        if self.profile not in self.profiles:
            raise ValueError(f"unknown Vina profile: {self.profile}")
        return self

    @property
    def active_profile(self) -> VinaProfile:
        return self.profiles[self.profile]


class BoltzCondition(StrictModel):
    enabled: bool = False


class BoltzConfig(StrictModel):
    constrained: BoltzCondition = Field(default_factory=BoltzCondition)
    unconstrained: BoltzCondition = Field(default_factory=BoltzCondition)
    protein_id: str = "A"
    ligand_id: str = "L"
    template_force: bool = True
    template_threshold: float = Field(default=2.0, gt=0)
    pocket_force: bool = True
    pocket_max_distance: float = Field(default=6.0, gt=0)
    recycling_steps: PositiveInt = 3
    sampling_steps: PositiveInt = 200
    diffusion_samples: PositiveInt = 5
    output_format: Literal["pdb", "cif"] = "pdb"
    accelerator: str = "gpu"
    devices: str = "1"
    use_potentials: bool = True
    use_msa_server: bool = True
    override: bool = True


class InteractionThresholds(StrictModel):
    contact_cutoff: float = Field(default=4.0, gt=0)
    binding_site_cutoff: float = Field(default=7.5, gt=0)
    hydrophobic_distance: float = Field(default=4.0, gt=0)
    hbond_distance: float = Field(default=4.1, gt=0)
    hbond_donor_angle_min: float = Field(default=100.0, ge=0, le=180)
    salt_bridge_distance: float = Field(default=5.5, gt=0)
    pi_stack_distance: float = Field(default=5.5, gt=0)
    pi_stack_angle_deviation: float = Field(default=30.0, ge=0, le=90)
    pi_stack_offset: float = Field(default=2.0, gt=0)
    pi_cation_distance: float = Field(default=6.0, gt=0)
    pi_cation_offset: float = Field(default=2.0, gt=0)
    halogen_distance: float = Field(default=4.0, gt=0)
    halogen_donor_angle_min: float = Field(default=135.0, ge=0, le=180)
    halogen_acceptor_angle_min: float = Field(default=90.0, ge=0, le=180)
    halogen_acceptor_angle_max: float = Field(default=150.0, ge=0, le=180)

    @model_validator(mode="after")
    def angle_range(self) -> "InteractionThresholds":
        if self.halogen_acceptor_angle_min > self.halogen_acceptor_angle_max:
            raise ValueError("halogen acceptor angle minimum cannot exceed maximum")
        return self


class AnalysisConfig(StrictModel):
    vina_shortlist: Annotated[int, Field(ge=1, le=50)] = 50
    vina_selection_metric: Literal[
        "best_affinity", "mean_affinity", "ligand_efficiency"
    ] = "best_affinity"
    # Accepted for compatibility with older saved projects. The single Vina
    # shortlist now governs every downstream stage, including Boltz PLIP.
    boltz_plip_shortlist: PositiveInt | None = Field(default=None, exclude=True)
    alignment_mode: Literal["whole_protein", "pocket"] = "pocket"
    thresholds: InteractionThresholds = Field(default_factory=InteractionThresholds)


class RankingConfig(StrictModel):
    policy: Literal["none", "weighted_consensus"] = "none"
    weights: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_weights(self) -> "RankingConfig":
        if self.policy == "weighted_consensus" and not self.weights:
            raise ValueError("weighted_consensus requires explicit weights")
        if any(not isinstance(value, (int, float)) or value < 0 for value in self.weights.values()):
            raise ValueError("ranking weights must be non-negative numbers")
        if self.weights and sum(self.weights.values()) <= 0:
            raise ValueError("at least one ranking weight must be positive")
        return self


class ReportingConfig(StrictModel):
    source_workbook_ref: str | None = None
    output_workbook_name: Annotated[
        str, Field(pattern=r"^[^/\\]{1,120}\.xlsx$")
    ] = "drug_discovery_results.xlsx"


class ExecutionConfig(StrictModel):
    ligand_workers: PositiveInt = 1
    vina_workers: PositiveInt = 1
    boltz_workers: PositiveInt = 1
    plip_workers: PositiveInt = 1
    command_timeout_seconds: float | None = Field(default=None, gt=0)
    conformer_random_seed: int = 42
    retry_failed: bool = True


class ControlPlaneConfig(StrictModel):
    enabled: bool = False
    endpoint: str | None = None
    machine_id: str | None = None
    poll_interval_seconds: float = Field(default=5.0, ge=1.0)
    allowed_browser_origins: list[str] = Field(default_factory=list)


class LigandSourceConfig(StrictModel):
    source_ref: str
    kind: Literal["multi_sdf", "sdf_directory"]


class ProjectConfig(StrictModel):
    project: ProjectInfo
    workflow: WorkflowName = WorkflowName.VINA_ONLY
    custom_stages: list[str] = Field(default_factory=list)
    target: TargetConfig
    pocket: PocketConfig = Field(default_factory=PocketConfig)
    pocketminer: PocketMinerConfig = Field(default_factory=PocketMinerConfig)
    ligands: list[LigandSourceConfig]
    vina: VinaConfig = Field(default_factory=VinaConfig)
    boltz: BoltzConfig = Field(default_factory=BoltzConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    ranking: RankingConfig = Field(default_factory=RankingConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    control_plane: ControlPlaneConfig = Field(default_factory=ControlPlaneConfig)

    @model_validator(mode="after")
    def scientific_requirements(self) -> "ProjectConfig":
        boltz_enabled = self.boltz.constrained.enabled or self.boltz.unconstrained.enabled
        if self.workflow != WorkflowName.CUSTOM and not self.vina.enabled:
            raise ValueError(f"workflow {self.workflow.value} requires vina.enabled=true")
        if self.workflow in {
            WorkflowName.VINA_TO_CONSTRAINED_BOLTZ,
            WorkflowName.VINA_TO_BOTH_BOLTZ,
            WorkflowName.FULL,
        } and not self.boltz.constrained.enabled:
            raise ValueError(f"workflow {self.workflow.value} requires boltz.constrained.enabled=true")
        if self.workflow in {
            WorkflowName.VINA_TO_UNCONSTRAINED_BOLTZ,
            WorkflowName.VINA_TO_BOTH_BOLTZ,
            WorkflowName.FULL,
        } and not self.boltz.unconstrained.enabled:
            raise ValueError(f"workflow {self.workflow.value} requires boltz.unconstrained.enabled=true")
        if self.vina.enabled and self.pocket.mode not in {"pocketminer", "manual"} and not (
            self.pocket.center and self.pocket.vina_size
        ):
            raise ValueError("Vina execution requires an explicit center and box size")
        if self.boltz.constrained.enabled and self.pocket.mode == "none":
            raise ValueError("constrained Boltz requires an active pocket definition")
        if boltz_enabled and not self.target.protein_sequence:
            raise ValueError("Boltz execution requires target.protein_sequence")
        if self.workflow == WorkflowName.CUSTOM and not self.custom_stages:
            raise ValueError("custom workflow requires custom_stages")
        return self

    def scientific_projection(self) -> dict[str, Any]:
        """Configuration used for local scientific hashes and provenance."""
        return self.model_dump(exclude={"execution", "control_plane"}, mode="json")

    def execution_projection(self) -> dict[str, Any]:
        return self.execution.model_dump(mode="json")

    def cloud_projection(self) -> dict[str, Any]:
        """Construct an allowlisted control-plane payload with no raw science."""
        return {
            "project_id": self.project.id,
            "workflow": self.workflow.value,
            "stages": list(self.custom_stages) if self.workflow == WorkflowName.CUSTOM else [],
            "features": {
                "vina": self.vina.enabled,
                "pocketminer": self.pocket.mode == "pocketminer",
                "boltz_constrained": self.boltz.constrained.enabled,
                "boltz_unconstrained": self.boltz.unconstrained.enabled,
            },
            "execution": {
                "ligand_workers": self.execution.ligand_workers,
                "vina_workers": self.execution.vina_workers,
                "boltz_workers": self.execution.boltz_workers,
                "plip_workers": self.execution.plip_workers,
            },
        }


def load_project_config(path: str | Path) -> ProjectConfig:
    source = Path(path)
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"project config must be a YAML mapping: {source}")
    return ProjectConfig.model_validate(data)


def save_project_config(config: ProjectConfig, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(target)
