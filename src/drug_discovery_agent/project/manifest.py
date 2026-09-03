from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .hashing import sha256_file
from .io import atomic_write_json, read_json


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModificationRecord(ManifestModel):
    kind: str
    description: str
    changes_scientific_identity: bool = False
    before: str | None = None
    after: str | None = None


class ArtifactRecord(ManifestModel):
    artifact_id: str
    kind: str
    relative_path: str
    sha256: str
    size_bytes: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class LigandRecord(ManifestModel):
    ligand_id: str
    original_name: str | None
    legacy_name: str
    source_file_id: str
    source_record_index: int
    canonical_smiles: str | None = None
    prepared_sdf_id: str | None = None
    prepared_pdbqt_id: str | None = None
    status: str = "PENDING"
    error: str | None = None
    modifications: list[ModificationRecord] = Field(default_factory=list)


class ProjectManifest(ManifestModel):
    schema_version: int = 1
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    ligands: list[LigandRecord] = Field(default_factory=list)


class ManifestStore:
    def __init__(self, project_root: str | Path, path: str | Path | None = None) -> None:
        self.project_root = Path(project_root).resolve()
        self.path = Path(path) if path else self.project_root / "state" / "manifest.json"

    def load(self) -> ProjectManifest:
        return ProjectManifest.model_validate(read_json(self.path, {"schema_version": 1}))

    def save(self, manifest: ProjectManifest) -> None:
        atomic_write_json(self.path, manifest.model_dump(mode="json"))

    def register_artifact(
        self,
        artifact_id: str,
        kind: str,
        file_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        file_path = Path(file_path).resolve()
        if not file_path.is_relative_to(self.project_root):
            raise ValueError("manifest artifacts must remain inside the project root")
        record = ArtifactRecord(
            artifact_id=artifact_id,
            kind=kind,
            relative_path=file_path.relative_to(self.project_root).as_posix(),
            sha256=sha256_file(file_path),
            size_bytes=file_path.stat().st_size,
            metadata=metadata or {},
        )
        manifest = self.load()
        manifest.artifacts = [item for item in manifest.artifacts if item.artifact_id != artifact_id]
        manifest.artifacts.append(record)
        self.save(manifest)
        return record

