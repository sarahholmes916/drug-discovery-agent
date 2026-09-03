from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def is_browser_origin(value: str) -> bool:
    """Return whether *value* is a safe, canonical browser Origin value."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if not parsed.hostname or parsed.username or parsed.password:
        return False
    if parsed.path or parsed.query or parsed.fragment:
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme != "http" or parsed.hostname.lower() not in _LOOPBACK_HOSTS:
        return False
    # Accessing .port above also rejects malformed ports. Explicit loopback ports
    # are allowed because development and the local UI do not use port 80.
    return port is None or 1 <= port <= 65535


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PairingLaunch:
    request_id: str
    approval_secret: str
    origin: str
    expires_at: float


@dataclass
class _PairingRequest:
    request_id: str
    approval_digest: str
    origin: str
    expires_at: float
    state: str = "pending"
    session_token: str | None = None


@dataclass(frozen=True)
class _Session:
    origin: str
    expires_at: float


class PairingManager:
    """Issue origin-scoped browser sessions after a one-time local approval."""

    def __init__(
        self,
        *,
        allowed_origins: list[str] | None = None,
        request_ttl_seconds: int = 120,
        session_ttl_seconds: int = 12 * 60 * 60,
        clock: Callable[[], float] = time.time,
        learn_first_origin: bool = False,
        on_first_origin_approved: Callable[[str], None] | None = None,
    ) -> None:
        configured = frozenset(allowed_origins or [])
        if any(not is_browser_origin(origin) for origin in configured):
            raise ValueError("pairing origins must be HTTPS or an HTTP loopback origin")
        if request_ttl_seconds < 30:
            raise ValueError("pairing requests must remain valid for at least 30 seconds")
        if session_ttl_seconds < 60:
            raise ValueError("paired sessions must remain valid for at least 60 seconds")
        self._allowed_origins = configured
        self._request_ttl = request_ttl_seconds
        self._session_ttl = session_ttl_seconds
        self._clock = clock
        self._learn_first_origin = learn_first_origin and not configured
        self._on_first_origin_approved = on_first_origin_approved
        self._learned_origin: str | None = None
        self._requests: dict[str, _PairingRequest] = {}
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def accepts_origin(self, origin: str) -> bool:
        if not is_browser_origin(origin):
            return False
        if self._allowed_origins:
            return origin in self._allowed_origins
        return self._learned_origin is None or hmac.compare_digest(origin, self._learned_origin)

    def begin(self, origin: str) -> PairingLaunch:
        if not self.accepts_origin(origin):
            raise PermissionError("website origin is not allowed to pair")
        now = self._clock()
        with self._lock:
            self._cleanup(now)
            approval_secret = secrets.token_urlsafe(32)
            request_id = secrets.token_urlsafe(24)
            expires_at = now + self._request_ttl
            self._requests[request_id] = _PairingRequest(
                request_id=request_id,
                approval_digest=_digest(approval_secret),
                origin=origin,
                expires_at=expires_at,
            )
        return PairingLaunch(request_id, approval_secret, origin, expires_at)

    def approve(self, request_id: str, approval_secret: str) -> bool:
        now = self._clock()
        learned_origin: str | None = None
        with self._lock:
            self._cleanup(now)
            request = self._requests.get(request_id)
            if request is None or request.state != "pending":
                return False
            if not self.accepts_origin(request.origin):
                return False
            if not hmac.compare_digest(request.approval_digest, _digest(approval_secret)):
                return False
            token = secrets.token_urlsafe(48)
            request.state = "approved"
            request.session_token = token
            self._sessions[_digest(token)] = _Session(
                origin=request.origin,
                expires_at=now + self._session_ttl,
            )
            if self._learn_first_origin and self._learned_origin is None:
                self._learned_origin = request.origin
                learned_origin = request.origin
        if learned_origin and self._on_first_origin_approved:
            self._on_first_origin_approved(learned_origin)
        return True

    def deny(self, request_id: str, approval_secret: str) -> bool:
        now = self._clock()
        with self._lock:
            self._cleanup(now)
            request = self._requests.get(request_id)
            if request is None or request.state != "pending":
                return False
            if not hmac.compare_digest(request.approval_digest, _digest(approval_secret)):
                return False
            request.state = "denied"
            return True

    def status(self, request_id: str, origin: str) -> dict[str, object]:
        now = self._clock()
        with self._lock:
            self._cleanup(now)
            request = self._requests.get(request_id)
            if request is None:
                raise KeyError("pairing request not found or expired")
            if not hmac.compare_digest(request.origin, origin):
                raise PermissionError("pairing request belongs to another website origin")
            result: dict[str, object] = {
                "request_id": request.request_id,
                "status": request.state,
                "expires_in": max(0, int(request.expires_at - now)),
            }
            if request.state == "approved" and request.session_token:
                # The request is short lived, so repeating this value makes polling
                # resilient to a dropped response without creating a durable secret.
                result["session_token"] = request.session_token
            return result

    def authorize(self, origin: str, token: str) -> bool:
        if not origin or not token:
            return False
        now = self._clock()
        with self._lock:
            self._cleanup(now)
            supplied_digest = _digest(token)
            for expected_digest, session in self._sessions.items():
                if hmac.compare_digest(expected_digest, supplied_digest):
                    return hmac.compare_digest(session.origin, origin)
            return False

    def _cleanup(self, now: float) -> None:
        self._requests = {
            key: value for key, value in self._requests.items() if value.expires_at > now
        }
        self._sessions = {
            key: value for key, value in self._sessions.items() if value.expires_at > now
        }
