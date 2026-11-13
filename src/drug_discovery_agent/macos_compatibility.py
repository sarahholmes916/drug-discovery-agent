"""Build-time checks of declared native macOS requirements, not runtime certification."""
from __future__ import annotations

import json
from pathlib import Path
import plistlib
import re
import subprocess

MACOS_MINIMUM = "14.0"
_MAGIC = {bytes.fromhex(value) for value in (
    "feedface", "cefaedfe", "feedfacf", "cffaedfe",
    "cafebabe", "bebafeca", "cafebabf", "bfbafeca",
)}


def _version(value: str) -> tuple[int, int, int]:
    parts = tuple(map(int, value.split(".")))
    return (parts + (0, 0, 0))[:3]


def minimum_versions(output: str) -> list[str]:
    """Read otool load commands, including every slice of a universal binary."""
    versions = []
    for block in re.split(r"Load command \d+", output):
        if re.search(r"\bcmd LC_BUILD_VERSION\b", block):
            if not re.search(r"\bplatform\s+(?:1|MACOS|macos)\s", block):
                raise RuntimeError("Native library targets a platform other than macOS")
            match = re.search(r"\bminos\s+(\d+(?:\.\d+){0,2})\b", block)
        elif re.search(r"\bcmd LC_VERSION_MIN_MACOSX\b", block):
            match = re.search(r"\bversion\s+(\d+(?:\.\d+){0,2})\b", block)
        else:
            continue
        if match is None:
            raise RuntimeError("Cannot read native library minimum macOS version")
        versions.append(match[1])
    if not versions:
        raise RuntimeError("Native library has no declared minimum macOS version")
    return versions


def verify_macos_bundle(bundle: Path, command_log: Path) -> dict:
    """Reject bundled executables/extensions that declare a newer OS requirement."""
    with (bundle / "Contents/Info.plist").open("rb") as handle:
        plist = plistlib.load(handle)
    if plist.get("LSMinimumSystemVersion") != MACOS_MINIMUM:
        raise RuntimeError(f"App must declare macOS {MACOS_MINIMUM}")
    inventory = {}
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as handle:
            if handle.read(4) not in _MAGIC:
                continue
        command = ["/usr/bin/otool", "-l", str(path)]
        with command_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(command) + "\n")
        output = subprocess.check_output(command, text=True, timeout=60)
        versions = minimum_versions(output)
        relative = path.relative_to(bundle).as_posix()
        if any(_version(version) > _version(MACOS_MINIMUM) for version in versions):
            raise RuntimeError(f"{relative} requires macOS {max(versions, key=_version)}; "
                               f"cannot package for {MACOS_MINIMUM}")
        inventory[relative] = versions
    if not inventory:
        raise RuntimeError("No Mach-O binaries found in the macOS app")
    return {"minimum_system_version": MACOS_MINIMUM,
            "native_minimum_versions": inventory,
            "validation": "Declared deployment targets only; test on macOS 14 before claiming runtime support."}
