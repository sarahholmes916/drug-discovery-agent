"""Explicit release publication. Never update an existing release or move a tag."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TARGETS = ("windows-x64", "macos-arm64", "macos-x64", "linux-x64")


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def validate_artifacts(root: Path, version: str, *, signed: bool) -> list[Path]:
    artifacts = []
    for target in TARGETS:
        directory = root / f"companion-{target}"
        suffix = ".tar.gz" if target.startswith("linux") else ".zip"
        archive = directory / f"DrugDiscoveryAgent-Companion-{target}{suffix}"
        checksum = directory / (archive.name + ".sha256")
        expected, name = checksum.read_text().split()
        with archive.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if name != archive.name or expected != actual:
            raise ValueError(f"Invalid archive checksum: {target}")
        manifest = json.loads((directory / "build-manifest.json").read_text())
        if manifest["target"] != target or manifest["version"] != version:
            raise ValueError(f"Mislabeled artifact: {target}")
        if manifest.get("source_dirty") is True:
            raise ValueError(f"Release artifact was built from a modified working tree: {target}")
        if os.environ.get("RELEASE_SHA") and manifest.get("source_commit") != os.environ["RELEASE_SHA"]:
            raise ValueError(f"Release artifact has the wrong source commit: {target}")
        check = json.loads((directory / "self-check.json").read_text())
        if check.get("ok") is not True or check["architecture"] != target.rsplit("-", 1)[1]:
            raise ValueError(f"Failed native check: {target}")
        if signed and target.startswith("macos") and not (manifest["signed"] and manifest["notarized"]):
            raise ValueError(f"Missing signing/notarization: {target}")
        named_manifest = directory / f"build-manifest-{target}.json"
        shutil.copy2(directory / "build-manifest.json", named_manifest)
        artifacts.extend([archive, checksum, named_manifest])
    return artifacts


def main():
    tag = os.environ["RELEASE_TAG"]
    repository = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[\w.-]+)?", tag):
        raise ValueError("Expected an explicit version tag")
    prerelease = os.environ.get("PRERELEASE") == "true"
    signed = os.environ.get("SIGN_MACOS") == "true"
    if not prerelease and not signed:
        raise ValueError("Stable Mac releases require Developer ID signing and notarization")
    # List all pages successfully; auth/network errors fail closed, never imply absence.
    releases = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repository}/releases?per_page=100"))
    if any(item["tag_name"] == tag for page in releases for item in page):
        raise ValueError("A release (possibly a failed draft) already exists; inspect it and use a new tag")
    # Resolve annotated or lightweight tags to a commit using GitHub's commit endpoint.
    sha = json.loads(gh("api", f"repos/{repository}/commits/{tag}"))["sha"]
    ref = json.loads(gh("api", f"repos/{repository}/git/ref/tags/{tag}"))
    if ref["ref"] != f"refs/tags/{tag}":
        raise ValueError("Release tag does not exist")
    if sys.argv[1] == "preflight":
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write(f"sha={sha}\nversion={tag[1:]}\n")
        return
    if sha != os.environ["RELEASE_SHA"]:
        raise ValueError("Tag changed during builds; refusing to publish")
    artifacts = validate_artifacts(Path("release-artifacts"), tag[1:], signed=signed)
    notes = Path("release-artifacts/RELEASE_NOTES.md")
    notes.write_text(
        f"Native companion {tag}. Verify each archive against its adjacent SHA-256 file.\n\n"
        "Windows x64, macOS Apple Silicon, macOS Intel, Linux x64. Native resource/import, "
        "localhost startup and restart checks passed on the build runners. "
        "These checks do not establish full scientific execution on every platform.\n\n"
        + ("Mac apps are Developer ID signed and notarized.\n" if signed else
           "UNSIGNED DEVELOPMENT PRERELEASE: Mac Gatekeeper installation is not supported. Do not disable OS security protections.\n")
        + "\nBoltz 2.2.1 has no MPS support. Intel Mac automatic Boltz installation is unavailable. "
        "Apple Silicon CPU predictions are unverified. See docs/COMPANION_RELEASES.md.\n",
        encoding="utf-8",
    )
    command = ["release", "create", tag, "--repo", repository, "--verify-tag", "--draft", "--title", f"Companion {tag}", "--notes-file", str(notes)]
    if prerelease:
        command.append("--prerelease")
    gh(*command)
    # A failed upload leaves only a draft. No clobber and no release editing until
    # every required asset is confirmed. A retry cannot silently reuse that draft.
    gh("release", "upload", tag, "--repo", repository, *map(str, artifacts))
    uploaded = json.loads(gh("release", "view", tag, "--repo", repository, "--json", "assets"))["assets"]
    expected = {path.name: path.stat().st_size for path in artifacts}
    actual = {item["name"]: item["size"] for item in uploaded}
    if actual != expected:
        raise RuntimeError("Draft asset inventory is incomplete; refusing to publish")
    gh("release", "edit", tag, "--repo", repository, "--draft=false", "--latest=false")


if __name__ == "__main__":
    main()
