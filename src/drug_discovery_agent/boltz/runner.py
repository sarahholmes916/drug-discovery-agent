from __future__ import annotations

import platform
from pathlib import Path

from drug_discovery_agent.config.models import BoltzConfig
from drug_discovery_agent.execution.commands import CancellationToken, CommandExecutor, CommandResult


def boltz_execution_error(result: CommandResult) -> str | None:
    """Return an error even when Boltz exits zero after skipping an invalid input."""
    if not result.successful:
        return (result.stderr or result.stdout or "Boltz failed").strip()
    combined = "\n".join(value for value in (result.stdout, result.stderr) if value)
    if "Failed to process" not in combined or "Skipping." not in combined:
        return None
    marker = "Error:"
    detail = combined.rsplit(marker, 1)[-1].strip() if marker in combined else combined.strip()
    return f"Boltz skipped the input instead of predicting it: {detail[-2000:]}"


def build_boltz_command(inputs: str | Path, output_directory: str | Path, config: BoltzConfig) -> list[str]:
    if platform.system() == "Darwin" and config.accelerator != "cpu":
        raise ValueError(
            "Pinned Boltz 2.2.1 does not support MPS or CUDA on macOS. "
            "Select boltz.accelerator: cpu explicitly to try the unverified, slow CPU path."
        )
    command = ["boltz", "predict", str(inputs), "--out_dir", str(output_directory)]
    if config.use_potentials:
        command.append("--use_potentials")
    command.extend([
        "--recycling_steps", str(config.recycling_steps),
        "--sampling_steps", str(config.sampling_steps),
        "--diffusion_samples", str(config.diffusion_samples),
        "--output_format", config.output_format,
        "--accelerator", config.accelerator,
        "--devices", config.devices,
    ])
    if config.override:
        command.append("--override")
    if config.use_msa_server:
        command.append("--use_msa_server")
    # Boltz's optional cuequivariance CUDA extension is not published for
    # Windows. Its supported fallback still runs on the GPU through PyTorch.
    if platform.system() in {"Windows", "Darwin"} or config.accelerator == "cpu":
        command.append("--no_kernels")
    return command


def run_boltz(
    inputs: str | Path,
    output_directory: str | Path,
    config: BoltzConfig,
    *,
    executor: CommandExecutor | None = None,
    cancellation: CancellationToken | None = None,
    timeout_seconds: float | None = None,
) -> CommandResult:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    return (executor or CommandExecutor()).run(
        build_boltz_command(inputs, output, config), working_directory=output,
        cancellation=cancellation, timeout_seconds=timeout_seconds,
    )
