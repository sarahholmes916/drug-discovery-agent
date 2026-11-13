"""Build only the host's native companion; never copy private workspace files."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from drug_discovery_agent.distribution import verify_pocketminer_resources
from drug_discovery_agent.platform_support import architecture

TARGETS = {("Windows", "x64"): "windows-x64", ("Darwin", "arm64"): "macos-arm64",
           ("Darwin", "x64"): "macos-x64", ("Linux", "x64"): "linux-x64"}


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def run(command, log: Path, **kwargs):
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps([str(x) for x in command]) + "\n")
    subprocess.run(command, check=True, **kwargs)


def package(stage: Path, archive: Path, system: str, log: Path):
    if system == "Darwin":
        run(["ditto", "-c", "-k", "--sequesterRsrc", str(stage), str(archive)], log)
    elif system == "Linux":
        with tarfile.open(archive, "w:gz") as output:
            for item in sorted(stage.iterdir()):
                output.add(item, arcname=item.name)
    else:
        shutil.make_archive(str(archive.with_suffix("")), "zip", stage)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=list(TARGETS.values()))
    parser.add_argument("--version")
    parser.add_argument("--notarize", action="store_true")
    args = parser.parse_args()
    system = platform.system()
    actual = TARGETS.get((system, architecture()))
    if actual != args.target:
        parser.error(f"Native {args.target} build requires that host/Python architecture; detected {actual}")
    if platform.python_version() != "3.12.10":
        parser.error("Release builds require Python 3.12.10")
    if args.notarize and (system != "Darwin" or not os.environ.get("MACOS_SIGNING_IDENTITY")):
        parser.error("Notarization requires macOS and a Developer ID Application signing identity")
    version = args.version or tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    for line in (ROOT / "packaging/requirements-build.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        name, expected = line.split("==")
        if importlib.metadata.version(name) != expected:
            parser.error(f"Install packaging/requirements-build.txt: {name} must be {expected}")
    resources = verify_pocketminer_resources()
    build = ROOT / "build"
    output = ROOT / "dist" / args.target
    build.mkdir(exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"companion-{args.target}-", dir=build))
    log = work / "build-commands.jsonl"
    env = {**os.environ, "COMPANION_VERSION": version,
           "COMPANION_NATIVE_ARCH": "arm64" if architecture() == "arm64" else "x86_64"}
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(work / "dist"),
         "--workpath", str(work / "work"), str(ROOT / "packaging/companion.spec")], log, cwd=ROOT, env=env)
    stage = work / "release"
    stage.mkdir()
    bundle = work / "dist" / "DrugDiscoveryAgent-Companion"
    if system == "Darwin":
        bundle = bundle.with_suffix(".app")
        shutil.copytree(bundle, stage / bundle.name, symlinks=True)
        executable = stage / bundle.name / "Contents/MacOS/DrugDiscoveryAgent-Companion"
    else:
        shutil.copytree(bundle, stage, dirs_exist_ok=True, symlinks=True)
        executable = stage / ("DrugDiscoveryAgent-Companion.exe" if system == "Windows" else "DrugDiscoveryAgent-Companion")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, stage / name)
    python_license = next((path for path in (
        Path(sys.base_prefix) / "LICENSE.txt", Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
        Path(sys.base_prefix) / "share/doc/python3.12/LICENSE.txt",
    ) if path.is_file()), None)
    if python_license is None:
        raise RuntimeError("Python redistribution license not found in this build environment")
    shutil.copy2(python_license, stage / "PYTHON_LICENSE.txt")
    if system != "Windows" and any(path.suffix.lower() in {".exe", ".dll"} for path in stage.rglob("*")):
        raise RuntimeError("Windows binaries found in a non-Windows bundle")
    shutil.copy2(ROOT / "packaging/COMPANION_README.txt", stage)
    shutil.copy2(ROOT / "src/drug_discovery_agent/_vendor/pocketminer/LICENSE", stage / "POCKETMINER_LICENSE.txt")
    licenses = stage / "dependency-licenses"
    inventory = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        inventory[name] = distribution.version
        for file in distribution.files or []:
            if any(word in file.name.lower() for word in ("license", "copying", "notice")):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    destination = licenses / name / str(file).replace("../", "")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    manifest = {"version": version, "target": actual, "python": platform.python_version(),
                "source_commit": source_commit, "source_dirty": source_dirty,
                "host": platform.platform(), "dependencies": dict(sorted(inventory.items())),
                "pocketminer_sha256": resources, "signed": bool(os.environ.get("MACOS_SIGNING_IDENTITY")),
                "notarized": args.notarize}
    (stage / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    run([str(executable), "--self-check", str(work / "self-check.json")], log, timeout=180)
    check = json.loads((work / "self-check.json").read_text())
    if not check["ok"] or check["architecture"] != architecture():
        raise RuntimeError("Frozen runtime verification failed")
    suffix = ".tar.gz" if system == "Linux" else ".zip"
    archive = output / f"DrugDiscoveryAgent-Companion-{actual}{suffix}"
    package(stage, archive, system, log)
    if args.notarize:
        run(["xcrun", "notarytool", "submit", str(archive), "--key", os.environ["APPLE_API_KEY_PATH"],
             "--key-id", os.environ["APPLE_API_KEY_ID"], "--issuer", os.environ["APPLE_API_ISSUER"], "--wait"], log)
        run(["xcrun", "stapler", "staple", str(stage / bundle.name)], log)
        run(["codesign", "--verify", "--deep", "--strict", str(stage / bundle.name)], log)
        run(["spctl", "--assess", "--type", "execute", str(stage / bundle.name)], log)
        archive.unlink()
        package(stage, archive, system, log)
    (output / (archive.name + ".sha256")).write_text(f"{digest(archive)}  {archive.name}\n", encoding="utf-8")
    shutil.copy2(stage / "build-manifest.json", output / "build-manifest.json")
    shutil.copy2(work / "self-check.json", output / "self-check.json")
    print(f"Built {archive}")


if __name__ == "__main__":
    main()
