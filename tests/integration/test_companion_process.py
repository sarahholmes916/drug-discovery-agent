"""Actual HTTP/process tests, also run against the extracted release executable."""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest
import importlib.util


def test_server_startup_authorization_shutdown_and_restart(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    executable = os.environ.get("COMPANION_EXECUTABLE")
    command = [executable] if executable else [sys.executable, "-m", "apps.companion_main"]
    home = tmp_path / "Research Data with spaces"
    home.mkdir()
    # Older registry entries and arbitrary registered project paths must survive.
    project = tmp_path / "Existing project"
    project.mkdir()
    registry = {"schema_version": 1, "projects": {"existing": str(project)}, "runs": {}}
    (home / "registry.json").write_text(json.dumps(registry))
    env = {**os.environ, "DRUG_AGENT_HOME": str(home), "DRUG_AGENT_TOOLS_HOME": str(home / "tools"),
           "PYTHONPATH": os.pathsep.join([str(repository), str(repository / "src")])}
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    website = "https://research.example"
    def request(path, origin=website):
        with urlopen(Request(f"http://127.0.0.1:{port}" + path, headers={"Origin": origin}), timeout=2) as response:
            return json.load(response)
    for iteration in range(2):
        with (tmp_path / f"process-{iteration}.log").open("wb") as log:
            process = subprocess.Popen(
                [*command, "--port", str(port), "--origin", website], cwd=repository,
                env=env, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            try:
                deadline = time.monotonic() + 45
                while True:
                    assert process.poll() is None, (tmp_path / f"process-{iteration}.log").read_text(errors="replace")
                    try:
                        discovery = request("/v1/companion")
                        break
                    except (URLError, TimeoutError):
                        if time.monotonic() > deadline:
                            pytest.fail("Companion failed to open its localhost server")
                        time.sleep(0.2)
                assert discovery["service"] == "drug-agent-companion"
                with pytest.raises(HTTPError) as denied:
                    request("/v1/companion", "https://untrusted.example")
                assert denied.value.code == 403
                with pytest.raises(HTTPError) as unauthorized:
                    request("/v1/capabilities")
                assert unauthorized.value.code == 401
                process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
                process.wait(timeout=20)
                # Uvicorn restores and re-raises the terminating signal after
                # completing shutdown (SIGBREAK is exit 3 on Windows).
                assert process.returncode in ((0, 3) if os.name == "nt" else (0, -signal.SIGTERM))
                assert "Application shutdown complete" in (tmp_path / f"process-{iteration}.log").read_text(errors="replace")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
    assert json.loads((home / "registry.json").read_text())["projects"] == registry["projects"]
    assert (home / "control_plane.sqlite3").is_file()


def test_actual_meeko_entrypoints_and_paths_with_spaces(tmp_path):
    executable = os.environ.get("COMPANION_EXECUTABLE")
    if not executable and importlib.util.find_spec("meeko") is None:
        pytest.skip("Meeko is not installed in the source environment")
    repository = Path(__file__).resolve().parents[2]
    command = [executable] if executable else [sys.executable, "-m", "apps.companion_main"]
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(repository), str(repository / "src")])}
    source = repository / "tests/fixtures/vina/structures_12233_prepared.sdf"
    output = tmp_path / "prepared ligand with spaces.pdbqt"
    result = subprocess.run([*command, "--internal-prepare-ligand", "-i", str(source), "-o", str(output)],
                            cwd=repository, env=environment, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "ROOT" in output.read_text()
    help_result = subprocess.run([*command, "--internal-prepare-receptor", "--help"],
                                cwd=repository, env=environment, capture_output=True, text=True, timeout=60)
    assert help_result.returncode == 0, help_result.stderr
