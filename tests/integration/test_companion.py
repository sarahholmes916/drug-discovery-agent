from __future__ import annotations

from io import BytesIO
import time
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

from fastapi.testclient import TestClient

from apps.runner.companion import create_companion_app
from apps.runner.registry import RunnerRegistry
from apps.runner.tool_install import ToolInstallManager
from drug_discovery_agent.config.models import load_project_config
from drug_discovery_agent.project.io import read_json
from drug_discovery_agent.project.manifest import ManifestStore


def test_companion_pairs_without_user_entered_token(tmp_path) -> None:
    opened: list[str] = []
    website = "https://research.example"
    local = "http://127.0.0.1:8765"
    registry = RunnerRegistry(tmp_path / "registry.json")
    projects_root = tmp_path / "projects"
    app = create_companion_app(
        database=tmp_path / "control.sqlite3",
        approval_base_url=local,
        allowed_origins=[website],
        registry=registry,
        projects_root=projects_root,
        approval_opener=lambda url: opened.append(url),
    )
    client = TestClient(app)
    browser_headers = {"Origin": website, "X-Requested-With": "DrugDiscoveryAgent"}

    assert client.get("/v1/companion", headers=browser_headers).status_code == 200
    started = client.post("/v1/pairing/requests", headers=browser_headers, json={})
    assert started.status_code == 201
    request_id = started.json()["request_id"]
    assert len(opened) == 1
    fragment = parse_qs(urlsplit(opened[0]).fragment)
    assert fragment["request_id"] == [request_id]
    approval_secret = fragment["secret"][0]
    assert "secret=" not in urlsplit(opened[0]).query

    pending = client.get(f"/v1/pairing/requests/{request_id}", headers=browser_headers)
    assert pending.json()["status"] == "pending"
    approved = client.post(
        f"/v1/pairing/{request_id}/approve",
        headers={"Origin": local},
        json={"approval_secret": approval_secret},
    )
    assert approved.status_code == 200
    paired = client.get(f"/v1/pairing/requests/{request_id}", headers=browser_headers).json()
    token = paired["session_token"]

    authenticated = {**browser_headers, "Authorization": f"Bearer {token}"}
    assert client.get("/v1/health", headers=authenticated).status_code == 200
    extracted = client.post(
        "/v1/receptor/sequence",
        headers=authenticated,
        data={"protein_chain": "A"},
        files={
            "receptor_structure": (
                "target.pdb",
                b"ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 20.00           C  \n"
                b"ATOM      2  CA  GLY A   2       2.000   2.000   3.000  1.00 20.00           C  \nEND\n",
                "chemical/x-pdb",
            ),
        },
    )
    assert extracted.status_code == 200, extracted.text
    assert extracted.json() == {
        "chain": "A",
        "sequence": "AG",
        "source": "coordinate_records",
        "residue_count": 2,
        "available_chains": ["A"],
    }
    project = client.post(
        "/api/projects",
        headers={**authenticated, "Content-Type": "application/json"},
        json={"project_id": "example", "display_name": "Example"},
    )
    assert project.status_code == 200

    imported = client.post(
        "/v1/projects/import",
        headers=authenticated,
        data={
            "project_id": "uploaded",
            "display_name": "Uploaded project",
            "protein_chain": "A",
            "protein_sequence": "",
            "pocketminer": "true",
            "boltz_constrained": "false",
            "boltz_unconstrained": "false",
            "downstream_ligand_count": "25",
            "downstream_selection_metric": "ligand_efficiency",
        },
        files=[
            ("receptor_structure", ("target.pdb", b"ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 20.00           C  \nEND\n", "chemical/x-pdb")),
            ("receptor_pdbqt", ("target.pdbqt", b"ATOM      1  CA  ALA A   1       1.000   2.000   3.000  0.00  0.00    0.000 C\n", "text/plain")),
            ("ligands", ("ligands.sdf", b"$$$$\n", "chemical/x-mdl-sdfile")),
        ],
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["project_id"] == "uploaded"
    project_root = registry.project_root("uploaded")
    config = load_project_config(project_root / "project.yaml")
    assert config.pocket.mode == "pocketminer"
    assert config.analysis.vina_shortlist == 25
    assert config.analysis.vina_selection_metric == "ligand_efficiency"
    references = read_json(project_root / "state" / "local_refs.json")["references"]
    assert references["receptor_structure"].endswith("receptor.pdb")
    assert references["receptor_vina"].endswith("receptor.pdbqt")
    assert references["ligand_set_01"].endswith("ligand_source_0001.sdf")
    projects = client.get("/v1/projects", headers=authenticated)
    assert projects.status_code == 200
    assert projects.json() == {
        "projects": [{
            "project_id": "uploaded",
            "display_name": "Uploaded project",
            "available": True,
            "workflow": "vina_only",
            "features": {
                "pocketminer": True,
                "boltz_constrained": False,
                "boltz_unconstrained": False,
            },
            "receptor_preparation": {
                "method": "provided_pdbqt",
                "remove_waters": False,
                "heterogens": "review",
                "alternate_locations": "review",
                "charge_model": "gasteiger",
                "custom_instructions": None,
            },
            "downstream_selection": {
                "count": 25,
                "metric": "ligand_efficiency",
            },
            "run_id": None,
            "status": "NOT_STARTED",
            "active_stage": None,
            "updated_at": projects.json()["projects"][0]["updated_at"],
            "artifact_count": 0,
            "results_available": False,
        }],
    }
    assert str(tmp_path) not in projects.text

    report = project_root / "reports" / "summary.json"
    report.write_text('{"status":"complete"}', encoding="utf-8")
    ManifestStore(project_root).register_artifact("report:summary", "report_json", report)
    refreshed = client.get("/v1/projects", headers=authenticated).json()["projects"][0]
    assert refreshed["artifact_count"] == 1
    assert refreshed["results_available"] is True
    download = client.get("/v1/projects/uploaded/results", headers=authenticated)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(download.content)) as archive:
        assert "reports/summary.json" in archive.namelist()
        assert "project.yaml" in archive.namelist()
        assert "state/manifest.json" in archive.namelist()
    # The bridge resolves projects registered after companion startup.
    status = client.get("/v1/projects/uploaded/status", headers=authenticated)
    assert status.status_code == 404
    assert status.json()["detail"] == "project has no run"


def test_companion_requires_local_approval_and_exact_origin(tmp_path) -> None:
    website = "https://research.example"
    app = create_companion_app(
        database=tmp_path / "control.sqlite3",
        allowed_origins=[website],
        registry=RunnerRegistry(tmp_path / "registry.json"),
        approval_opener=lambda url: None,
    )
    client = TestClient(app)
    assert client.post(
        "/v1/pairing/requests",
        headers={"Origin": "https://attacker.example", "X-Requested-With": "DrugDiscoveryAgent"},
        json={},
    ).status_code == 403
    assert client.get("/v1/health", headers={"Origin": website}).status_code == 401
    assert client.get("/v1/projects", headers={"Origin": website}).status_code == 401
    assert client.post(
        "/v1/projects/import",
        headers={"Origin": website},
        files={"receptor_structure": ("target.pdb", b"ATOM\n")},
    ).status_code == 401


def test_companion_can_invisibly_pair_its_own_local_ui_origin(tmp_path) -> None:
    website = "http://127.0.0.1:8000"
    opened: list[str] = []
    app = create_companion_app(
        database=tmp_path / "control.sqlite3",
        allowed_origins=[website],
        auto_approve_origins=[website],
        registry=RunnerRegistry(tmp_path / "registry.json"),
        approval_opener=lambda url: opened.append(url),
    )
    client = TestClient(app)
    browser_headers = {"Origin": website, "X-Requested-With": "DrugDiscoveryAgent"}

    started = client.post("/v1/pairing/requests", headers=browser_headers, json={})
    assert started.status_code == 201
    assert opened == []
    paired = client.get(
        f"/v1/pairing/requests/{started.json()['request_id']}", headers=browser_headers,
    ).json()
    assert paired["status"] == "approved"
    authenticated = {
        **browser_headers,
        "Authorization": f"Bearer {paired['session_token']}",
    }
    assert client.get("/v1/health", headers=authenticated).status_code == 200


def test_paired_companion_runs_managed_tool_setup_and_reports_status(tmp_path) -> None:
    opened: list[str] = []
    website = "https://research.example"
    local = "http://127.0.0.1:8765"
    manager = ToolInstallManager({
        "vina": lambda progress: (progress("Verified official download"), "Vina is ready")[1],
    })
    app = create_companion_app(
        database=tmp_path / "control.sqlite3",
        approval_base_url=local,
        allowed_origins=[website],
        registry=RunnerRegistry(tmp_path / "registry.json"),
        tool_installs=manager,
        approval_opener=lambda url: opened.append(url),
    )
    client = TestClient(app)
    browser_headers = {"Origin": website, "X-Requested-With": "DrugDiscoveryAgent"}
    request_id = client.post("/v1/pairing/requests", headers=browser_headers, json={}).json()[
        "request_id"
    ]
    fragment = parse_qs(urlsplit(opened[0]).fragment)
    client.post(
        f"/v1/pairing/{request_id}/approve",
        headers={"Origin": local},
        json={"approval_secret": fragment["secret"][0]},
    )
    token = client.get(
        f"/v1/pairing/requests/{request_id}", headers=browser_headers,
    ).json()["session_token"]
    authenticated = {**browser_headers, "Authorization": f"Bearer {token}"}

    assert client.get("/v1/tools/installers", headers=browser_headers).status_code == 401
    catalog = client.get("/v1/tools/installers", headers=authenticated)
    assert catalog.status_code == 200
    assert catalog.json()["installers"]["AutoDock Vina"]["tool_id"] == "vina"
    assert client.post(
        "/v1/tools/vina/install", headers=authenticated, content=b"",
    ).status_code == 415
    started = client.post("/v1/tools/vina/install", headers=authenticated, json={})
    assert started.status_code == 202

    deadline = time.monotonic() + 2
    status = client.get(
        f"/v1/tools/installations/{started.json()['task_id']}", headers=authenticated,
    )
    while status.json()["status"] != "success" and time.monotonic() < deadline:
        time.sleep(0.005)
        status = client.get(
            f"/v1/tools/installations/{started.json()['task_id']}", headers=authenticated,
        )
    assert status.json()["message"] == "Vina is ready"
