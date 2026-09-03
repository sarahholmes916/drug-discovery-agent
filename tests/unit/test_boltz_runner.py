from __future__ import annotations

from datetime import UTC, datetime

from drug_discovery_agent.boltz.runner import (
    boltz_execution_error,
    build_boltz_command,
)
from drug_discovery_agent.config.models import BoltzConfig
from drug_discovery_agent.execution.commands import CommandResult


def _result(*, stdout: str = "", stderr: str = "", return_code: int = 0) -> CommandResult:
    now = datetime.now(UTC)
    return CommandResult(
        command=["boltz", "predict", "input.yaml"],
        working_directory=".",
        return_code=return_code,
        stdout=stdout,
        stderr=stderr,
        start_time=now,
        end_time=now,
        duration_seconds=0.0,
    )


def test_windows_boltz_command_preserves_legacy_flags_and_disables_unavailable_kernels(
    monkeypatch,
) -> None:
    monkeypatch.setattr("drug_discovery_agent.boltz.runner.platform.system", lambda: "Windows")
    command = build_boltz_command("input.yaml", "results", BoltzConfig())

    assert "--use_msa_server" in command
    assert "--override" in command
    assert "--no_kernels" in command


def test_linux_boltz_command_keeps_optimized_kernels(monkeypatch) -> None:
    monkeypatch.setattr("drug_discovery_agent.boltz.runner.platform.system", lambda: "Linux")

    command = build_boltz_command("input.yaml", "results", BoltzConfig())

    assert "--no_kernels" not in command


def test_zero_exit_after_boltz_skips_input_is_a_failure() -> None:
    result = _result(
        stdout=(
            "Checking input data.\n"
            "Failed to process input.yaml. Skipping. "
            "Error: Missing MSA's in input and --use_msa_server flag not set.\n"
        ),
    )

    error = boltz_execution_error(result)

    assert error is not None
    assert "Missing MSA" in error


def test_successful_boltz_output_has_no_execution_error() -> None:
    assert boltz_execution_error(_result(stdout="Predicting 1 structure.\n")) is None
