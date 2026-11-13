"""Small offline checks for a frozen companion's required runtime/resources."""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import platform
from pathlib import Path

from drug_discovery_agent.platform_support import architecture


def verify_pocketminer_resources(root: Path | None = None) -> dict[str, str]:
    package = Path(__file__).resolve().parent
    root = root or package / "_vendor" / "pocketminer"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest["commit"] != "187062df3c94127e991669768009141a08fd5d8b":
        raise RuntimeError("Unexpected bundled PocketMiner revision")
    if not manifest.get("files"):
        raise RuntimeError("Empty PocketMiner integrity manifest")
    for relative, expected in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise RuntimeError(f"Missing or invalid PocketMiner resource: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"PocketMiner integrity failure: {relative}")
    if not (package / "pocketminer" / "_official_adapter.py").is_file():
        raise RuntimeError("Missing external PocketMiner adapter source")
    return manifest["files"]


def self_check() -> dict[str, object]:
    resources = verify_pocketminer_resources()
    versions = {}
    for name in ("pydantic", "yaml", "numpy", "scipy", "rdkit", "gemmi", "meeko", "openpyxl", "fastapi", "uvicorn", "multipart"):
        importlib.import_module(name)
        distribution = {"yaml": "PyYAML", "multipart": "python-multipart"}.get(name, name)
        versions[name] = importlib.metadata.version(distribution)
    from rdkit import Chem
    from scipy.spatial import cKDTree
    import gemmi
    assert Chem.MolFromSmiles("CCO").GetNumAtoms() == 3
    assert cKDTree([[0, 0, 0]]).query([0, 0, 0])[0] == 0
    assert gemmi.Structure() is not None
    return {"ok": True, "system": platform.system(), "architecture": architecture(),
            "python": platform.python_version(), "versions": versions, "pocketminer_sha256": resources}
