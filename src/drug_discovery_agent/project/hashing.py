from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stage_input_hash(
    input_paths: Iterable[str | Path] = (),
    *,
    config: Any,
    implementation: str,
    tool_versions: dict[str, str | None] | None = None,
) -> str:
    payload = {
        "inputs": [
            {"name": Path(path).name, "sha256": sha256_file(path)}
            for path in sorted((Path(path) for path in input_paths), key=lambda p: p.as_posix())
        ],
        "config": config,
        "implementation": implementation,
        "tool_versions": tool_versions or {},
    }
    return stable_json_hash(payload)


def outputs_exist(project_root: str | Path, outputs: Iterable[str]) -> bool:
    root = Path(project_root).resolve()
    for output in outputs:
        candidate = (root / output).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return False
    return True

