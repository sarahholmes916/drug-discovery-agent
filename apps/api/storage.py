from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS machines (
  machine_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, status TEXT NOT NULL,
  last_seen TEXT NOT NULL, capabilities_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, user_id TEXT NOT NULL,
  status TEXT NOT NULL, active_stage TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, user_id TEXT NOT NULL,
  assigned_machine TEXT, state TEXT NOT NULL, sanitized_config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, user_id TEXT NOT NULL,
  timestamp TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
  completed INTEGER NOT NULL, total INTEGER NOT NULL, failed INTEGER NOT NULL,
  message TEXT, candidate_count INTEGER
);
"""


class ControlPlaneStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(SCHEMA)
            event_columns = {row["name"] for row in connection.execute("PRAGMA table_info(events)")}
            if "candidate_count" not in event_columns:
                connection.execute("ALTER TABLE events ADD COLUMN candidate_count INTEGER")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def heartbeat(self, *, machine_id: str, user_id: str, status: str,
                  last_seen: str, capabilities: dict[str, object]) -> None:
        with self.connection() as connection:
            owner = connection.execute(
                "SELECT user_id FROM machines WHERE machine_id=?", (machine_id,)
            ).fetchone()
            if owner and owner["user_id"] != user_id:
                raise PermissionError("machine ID belongs to another account")
            connection.execute(
                "INSERT INTO machines VALUES(?,?,?,?,?) ON CONFLICT(machine_id) DO UPDATE SET "
                "user_id=excluded.user_id,status=excluded.status,last_seen=excluded.last_seen,"
                "capabilities_json=excluded.capabilities_json",
                (machine_id, user_id, status, last_seen, json.dumps(capabilities)),
            )

    def create_project(self, project_id: str, user_id: str, display_name: str) -> None:
        with self.connection() as connection:
            owner = connection.execute(
                "SELECT user_id FROM projects WHERE project_id=?", (project_id,)
            ).fetchone()
            if owner and owner["user_id"] != user_id:
                raise PermissionError("project ID belongs to another account")
            connection.execute(
                "INSERT INTO projects VALUES(?,?,?) ON CONFLICT(project_id) DO UPDATE SET "
                "display_name=excluded.display_name",
                (project_id, user_id, display_name),
            )

    def create_run(self, run_id: str, project_id: str, user_id: str, status: str,
                   created_at: str) -> None:
        with self.connection() as connection:
            project = connection.execute(
                "SELECT 1 FROM projects WHERE project_id=? AND user_id=?", (project_id, user_id)
            ).fetchone()
            if not project:
                raise KeyError("project not found")
            connection.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)",
                               (run_id, project_id, user_id, status, None, created_at))

    def create_job(self, job_id: str, run_id: str, user_id: str,
                   sanitized_config: dict[str, object]) -> None:
        with self.connection() as connection:
            run = connection.execute(
                "SELECT project_id FROM runs WHERE run_id=? AND user_id=?", (run_id, user_id)
            ).fetchone()
            if not run:
                raise KeyError("run not found")
            if run["project_id"] != sanitized_config.get("project_id"):
                raise ValueError("job project does not match its run")
            connection.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)",
                               (job_id, run_id, user_id, None, "PENDING", json.dumps(sanitized_config)))

    def claim_job(self, machine_id: str, user_id: str) -> dict[str, object] | None:
        with self.connection() as connection:
            machine = connection.execute(
                "SELECT 1 FROM machines WHERE machine_id=? AND user_id=?", (machine_id, user_id)
            ).fetchone()
            if not machine:
                raise KeyError("machine not found")
            row = connection.execute(
                "SELECT * FROM jobs WHERE user_id=? AND state='PENDING' ORDER BY rowid LIMIT 1", (user_id,)
            ).fetchone()
            if row is None:
                return None
            updated = connection.execute(
                "UPDATE jobs SET state='CLAIMED', assigned_machine=? WHERE job_id=? AND state='PENDING'",
                (machine_id, row["job_id"]),
            )
            if updated.rowcount != 1:
                return None
            return {"job_id": row["job_id"], "run_id": row["run_id"],
                    "sanitized_config": json.loads(row["sanitized_config_json"])}

    def add_event(self, values: tuple[object, ...], *, reported_run_id: str) -> None:
        with self.connection() as connection:
            _, job_id, user_id, _, stage, status, *_ = values
            job = connection.execute("SELECT run_id FROM jobs WHERE job_id=? AND user_id=?", (job_id, user_id)).fetchone()
            if not job:
                raise KeyError("job not found")
            if job["run_id"] != reported_run_id:
                raise ValueError("event run does not match its job")
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)", values)
            terminal = status in {"FAILED", "CANCELLED", "awaiting_user_selection"} or (
                stage == "BUILD_REPORT" and status in {"SUCCESS", "PARTIAL", "NEEDS_REVIEW"}
            )
            run_status = status if terminal else "RUNNING"
            connection.execute("UPDATE runs SET status=?,active_stage=? WHERE run_id=?",
                               (run_status, stage, job["run_id"]))
            connection.execute("UPDATE jobs SET state=? WHERE job_id=?",
                               (status if terminal else "RUNNING", job_id))

    def job_state(self, job_id: str, user_id: str) -> str | None:
        with self.connection() as connection:
            row = connection.execute("SELECT state FROM jobs WHERE job_id=? AND user_id=?",
                                     (job_id, user_id)).fetchone()
            return row["state"] if row else None

    def request_cancellation(self, job_id: str, user_id: str) -> bool:
        with self.connection() as connection:
            result = connection.execute(
                "UPDATE jobs SET state='CANCEL_REQUESTED' WHERE job_id=? AND user_id=? "
                "AND state IN ('PENDING','CLAIMED','RUNNING')",
                (job_id, user_id),
            )
            return result.rowcount == 1

    def resume_after_selection(self, job_id: str, user_id: str) -> bool:
        with self.connection() as connection:
            job = connection.execute(
                "SELECT run_id,state FROM jobs WHERE job_id=? AND user_id=?", (job_id, user_id)
            ).fetchone()
            if not job or job["state"] != "awaiting_user_selection":
                return False
            connection.execute(
                "UPDATE jobs SET state='PENDING',assigned_machine=NULL WHERE job_id=?", (job_id,)
            )
            connection.execute(
                "UPDATE runs SET status='PENDING',active_stage=NULL WHERE run_id=?", (job["run_id"],)
            )
            return True

    def run_view(self, run_id: str, user_id: str) -> dict[str, object] | None:
        with self.connection() as connection:
            run = connection.execute("SELECT * FROM runs WHERE run_id=? AND user_id=?", (run_id, user_id)).fetchone()
            if not run:
                return None
            events = connection.execute(
                "SELECT timestamp,stage,status,completed,total,failed,message,candidate_count FROM events "
                "JOIN jobs USING(job_id) WHERE jobs.run_id=? AND events.user_id=? ORDER BY events.rowid",
                (run_id, user_id),
            ).fetchall()
            return {"run_id": run["run_id"], "project_id": run["project_id"], "status": run["status"],
                    "active_stage": run["active_stage"], "created_at": run["created_at"],
                    "events": [dict(event) for event in events]}
