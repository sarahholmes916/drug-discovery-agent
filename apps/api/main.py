from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from drug_discovery_agent.privacy import PrivacyViolation, validate_cloud_payload
from drug_discovery_agent.project.state import StageName, StageStatus

from .storage import ControlPlaneStore


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


OpaqueId = str


class CapabilityValue(APIModel):
    available: bool
    version: str | None = Field(default=None, max_length=160)


class CapabilitySet(APIModel):
    tools: dict[str, CapabilityValue]


class SanitizedFeatures(APIModel):
    vina: bool = False
    boltz_constrained: bool = False
    boltz_unconstrained: bool = False
    plip: bool = False
    pose_comparison: bool = False
    pocketminer: bool = False


class SanitizedExecution(APIModel):
    ligand_workers: int = Field(default=1, ge=1, le=128)
    vina_workers: int = Field(default=1, ge=1, le=128)
    boltz_workers: int = Field(default=1, ge=1, le=16)
    plip_workers: int = Field(default=1, ge=1, le=128)


class SanitizedJobConfig(APIModel):
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
    workflow: str = Field(pattern=r"^(vina_only|vina_to_constrained_boltz|vina_to_unconstrained_boltz|vina_to_both_boltz|full|custom)$")
    stages: list[StageName] = Field(default_factory=list)
    features: SanitizedFeatures
    execution: SanitizedExecution = Field(default_factory=SanitizedExecution)


class Heartbeat(APIModel):
    machine_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
    status: Literal["CONNECTED", "BUSY", "OFFLINE"] = "CONNECTED"
    capabilities: CapabilitySet


class ProjectCreate(APIModel):
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
    display_name: str = Field(min_length=1, max_length=160)


class RunCreate(APIModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


class JobCreate(APIModel):
    job_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
    sanitized_config: SanitizedJobConfig


class Claim(APIModel):
    machine_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


class EventCreate(APIModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
    stage: StageName | Literal["pocket_selection"]
    status: StageStatus | Literal["awaiting_user_selection"]
    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    failed: int = Field(ge=0)
    candidate_count: int | None = Field(default=None, ge=0)
    message_code: str | None = Field(
        default=None,
        pattern=r"^(stage_started|stage_completed|stage_partial|stage_failed|cancellation_requested)$",
    )

    @model_validator(mode="after")
    def valid_counts(self) -> "EventCreate":
        if self.completed > self.total or self.failed > self.total:
            raise ValueError("completed and failed counts cannot exceed total")
        if self.completed + self.failed > self.total:
            raise ValueError("completed plus failed cannot exceed total")
        if self.status == "awaiting_user_selection" and self.stage != "pocket_selection":
            raise ValueError("awaiting_user_selection is valid only for pocket_selection")
        if self.stage == "pocket_selection" and self.status == "awaiting_user_selection" and self.candidate_count is None:
            raise ValueError("pocket selection wait events require candidate_count")
        return self


def create_app(
    *,
    database: str | Path,
    bearer_tokens: dict[str, str] | None = None,
    bearer_resolver: Callable[[str, str | None], str | None] | None = None,
):
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException
    except ImportError as exc:
        raise RuntimeError("FastAPI is required for the hosted API") from exc
    store = ControlPlaneStore(database)
    app = FastAPI(title="Drug Discovery Agent Control Plane")

    tokens = bearer_tokens or {}
    if not tokens and bearer_resolver is None:
        raise ValueError("the control plane requires at least one authentication method")

    def user(
        authorization: str = Header(default=""),
        origin: str | None = Header(default=None),
    ) -> str:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="bearer token required")
        supplied = authorization.removeprefix("Bearer ")
        for token, user_id in tokens.items():
            if hmac.compare_digest(supplied, token):
                return user_id
        if bearer_resolver is not None:
            user_id = bearer_resolver(supplied, origin)
            if user_id:
                return user_id
        raise HTTPException(status_code=401, detail="invalid token")

    @app.get("/health")
    def health():
        return {"status": "ok", "data_plane": False}

    @app.post("/runner/heartbeat")
    def heartbeat(payload: Heartbeat, user_id: str = Depends(user)):
        data = payload.model_dump(mode="json")
        validate_cloud_payload(data)
        try:
            store.heartbeat(machine_id=payload.machine_id, user_id=user_id, status=payload.status,
                            last_seen=datetime.now(UTC).isoformat(), capabilities=data["capabilities"])
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"accepted": True}

    @app.post("/projects")
    def create_project(payload: ProjectCreate, user_id: str = Depends(user)):
        validate_cloud_payload(payload.model_dump(mode="json"))
        try:
            store.create_project(payload.project_id, user_id, payload.display_name)
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return payload

    @app.post("/runs")
    def create_run(payload: RunCreate, user_id: str = Depends(user)):
        try:
            store.create_run(payload.run_id, payload.project_id, user_id, "PENDING", datetime.now(UTC).isoformat())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return payload

    @app.post("/jobs")
    def create_job(payload: JobCreate, user_id: str = Depends(user)):
        try:
            sanitized = payload.sanitized_config.model_dump(mode="json")
            validate_cloud_payload(sanitized)
        except PrivacyViolation as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            store.create_job(payload.job_id, payload.run_id, user_id, sanitized)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return payload

    @app.post("/runner/jobs/claim")
    def claim(payload: Claim, user_id: str = Depends(user)):
        return store.claim_job(payload.machine_id, user_id) or {}

    @app.post("/runner/jobs/{job_id}/events")
    def event(job_id: str, payload: EventCreate, user_id: str = Depends(user)):
        data = payload.model_dump(mode="json")
        validate_cloud_payload(data)
        try:
            store.add_event(
                (f"event_{uuid4().hex}", job_id, user_id, datetime.now(UTC).isoformat(),
                 payload.stage, payload.status, payload.completed, payload.total,
                 payload.failed, payload.message_code, payload.candidate_count),
                reported_run_id=payload.run_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"accepted": True}

    @app.get("/runner/jobs/{job_id}/state")
    def job_state(job_id: str, user_id: str = Depends(user)):
        state = store.job_state(job_id, user_id)
        if state is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {"job_id": job_id, "state": state}

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, user_id: str = Depends(user)):
        if not store.request_cancellation(job_id, user_id):
            raise HTTPException(status_code=409, detail="job cannot be cancelled")
        return {"job_id": job_id, "state": "CANCEL_REQUESTED"}

    @app.post("/jobs/{job_id}/resume")
    def resume_after_pocket_selection(job_id: str, user_id: str = Depends(user)):
        if not store.resume_after_selection(job_id, user_id):
            raise HTTPException(status_code=409, detail="job is not awaiting pocket selection")
        return {"job_id": job_id, "state": "PENDING"}

    @app.get("/runs/{run_id}")
    def get_run(run_id: str, user_id: str = Depends(user)):
        value = store.run_view(run_id, user_id)
        if value is None:
            raise HTTPException(status_code=404, detail="run not found")
        return value

    return app


_database = os.environ.get("DRUG_AGENT_API_DB", "control_plane.sqlite3")
_token = os.environ.get("DRUG_AGENT_API_TOKEN", "development-token-change-me")
app = create_app(database=_database, bearer_tokens={_token: "development-user"})
