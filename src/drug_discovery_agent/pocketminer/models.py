from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Vector3 = tuple[float, float, float]


class PocketMinerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResidueIdentity(PocketMinerModel):
    chain: str
    residue_number: int
    insertion_code: str = ""
    residue_name: str

    @property
    def key(self) -> tuple[str, int, str, str]:
        return (self.chain, self.residue_number, self.insertion_code, self.residue_name)


class ResidueScore(PocketMinerModel):
    residue: ResidueIdentity
    score: float = Field(ge=0.0, le=1.0)
    smoothed_score: float | None = Field(default=None, ge=0.0, le=1.0)
    representative_coordinate: Vector3 | None = None
    representative_method: Literal["sidechain_heavy_centroid", "heavy_atom_centroid", "ca"] | None = None

    @property
    def active_score(self) -> float:
        return self.smoothed_score if self.smoothed_score is not None else self.score


class PocketBounds(PocketMinerModel):
    minimum: Vector3
    maximum: Vector3


class PocketMetrics(PocketMinerModel):
    mean_score: float = Field(ge=0.0, le=1.0)
    max_score: float = Field(ge=0.0, le=1.0)
    residue_count: int = Field(ge=1)
    compactness_angstrom: float = Field(ge=0.0)
    spatial_extent_angstrom: Vector3
    ranking_score: float = 0.0
    ranking_contributions: dict[str, float] = Field(default_factory=dict)


class CandidatePocket(PocketMinerModel):
    pocket_id: str
    rank: int | None = Field(default=None, ge=1)
    source: Literal["pocketminer"] = "pocketminer"
    residues: list[ResidueScore] = Field(min_length=1)
    metrics: PocketMetrics
    center: Vector3
    size: Vector3
    bounds: PocketBounds
    atom_extent_bounds: PocketBounds

    @model_validator(mode="after")
    def valid_geometry(self) -> "CandidatePocket":
        if not all(isfinite(value) for value in (*self.center, *self.size)) or any(value <= 0 for value in self.size):
            raise ValueError("candidate pocket center/size must be finite with positive dimensions")
        expected_min = tuple(self.center[axis] - self.size[axis] / 2 for axis in range(3))
        expected_max = tuple(self.center[axis] + self.size[axis] / 2 for axis in range(3))
        if any(abs(self.bounds.minimum[axis] - expected_min[axis]) > 1e-6 or abs(self.bounds.maximum[axis] - expected_max[axis]) > 1e-6 for axis in range(3)):
            raise ValueError("candidate pocket bounds do not match center/size")
        return self


class PocketDefinition(PocketMinerModel):
    schema_version: int = 1
    pocket_id: str
    source: Literal["pocketminer", "manual"]
    residues: list[ResidueScore] = Field(default_factory=list)
    metrics: PocketMetrics | None = None
    original_center: Vector3
    original_size: Vector3
    original_bounds: PocketBounds
    final_center: Vector3
    final_size: Vector3
    final_bounds: PocketBounds
    manual_box_edit: bool = False
    candidate_set_hash: str
    receptor_sha256: str
    pocketminer_config_hash: str
    selected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def positive_size(self) -> "PocketDefinition":
        values = (*self.original_center, *self.original_size, *self.final_center, *self.final_size)
        if not all(isfinite(value) for value in values):
            raise ValueError("pocket center and size must be finite")
        if any(value <= 0 for value in (*self.original_size, *self.final_size)):
            raise ValueError("pocket box dimensions must be positive")
        for center, size, bounds in (
            (self.original_center, self.original_size, self.original_bounds),
            (self.final_center, self.final_size, self.final_bounds),
        ):
            if any(
                abs(bounds.minimum[axis] - (center[axis] - size[axis] / 2)) > 1e-6
                or abs(bounds.maximum[axis] - (center[axis] + size[axis] / 2)) > 1e-6
                for axis in range(3)
            ):
                raise ValueError("pocket bounds do not match center/size")
        return self


class PocketSelectionRequest(PocketMinerModel):
    candidate_id: str | None = None
    center: Vector3 | None = None
    size: Vector3 | None = None
    residues: list[ResidueIdentity] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_selection(self) -> "PocketSelectionRequest":
        if (self.center is None) != (self.size is None):
            raise ValueError("manual center and size must be provided together")
        if self.size is not None and any(value <= 0 for value in self.size):
            raise ValueError("manual box dimensions must be positive")
        if self.center is not None and not all(isfinite(value) for value in (*self.center, *self.size)):
            raise ValueError("manual box center and dimensions must be finite")
        if self.candidate_id is None and self.center is None:
            raise ValueError("select a candidate or provide a custom manual box")
        return self


class PocketMinerRunMetadata(PocketMinerModel):
    implementation: Literal["Mickdub/gvp:pocket_pred"] = "Mickdub/gvp:pocket_pred"
    repository_url: str
    commit: str
    python_version: str
    tensorflow_version: str | None = None
    mdtraj_version: str | None = None
    checkpoint_prefix: str
    checkpoint_files: dict[str, str]
    raw_prediction_sha256: str
    receptor_sha256: str
    command: list[str]
