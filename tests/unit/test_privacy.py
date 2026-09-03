from __future__ import annotations

import pytest

from drug_discovery_agent.privacy import PrivacyViolation, progress_payload, validate_cloud_payload


def test_progress_payload_contains_only_aggregate_state() -> None:
    payload = progress_payload(run_id="run_123", stage="RUN_VINA", status="RUNNING",
                               completed=843, total=1200, failed=7)
    assert set(payload) == {"run_id", "stage", "status", "completed", "total", "failed"}


def test_pocket_selection_progress_exposes_only_safe_count() -> None:
    payload = progress_payload(
        run_id="run_123", stage="pocket_selection", status="awaiting_user_selection",
        completed=0, total=3, failed=0, candidate_count=3,
    )
    assert payload == {
        "run_id": "run_123", "stage": "pocket_selection", "status": "awaiting_user_selection",
        "completed": 0, "total": 3, "failed": 0, "candidate_count": 3,
    }
    assert "residue" not in str(payload).lower()


@pytest.mark.parametrize(
    "payload",
    [
        {"smiles": "CCO"},
        {"protein_sequence": "ACDE"},
        {"message": r"C:\\Research\\secret.sdf"},
        {"nested": {"pdb_contents": "ATOM"}},
        {"plip_report": "report.xml"},
    ],
)
def test_cloud_payload_rejects_science_and_paths(payload: dict[str, object]) -> None:
    with pytest.raises(PrivacyViolation):
        validate_cloud_payload(payload)


def test_explicit_future_sync_gate_is_separate() -> None:
    validate_cloud_payload({"smiles": "CCO"}, sync_enabled=True)
