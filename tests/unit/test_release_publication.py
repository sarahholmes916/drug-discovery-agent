import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("publish_companion", Path(__file__).parents[2] / "scripts/publish_companion.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def artifacts(root):
    for target in publisher.TARGETS:
        directory = root / f"companion-{target}"
        directory.mkdir()
        suffix = ".tar.gz" if target.startswith("linux") else ".zip"
        archive = directory / f"DrugDiscoveryAgent-Companion-{target}{suffix}"
        archive.write_bytes(b"test archive")
        (directory / (archive.name + ".sha256")).write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n")
        (directory / "build-manifest.json").write_text(json.dumps({"target": target, "version": "0.1.1", "signed": True, "notarized": True}))
        (directory / "self-check.json").write_text(json.dumps({"ok": True, "architecture": target.rsplit("-", 1)[1]}))


def test_release_requires_every_platform_and_checksum(tmp_path):
    artifacts(tmp_path)
    assert len(publisher.validate_artifacts(tmp_path, "0.1.1", signed=True)) == 12
    next((tmp_path / "companion-macos-arm64").glob("*.zip")).write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        publisher.validate_artifacts(tmp_path, "0.1.1", signed=True)


def test_release_rejects_missing_or_mislabeled_platform(tmp_path):
    artifacts(tmp_path)
    path = tmp_path / "companion-macos-x64/self-check.json"
    path.write_text(json.dumps({"ok": True, "architecture": "arm64"}))
    with pytest.raises(ValueError, match="native"):
        publisher.validate_artifacts(tmp_path, "0.1.1", signed=True)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        publisher.validate_artifacts(tmp_path, "0.1.1", signed=True)


def test_stable_release_requires_notarization(tmp_path):
    artifacts(tmp_path)
    path = tmp_path / "companion-macos-arm64/build-manifest.json"
    data = json.loads(path.read_text())
    data["notarized"] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="notarization"):
        publisher.validate_artifacts(tmp_path, "0.1.1", signed=True)
