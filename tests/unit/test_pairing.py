from __future__ import annotations

import pytest

from apps.runner.pairing import PairingManager, is_browser_origin


def test_pairing_accepts_https_and_loopback_but_not_remote_http() -> None:
    assert is_browser_origin("https://research.example")
    assert is_browser_origin("http://127.0.0.1:8000")
    assert is_browser_origin("http://localhost:3000")
    assert not is_browser_origin("http://research.example")
    assert not is_browser_origin("https://research.example/path")
    assert not is_browser_origin("javascript:alert(1)")


def test_approved_session_is_scoped_to_exact_origin_and_expires() -> None:
    now = [1_000.0]
    pairing = PairingManager(
        allowed_origins=["https://research.example"],
        request_ttl_seconds=60,
        session_ttl_seconds=120,
        clock=lambda: now[0],
    )
    launch = pairing.begin("https://research.example")
    assert pairing.status(launch.request_id, launch.origin)["status"] == "pending"
    assert not pairing.approve(launch.request_id, "wrong-secret" * 4)
    assert pairing.approve(launch.request_id, launch.approval_secret)
    status = pairing.status(launch.request_id, launch.origin)
    token = str(status["session_token"])
    assert pairing.authorize("https://research.example", token)
    assert not pairing.authorize("https://lookalike.example", token)
    now[0] += 121
    assert not pairing.authorize("https://research.example", token)


def test_pairing_rejects_unconfigured_origin() -> None:
    pairing = PairingManager(allowed_origins=["https://research.example"])
    with pytest.raises(PermissionError, match="not allowed"):
        pairing.begin("https://attacker.example")


def test_first_approved_origin_can_be_learned_without_showing_a_token() -> None:
    learned: list[str] = []
    pairing = PairingManager(
        learn_first_origin=True,
        on_first_origin_approved=learned.append,
    )
    launch = pairing.begin("https://research.example")
    assert pairing.approve(launch.request_id, launch.approval_secret)
    assert learned == ["https://research.example"]
    assert pairing.accepts_origin("https://research.example")
    assert not pairing.accepts_origin("https://attacker.example")
