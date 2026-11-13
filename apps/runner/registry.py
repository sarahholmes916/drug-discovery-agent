from __future__ import annotations

import os
from pathlib import Path

from drug_discovery_agent.project.io import atomic_write_json, read_json
from drug_discovery_agent.platform_support import data_home


def runner_home() -> Path:
    return data_home()


class RunnerRegistry:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else runner_home() / "registry.json"

    def load(self) -> dict[str, object]:
        return read_json(self.path, {"schema_version": 1, "projects": {}, "runs": {}})

    def register_project(self, project_id: str, root: str | Path) -> None:
        data = self.load()
        data["projects"][project_id] = str(Path(root).resolve())
        atomic_write_json(self.path, data)

    def register_run(self, run_id: str, project_id: str, root: str | Path) -> None:
        data = self.load()
        data["projects"][project_id] = str(Path(root).resolve())
        data["runs"][run_id] = {"project_id": project_id, "project_root": str(Path(root).resolve())}
        atomic_write_json(self.path, data)

    def trusted_origins(self) -> list[str]:
        values = self.load().get("trusted_origins", [])
        return [value for value in values if isinstance(value, str)]

    def trust_origin(self, origin: str) -> None:
        data = self.load()
        origins = data.setdefault("trusted_origins", [])
        if origin not in origins:
            origins.append(origin)
            atomic_write_json(self.path, data)

    def run_root(self, run_id: str) -> Path:
        item = self.load().get("runs", {}).get(run_id)
        if not item:
            raise KeyError(f"unknown local run: {run_id}")
        return Path(item["project_root"])

    def project_root(self, project_id: str) -> Path:
        value = self.load().get("projects", {}).get(project_id)
        if not value:
            raise KeyError(f"unknown local project: {project_id}")
        return Path(value)
