from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_control_plane_accepts_only_sanitized_job_config(tmp_path: Path) -> None:
    app = create_app(database=tmp_path / "control.sqlite3", bearer_tokens={"secret-token": "user_1"})
    client = TestClient(app)
    headers = {"Authorization": "Bearer secret-token"}
    assert client.post("/projects", headers=headers,
                       json={"project_id": "project_1", "display_name": "Project"}).status_code == 200
    assert client.post("/projects", headers=headers,
                       json={"project_id": "project_1", "display_name": "Renamed"}).status_code == 200
    assert client.post("/runs", headers=headers,
                       json={"run_id": "run_1", "project_id": "project_1"}).status_code == 200
    safe = {"project_id": "project_1", "workflow": "vina_only", "stages": [],
            "features": {"vina": True}, "execution": {}}
    assert client.post("/jobs", headers=headers,
                       json={"job_id": "job_1", "run_id": "run_1", "sanitized_config": safe}).status_code == 200
    unsafe = {**safe, "protein_sequence": "ACDE"}
    response = client.post("/jobs", headers=headers,
                           json={"job_id": "job_2", "run_id": "run_1", "sanitized_config": unsafe})
    assert response.status_code >= 400

    mismatched_event = {
        "run_id": "run_wrong", "stage": "RUN_VINA", "status": "SUCCESS",
        "completed": 1, "total": 1, "failed": 0,
    }
    assert client.post("/runner/jobs/job_1/events", headers=headers,
                       json=mismatched_event).status_code == 409

    waiting_event = {
        "run_id": "run_1", "stage": "pocket_selection", "status": "awaiting_user_selection",
        "completed": 0, "total": 2, "failed": 0, "candidate_count": 2,
    }
    assert client.post("/runner/jobs/job_1/events", headers=headers, json=waiting_event).status_code == 200
    assert client.post("/jobs/job_1/resume", headers=headers, json={}).json()["state"] == "PENDING"


def test_control_plane_ids_cannot_be_taken_over_between_users(tmp_path: Path) -> None:
    app = create_app(
        database=tmp_path / "control.sqlite3",
        bearer_tokens={"token-one": "user_1", "token-two": "user_2"},
    )
    client = TestClient(app)
    first = {"Authorization": "Bearer token-one"}
    second = {"Authorization": "Bearer token-two"}
    payload = {"project_id": "shared_id", "display_name": "First"}
    assert client.post("/projects", headers=first, json=payload).status_code == 200
    assert client.post("/projects", headers=second, json=payload).status_code == 409
