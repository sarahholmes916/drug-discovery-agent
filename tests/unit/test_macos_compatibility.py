import json
import plistlib

import pytest

from drug_discovery_agent import macos_compatibility as compatibility


def build_command(version="14.0", platform="1"):
    return f"Load command 0\n cmd LC_BUILD_VERSION\n cmdsize 32\n platform {platform}\n minos {version}\n sdk 15.5\n"


def test_load_commands_use_minimum_not_sdk_and_include_all_slices():
    output = ("library (architecture arm64):\n" + build_command("11.0")
              + "library (architecture x86_64):\nLoad command 1\n"
                " cmd LC_VERSION_MIN_MACOSX\n version 10.13\n sdk 15.5\n")
    assert compatibility.minimum_versions(output) == ["11.0", "10.13"]


@pytest.mark.parametrize("output", ["", build_command(platform="2"),
                                    "Load command 0\n cmd LC_BUILD_VERSION\n platform 1\n"])
def test_unknown_or_non_macos_requirements_fail_closed(output):
    with pytest.raises(RuntimeError):
        compatibility.minimum_versions(output)


def bundle_fixture(tmp_path, minimum="14.0"):
    app = tmp_path / "Companion with spaces.app"
    contents = app / "Contents"
    contents.mkdir(parents=True)
    (contents / "Info.plist").write_bytes(plistlib.dumps({"LSMinimumSystemVersion": minimum}))
    (contents / "binary").write_bytes(bytes.fromhex("cffaedfe") + b"fixture")
    (contents / "ordinary.txt").write_text("not a native binary")
    return app


def test_bundle_records_native_versions_and_commands(tmp_path, monkeypatch):
    app = bundle_fixture(tmp_path)
    def inspect(command, **kwargs):
        assert command == ["/usr/bin/otool", "-l", str(app / "Contents/binary")]
        return build_command(platform="MACOS")
    monkeypatch.setattr(compatibility.subprocess, "check_output", inspect)
    log = tmp_path / "commands.jsonl"
    report = compatibility.verify_macos_bundle(app, log)
    assert report["native_minimum_versions"] == {"Contents/binary": ["14.0"]}
    assert json.loads(log.read_text())[1] == "-l"


@pytest.mark.parametrize("version", ["14.1", "14.5", "15.0"])
def test_bundle_rejects_newer_native_dependency(tmp_path, monkeypatch, version):
    app = bundle_fixture(tmp_path)
    monkeypatch.setattr(compatibility.subprocess, "check_output", lambda *a, **k: build_command(version))
    with pytest.raises(RuntimeError, match="Contents/binary requires macOS"):
        compatibility.verify_macos_bundle(app, tmp_path / "commands.jsonl")


def test_bundle_rejects_old_plist_before_inspection(tmp_path):
    with pytest.raises(RuntimeError, match="App must declare"):
        compatibility.verify_macos_bundle(bundle_fixture(tmp_path, "15.0"), tmp_path / "commands.jsonl")
