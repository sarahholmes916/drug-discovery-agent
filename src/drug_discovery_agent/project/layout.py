from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from drug_discovery_agent.config.models import ProjectConfig, save_project_config

from .io import atomic_write_json


PROJECT_DIRECTORIES = (
    "inputs/receptor",
    "inputs/ligands",
    "receptor",
    "pocketminer/raw",
    "pocketminer/scores",
    "pocketminer/candidates",
    "pocketminer/visualization",
    "ligands/source",
    "ligands/prepared_sdf",
    "ligands/prepared_pdbqt",
    "vina/docked",
    "vina/structures",
    "boltz_constrained/inputs",
    "boltz_constrained/results",
    "boltz_unconstrained/inputs",
    "boltz_unconstrained/results",
    "interactions/vina",
    "interactions/boltz",
    "comparison",
    "reports",
    "state/commands",
    "state/logs",
)


@dataclass(frozen=True, slots=True)
class ProjectLayout:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "project.yaml"

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def manifest(self) -> Path:
        return self.state / "manifest.json"

    @property
    def run_state(self) -> Path:
        return self.state / "run.json"

    @property
    def provenance(self) -> Path:
        return self.state / "provenance.json"

    @property
    def local_references(self) -> Path:
        return self.state / "local_refs.json"

    def resolve_artifact(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        root = self.root.resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"artifact path escapes project root: {relative_path}")
        return candidate


def create_project(
    projects_root: str | Path,
    config: ProjectConfig,
    local_references: Mapping[str, str | Path],
) -> ProjectLayout:
    root = Path(projects_root).expanduser().resolve() / config.project.id
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"project already exists: {root}")
    for relative in PROJECT_DIRECTORIES:
        (root / relative).mkdir(parents=True, exist_ok=True)

    layout = ProjectLayout(root)
    save_project_config(config, layout.config)
    atomic_write_json(layout.state / "project.json", {"project_id": config.project.id, "schema_version": 1})
    atomic_write_json(layout.manifest, {"schema_version": 1, "artifacts": [], "ligands": []})
    atomic_write_json(
        layout.local_references,
        {
            "schema_version": 1,
            "references": {key: str(Path(value).expanduser().resolve()) for key, value in local_references.items()},
        },
    )
    return layout
