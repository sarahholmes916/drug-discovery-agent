from __future__ import annotations

import threading

from apps.runner import companion


def test_claimed_job_is_failed_when_local_project_startup_fails(monkeypatch) -> None:
    shutdown = threading.Event()

    class FakeClient:
        def __init__(self) -> None:
            self.claimed = False
            self.events: list[tuple[str, dict[str, object]]] = []

        def heartbeat(self, payload: dict[str, object]) -> None:
            assert payload["machine_id"] == "localhost_companion"

        def claim_job(self, machine_id: str) -> dict[str, object] | None:
            if self.claimed:
                return None
            self.claimed = True
            return {
                "job_id": "job_missing",
                "run_id": "run_missing",
                "sanitized_config": {"project_id": "missing"},
            }

        def report_event(self, job_id: str, payload: dict[str, object]) -> None:
            self.events.append((job_id, payload))
            shutdown.set()

        def job_state(self, job_id: str) -> str:
            return "CLAIMED"

    class MissingProjectService:
        def start_assigned(self, project_id: str, run_id: str, *, progress=None):
            raise KeyError(project_id)

        def cancel(self, run_id: str) -> None:
            raise AssertionError("cancellation should not be requested")

    client = FakeClient()
    monkeypatch.setattr(companion, "PollingControlPlaneClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(companion, "collect_capabilities", lambda: [])

    companion.run_worker_loop(
        endpoint="http://127.0.0.1:8765/api",
        token="service-token",
        service=MissingProjectService(),  # type: ignore[arg-type]
        shutdown=shutdown,
        poll_interval=0.01,
    )

    assert client.events == [(
        "job_missing",
        {
            "run_id": "run_missing",
            "stage": "INGEST_PROJECT",
            "status": "FAILED",
            "completed": 0,
            "total": 1,
            "failed": 1,
            "message_code": "stage_failed",
        },
    )]
