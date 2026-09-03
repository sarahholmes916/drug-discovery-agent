from __future__ import annotations

import json
import re
from typing import Any, Mapping


FORBIDDEN_KEY_PARTS = {
    "smiles", "sequence", "pdb", "pdbqt", "sdf", "structure", "ligand_name",
    "molecule", "local_path", "filesystem", "plip_report", "msa", "pae", "pde", "plddt",
}
WINDOWS_PATH = re.compile(r"(?:^|[\s\"'])[A-Za-z]:[\\/]")
UNIX_PATH = re.compile(r"(?:^|[\s\"'])/(?:Users|home|mnt|tmp|var|opt|data)/")


class PrivacyViolation(ValueError):
    pass


def _scan(value: Any, location: str = "$", *, sync_enabled: bool = False) -> None:
    if sync_enabled:
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                raise PrivacyViolation(f"cloud payload contains forbidden scientific field at {location}.{key}")
            _scan(child, f"{location}.{key}", sync_enabled=sync_enabled)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _scan(child, f"{location}[{index}]", sync_enabled=sync_enabled)
    elif isinstance(value, str) and (WINDOWS_PATH.search(value) or UNIX_PATH.search(value)):
        raise PrivacyViolation(f"cloud payload contains an absolute local path at {location}")


def validate_cloud_payload(payload: Mapping[str, Any], *, sync_enabled: bool = False) -> None:
    _scan(payload, sync_enabled=sync_enabled)
    json.dumps(payload)


def progress_payload(
    *,
    run_id: str,
    stage: str,
    status: str,
    completed: int,
    total: int,
    failed: int,
    candidate_count: int | None = None,
) -> dict[str, object]:
    payload = {
        "run_id": run_id,
        "stage": stage,
        "status": status,
        "completed": completed,
        "total": total,
        "failed": failed,
    }
    if candidate_count is not None:
        payload["candidate_count"] = candidate_count
    validate_cloud_payload(payload)
    return payload
