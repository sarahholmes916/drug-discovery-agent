from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import json
from uuid import uuid4
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field


StreamName = Literal["stdout", "stderr"]
ProgressHook = Callable[[StreamName, str], None]


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str]
    working_directory: str
    return_code: int
    stdout: str
    stderr: str
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    timed_out: bool = False
    cancelled: bool = False
    environment_keys: list[str] = Field(default_factory=list)

    @property
    def successful(self) -> bool:
        return self.return_code == 0 and not self.timed_out and not self.cancelled


class CommandExecutor:
    """Run argument-array commands with streaming, timeout, and cancellation."""

    def __init__(self, record_directory: str | Path | None = None) -> None:
        self.record_directory = Path(record_directory) if record_directory else None

    def _record(self, result: CommandResult) -> None:
        if self.record_directory is None:
            return
        self.record_directory.mkdir(parents=True, exist_ok=True)
        target = self.record_directory / f"command_{uuid4().hex}.json"
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_text(json.dumps(result.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)

    def run(
        self,
        command: Sequence[str | os.PathLike[str]],
        *,
        working_directory: str | Path,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        cancellation: CancellationToken | None = None,
        progress_hook: ProgressHook | None = None,
    ) -> CommandResult:
        args = [os.fspath(value) for value in command]
        if not args:
            raise ValueError("command cannot be empty")
        cwd = Path(working_directory).resolve()
        cwd.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        if environment:
            env.update(environment)

        start_dt = datetime.now(UTC)
        start = time.monotonic()
        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                bufsize=1,
            )
        except OSError as exc:
            end_dt = datetime.now(UTC)
            result = CommandResult(
                command=args,
                working_directory=str(cwd),
                return_code=127,
                stdout="",
                stderr=f"could not start external command: {exc}",
                start_time=start_dt,
                end_time=end_dt,
                duration_seconds=time.monotonic() - start,
                environment_keys=sorted(environment or {}),
            )
            self._record(result)
            return result
        events: queue.Queue[tuple[StreamName, str] | tuple[StreamName, None]] = queue.Queue()

        def consume(name: StreamName, stream: object) -> None:
            assert hasattr(stream, "readline")
            for line in iter(stream.readline, ""):
                events.put((name, line))
            events.put((name, None))

        readers = [
            threading.Thread(target=consume, args=("stdout", process.stdout), daemon=True),
            threading.Thread(target=consume, args=("stderr", process.stderr), daemon=True),
        ]
        for reader in readers:
            reader.start()

        captured: dict[StreamName, list[str]] = {"stdout": [], "stderr": []}
        closed_streams = 0
        timed_out = False
        was_cancelled = False
        while closed_streams < 2 or process.poll() is None:
            try:
                stream_name, line = events.get(timeout=0.05)
                if line is None:
                    closed_streams += 1
                else:
                    captured[stream_name].append(line)
                    if progress_hook:
                        progress_hook(stream_name, line.rstrip("\r\n"))
            except queue.Empty:
                pass

            if cancellation and cancellation.cancelled and process.poll() is None:
                was_cancelled = True
                process.terminate()
            if timeout_seconds is not None and time.monotonic() - start > timeout_seconds and process.poll() is None:
                timed_out = True
                process.terminate()
            if (was_cancelled or timed_out) and process.poll() is None:
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()

        for reader in readers:
            reader.join(timeout=1)
        return_code = process.wait()
        end_dt = datetime.now(UTC)
        result = CommandResult(
            command=args,
            working_directory=str(cwd),
            return_code=return_code,
            stdout="".join(captured["stdout"]),
            stderr="".join(captured["stderr"]),
            start_time=start_dt,
            end_time=end_dt,
            duration_seconds=time.monotonic() - start,
            timed_out=timed_out,
            cancelled=was_cancelled,
            environment_keys=sorted(environment or {}),
        )
        self._record(result)
        return result
