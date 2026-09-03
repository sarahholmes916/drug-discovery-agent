from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Protocol

from drug_discovery_agent.privacy import validate_cloud_payload


class ControlPlaneClient(Protocol):
    def heartbeat(self, payload: dict[str, object]) -> None: ...
    def claim_job(self, machine_id: str) -> dict[str, object] | None: ...
    def report_event(self, job_id: str, payload: dict[str, object]) -> None: ...
    def job_state(self, job_id: str) -> str: ...


@dataclass(slots=True)
class PollingControlPlaneClient:
    endpoint: str
    token: str
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError("control-plane endpoint must use HTTPS (HTTP is allowed only on loopback)")
        if not self.token:
            raise ValueError("control-plane bearer token cannot be empty")

    def _request(self, method: str, path: str, payload: dict[str, object] | None = None) -> object:
        if payload is not None:
            validate_cloud_payload(payload)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.endpoint.rstrip("/") + path, data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"control-plane request failed: HTTP {exc.code}") from exc
        return json.loads(body) if body else None

    def heartbeat(self, payload: dict[str, object]) -> None:
        self._request("POST", "/runner/heartbeat", payload)

    def claim_job(self, machine_id: str) -> dict[str, object] | None:
        result = self._request("POST", "/runner/jobs/claim", {"machine_id": machine_id})
        return result if isinstance(result, dict) and result else None

    def report_event(self, job_id: str, payload: dict[str, object]) -> None:
        self._request("POST", f"/runner/jobs/{job_id}/events", payload)

    def job_state(self, job_id: str) -> str:
        result = self._request("GET", f"/runner/jobs/{job_id}/state")
        return str(result.get("state")) if isinstance(result, dict) else "UNKNOWN"
