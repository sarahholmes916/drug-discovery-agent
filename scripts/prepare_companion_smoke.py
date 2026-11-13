"""Verify and extract a release into a path with spaces for executable tests."""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--target", required=True)
args = parser.parse_args()
directory = ROOT / "dist" / args.target
suffix = ".tar.gz" if args.target.startswith("linux") else ".zip"
archive = directory / f"DrugDiscoveryAgent-Companion-{args.target}{suffix}"
with archive.open("rb") as handle:
    actual = hashlib.file_digest(handle, "sha256").hexdigest()
expected, name = (directory / (archive.name + ".sha256")).read_text().split()
assert name == archive.name and actual == expected, "Archive checksum mismatch"
destination = Path(tempfile.mkdtemp(prefix="Extracted companion with spaces ", dir=ROOT / "build"))
if platform.system() == "Darwin":
    subprocess.run(["ditto", "-x", "-k", str(archive), str(destination)], check=True)
    executable = destination / "DrugDiscoveryAgent-Companion.app/Contents/MacOS/DrugDiscoveryAgent-Companion"
elif suffix == ".tar.gz":
    with tarfile.open(archive) as source:
        source.extractall(destination, filter="data")
    executable = destination / "DrugDiscoveryAgent-Companion"
else:
    with zipfile.ZipFile(archive) as source:
        source.extractall(destination)
    executable = destination / "DrugDiscoveryAgent-Companion.exe"
subprocess.run([str(executable), "--self-check", str(destination / "self-check.json")], check=True, timeout=180)
if os.environ.get("GITHUB_ENV"):
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as handle:
        handle.write(f"COMPANION_EXECUTABLE={executable}\n")
else:
    print(executable)
