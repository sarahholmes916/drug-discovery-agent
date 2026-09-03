from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .hashing import outputs_exist
from .io import atomic_write_json, read_json


class StageName(StrEnum):
    INGEST_PROJECT = "INGEST_PROJECT"
    PREPARE_RECEPTOR = "PREPARE_RECEPTOR"
    RUN_POCKETMINER = "RUN_POCKETMINER"
    PARSE_POCKETMINER_SCORES = "PARSE_POCKETMINER_SCORES"
    DETECT_CANDIDATE_POCKETS = "DETECT_CANDIDATE_POCKETS"
    RANK_CANDIDATE_POCKETS = "RANK_CANDIDATE_POCKETS"
    AWAIT_POCKET_SELECTION = "AWAIT_POCKET_SELECTION"
    CONFIRM_SELECTED_POCKET = "CONFIRM_SELECTED_POCKET"
    DEFINE_OR_IMPORT_POCKET = "DEFINE_OR_IMPORT_POCKET"
    INGEST_LIGANDS = "INGEST_LIGANDS"
    PREPARE_LIGANDS = "PREPARE_LIGANDS"
    RUN_VINA = "RUN_VINA"
    QC_VINA = "QC_VINA"
    SHORTLIST_VINA = "SHORTLIST_VINA"
    PREPARE_BOLTZ_CONSTRAINED = "PREPARE_BOLTZ_CONSTRAINED"
    PREPARE_BOLTZ_UNCONSTRAINED = "PREPARE_BOLTZ_UNCONSTRAINED"
    RUN_BOLTZ_CONSTRAINED = "RUN_BOLTZ_CONSTRAINED"
    RUN_BOLTZ_UNCONSTRAINED = "RUN_BOLTZ_UNCONSTRAINED"
    QC_BOLTZ = "QC_BOLTZ"
    ANALYZE_VINA_POSES = "ANALYZE_VINA_POSES"
    ANALYZE_BOLTZ_INTERACTIONS = "ANALYZE_BOLTZ_INTERACTIONS"
    ALIGN_AND_COMPARE_POSES = "ALIGN_AND_COMPARE_POSES"
    RANK_CONSENSUS = "RANK_CONSENSUS"
    BUILD_REPORT = "BUILD_REPORT"


class StageStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SKIPPED = "SKIPPED"
    AWAITING_USER_SELECTION = "AWAITING_USER_SELECTION"


class ItemStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


TERMINAL = {
    StageStatus.SUCCESS,
    StageStatus.FAILED,
    StageStatus.PARTIAL,
    StageStatus.CANCELLED,
    StageStatus.NEEDS_REVIEW,
    StageStatus.SKIPPED,
    StageStatus.AWAITING_USER_SELECTION,
}

ALLOWED_TRANSITIONS: dict[StageStatus, set[StageStatus]] = {
    StageStatus.PENDING: {StageStatus.READY, StageStatus.SKIPPED, StageStatus.CANCELLED},
    StageStatus.READY: {StageStatus.RUNNING, StageStatus.SKIPPED, StageStatus.CANCELLED},
    StageStatus.RUNNING: TERMINAL,
    StageStatus.SUCCESS: {StageStatus.READY},
    StageStatus.FAILED: {StageStatus.READY},
    StageStatus.PARTIAL: {StageStatus.READY},
    StageStatus.CANCELLED: {StageStatus.READY},
    StageStatus.NEEDS_REVIEW: {StageStatus.READY, StageStatus.SKIPPED},
    StageStatus.SKIPPED: {StageStatus.READY},
    StageStatus.AWAITING_USER_SELECTION: {StageStatus.READY, StageStatus.CANCELLED},
}


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FailureRecord(StateModel):
    stage: StageName
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    input_identifier: str
    error_message: str
    external_command: list[str] | None = None
    exit_code: int | None = None


class ItemState(StateModel):
    input_identifier: str
    status: ItemStatus
    input_hash: str
    outputs: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None
    command_record_id: str | None = None


class StageState(StateModel):
    name: StageName
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    ended_at: datetime | None = None
    input_hash: str | None = None
    items: dict[str, ItemState] = Field(default_factory=dict)
    message: str | None = None


class RunState(StateModel):
    schema_version: int = 1
    run_id: str
    project_id: str
    status: StageStatus = StageStatus.PENDING
    active_stage: StageName | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cancellation_requested: bool = False
    stages: dict[StageName, StageState] = Field(default_factory=dict)
    failures: list[FailureRecord] = Field(default_factory=list)


class StateStore:
    def __init__(self, path: str | Path, project_root: str | Path) -> None:
        self.path = Path(path)
        self.project_root = Path(project_root).resolve()

    def load(self) -> RunState:
        data = read_json(self.path)
        if data is None:
            raise FileNotFoundError(self.path)
        return RunState.model_validate(data)

    def save(self, state: RunState) -> None:
        state.updated_at = datetime.now(UTC)
        atomic_write_json(self.path, state.model_dump(mode="json"))

    def transition(
        self,
        state: RunState,
        stage_name: StageName,
        status: StageStatus,
        *,
        message: str | None = None,
        input_hash: str | None = None,
    ) -> StageState:
        stage = state.stages.setdefault(stage_name, StageState(name=stage_name))
        if status != stage.status and status not in ALLOWED_TRANSITIONS[stage.status]:
            raise ValueError(f"invalid stage transition {stage.status} -> {status} for {stage_name}")
        stage.status = status
        stage.message = message
        if input_hash is not None:
            stage.input_hash = input_hash
        now = datetime.now(UTC)
        if status == StageStatus.RUNNING:
            stage.started_at = now
            stage.ended_at = None
            state.active_stage = stage_name
            state.status = StageStatus.RUNNING
        elif status in TERMINAL:
            stage.ended_at = now
            if state.active_stage == stage_name:
                state.active_stage = None
        self.save(state)
        return stage

    def reusable_item(self, item: ItemState | None, expected_hash: str) -> bool:
        return bool(
            item
            and item.status == ItemStatus.SUCCESS
            and item.input_hash == expected_hash
            and outputs_exist(self.project_root, item.outputs)
        )

    def record_item(self, state: RunState, stage_name: StageName, item: ItemState) -> None:
        stage = state.stages.setdefault(stage_name, StageState(name=stage_name))
        stage.items[item.input_identifier] = item
        self.save(state)

    def request_cancellation(self, state: RunState) -> None:
        state.cancellation_requested = True
        self.save(state)

    def record_failure(self, state: RunState, failure: FailureRecord) -> None:
        state.failures.append(failure)
        self.save(state)
