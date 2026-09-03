from __future__ import annotations

import sys
from pathlib import Path

from drug_discovery_agent.execution.commands import CommandExecutor


def test_executor_captures_structured_command_result(tmp_path: Path) -> None:
    events = []
    result = CommandExecutor().run(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
        working_directory=tmp_path,
        progress_hook=lambda stream, line: events.append((stream, line)),
    )
    assert result.successful
    assert result.command[0] == sys.executable
    assert result.working_directory == str(tmp_path.resolve())
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    assert ("stdout", "out") in events and ("stderr", "err") in events


def test_missing_executable_is_a_structured_failure(tmp_path: Path) -> None:
    result = CommandExecutor(tmp_path / "records").run(
        ["definitely-not-a-real-scientific-tool-7f31a9"], working_directory=tmp_path
    )
    assert not result.successful
    assert result.return_code == 127
    assert "could not start" in result.stderr
    assert len(list((tmp_path / "records").glob("command_*.json"))) == 1
