from __future__ import annotations

from fastapi.testclient import TestClient

from apps.runner.bridge import create_bridge
from drug_discovery_agent.config.models import ProjectConfig
from drug_discovery_agent.project.io import atomic_write_json
from drug_discovery_agent.project.layout import create_project


def test_bridge_requires_exact_origin_and_token() -> None:
    token = "a" * 64
    app = create_bridge(token=token, allowed_origins=["https://research.example"], projects={})
    client = TestClient(app)
    assert client.get("/v1/health", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    origin = {"Origin": "https://research.example"}
    assert client.get("/v1/health", headers=origin).status_code == 401
    response = client.get("/v1/health", headers={**origin, "Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["service"] == "drug-agent-local"


def test_bridge_serves_and_confirms_only_registered_pocket_data(tmp_path) -> None:
    receptor = tmp_path / "receptor.pdb"
    receptor.write_text(
        "ATOM      1   CA ALA A   1       1.000   2.000   3.000  1.00  0.50           C  \nEND\n",
        encoding="ascii",
    )
    ligands = tmp_path / "ligands.sdf"; ligands.write_text("$$$$\n")
    config = ProjectConfig.model_validate({
        "project": {"id": "pockets"}, "workflow": "custom",
        "custom_stages": ["AWAIT_POCKET_SELECTION"],
        "target": {"receptor_ref": "receptor"}, "pocket": {"mode": "manual"},
        "ligands": [{"source_ref": "ligands", "kind": "multi_sdf"}],
    })
    layout = create_project(tmp_path / "projects", config, {"receptor": receptor, "ligands": ligands})
    atomic_write_json(layout.root / "pocketminer" / "candidates" / "ranked_pockets.json", {
        "candidate_count": 0, "max_displayed_candidates": 5, "candidates": [],
    })
    visualization = layout.root / "pocketminer" / "visualization" / "receptor_pocketminer_scores.pdb"
    visualization.write_text(receptor.read_text(), encoding="ascii")
    token, origin = "b" * 64, {"Origin": "https://research.example"}
    app = create_bridge(token=token, allowed_origins=[origin["Origin"]], projects={"pockets": layout.root})
    client = TestClient(app); headers = {**origin, "Authorization": f"Bearer {token}"}
    assert client.get("/v1/projects/pockets/pockets", headers=headers).json()["candidate_count"] == 0
    response = client.post(
        "/v1/projects/pockets/pocket-selection", headers={**headers, "Content-Type": "application/json"},
        json={"center": [1, 2, 3], "size": [10, 10, 10]},
    )
    assert response.status_code == 200
    assert response.json()["source"] == "manual"
    assert client.get("/v1/projects/pockets/pocket-selection", headers=headers).status_code == 200


def test_bridge_reports_live_vina_file_progress(tmp_path) -> None:
    receptor = tmp_path / "receptor.pdbqt"; receptor.write_text("ATOM\n")
    ligands = tmp_path / "ligands.sdf"; ligands.write_text("$$$$\n")
    config = ProjectConfig.model_validate({
        "project": {"id": "progress"}, "workflow": "custom",
        "custom_stages": ["RUN_VINA"],
        "target": {"receptor_ref": "receptor", "receptor_pdbqt_ref": "receptor"},
        "pocket": {"mode": "manual", "center": [1, 2, 3], "vina_size": [10, 10, 10]},
        "ligands": [{"source_ref": "ligands", "kind": "multi_sdf"}],
    })
    layout = create_project(
        tmp_path / "projects", config, {"receptor": receptor, "ligands": ligands},
    )
    for name in ("one", "two", "three"):
        (layout.root / "ligands" / "prepared_pdbqt" / f"{name}.pdbqt").write_text("ATOM\n")
    (layout.root / "vina" / "docked" / "one_out.pdbqt").write_text("MODEL\n")
    atomic_write_json(layout.run_state, {
        "run_id": "run_progress", "project_id": "progress", "status": "RUNNING",
        "active_stage": "RUN_VINA", "updated_at": "2026-01-01T00:00:00Z",
        "failures": [],
        "stages": {"RUN_VINA": {"name": "RUN_VINA", "status": "RUNNING", "items": {}}},
    })
    token, origin = "p" * 64, {"Origin": "https://research.example"}
    client = TestClient(create_bridge(
        token=token, allowed_origins=[origin["Origin"]], projects={"progress": layout.root},
    ))
    response = client.get(
        "/v1/projects/progress/progress",
        headers={**origin, "Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "project_id": "progress", "run_id": "run_progress", "status": "RUNNING",
        "active_stage": "RUN_VINA", "last_stage": "RUN_VINA", "stage_status": "RUNNING",
        "completed": 1, "total": 3, "failed": 0,
        "message": None, "updated_at": "2026-01-01T00:00:00Z",
    }


def test_bridge_reports_the_last_failed_stage_after_execution_stops(tmp_path) -> None:
    receptor = tmp_path / "receptor.pdbqt"; receptor.write_text("ATOM\n")
    ligands = tmp_path / "ligands.sdf"; ligands.write_text("$$$$\n")
    config = ProjectConfig.model_validate({
        "project": {"id": "failed"}, "workflow": "custom",
        "custom_stages": ["RUN_BOLTZ_CONSTRAINED"],
        "target": {"receptor_ref": "receptor"},
        "pocket": {"mode": "manual"},
        "ligands": [{"source_ref": "ligands", "kind": "multi_sdf"}],
    })
    layout = create_project(
        tmp_path / "projects", config, {"receptor": receptor, "ligands": ligands},
    )
    atomic_write_json(layout.run_state, {
        "run_id": "run_failed", "project_id": "failed", "status": "FAILED",
        "active_stage": None, "updated_at": "2026-01-01T00:00:00Z",
        "failures": [{"stage": "RUN_BOLTZ_CONSTRAINED"}],
        "stages": {"RUN_BOLTZ_CONSTRAINED": {
            "name": "RUN_BOLTZ_CONSTRAINED", "status": "FAILED",
            "started_at": "2026-01-01T00:00:00Z", "ended_at": "2026-01-01T00:01:00Z",
            "items": {"ligand": {"status": "FAILED"}},
        }},
    })
    token, origin = "f" * 64, {"Origin": "https://research.example"}
    client = TestClient(create_bridge(
        token=token, allowed_origins=[origin["Origin"]], projects={"failed": layout.root},
    ))

    payload = client.get(
        "/v1/projects/failed/progress",
        headers={**origin, "Authorization": f"Bearer {token}"},
    ).json()

    assert payload["status"] == "FAILED"
    assert payload["active_stage"] is None
    assert payload["last_stage"] == "RUN_BOLTZ_CONSTRAINED"
    assert payload["stage_status"] == "FAILED"
    assert payload["total"] == 1
    assert payload["failed"] == 1


def test_bridge_does_not_report_failures_from_a_previous_stage_attempt(tmp_path) -> None:
    receptor = tmp_path / "receptor.pdbqt"; receptor.write_text("ATOM\n")
    ligands = tmp_path / "ligands.sdf"; ligands.write_text("$$$$\n")
    config = ProjectConfig.model_validate({
        "project": {"id": "retrying"}, "workflow": "custom",
        "custom_stages": ["RUN_BOLTZ_CONSTRAINED"],
        "target": {"receptor_ref": "receptor"},
        "pocket": {"mode": "manual"},
        "ligands": [{"source_ref": "ligands", "kind": "multi_sdf"}],
    })
    layout = create_project(
        tmp_path / "projects", config, {"receptor": receptor, "ligands": ligands},
    )
    atomic_write_json(layout.run_state, {
        "run_id": "run_retrying", "project_id": "retrying", "status": "RUNNING",
        "active_stage": "RUN_BOLTZ_CONSTRAINED", "updated_at": "2026-01-01T00:02:00Z",
        "failures": [],
        "stages": {"RUN_BOLTZ_CONSTRAINED": {
            "name": "RUN_BOLTZ_CONSTRAINED", "status": "RUNNING",
            "started_at": "2026-01-01T00:02:00Z", "ended_at": None,
            "items": {
                "old_failure": {
                    "status": "FAILED", "updated_at": "2026-01-01T00:01:00Z",
                },
                "old_success": {
                    "status": "SUCCESS", "updated_at": "2026-01-01T00:01:00Z",
                },
            },
        }},
    })
    for name in ("first", "second"):
        prediction = (
            layout.root / "boltz_constrained" / "results" / name / "hash" /
            "attempt_0001" / f"boltz_results_{name}" / "predictions" / name
        )
        prediction.mkdir(parents=True)
        (prediction / f"affinity_{name}.json").write_text("{}")
    token, origin = "r" * 64, {"Origin": "https://research.example"}
    client = TestClient(create_bridge(
        token=token, allowed_origins=[origin["Origin"]], projects={"retrying": layout.root},
    ))

    payload = client.get(
        "/v1/projects/retrying/progress",
        headers={**origin, "Authorization": f"Bearer {token}"},
    ).json()

    assert payload["status"] == "RUNNING"
    assert payload["active_stage"] == "RUN_BOLTZ_CONSTRAINED"
    assert payload["total"] == 2
    assert payload["completed"] == 2
    assert payload["failed"] == 0
