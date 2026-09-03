from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from drug_discovery_agent.execution.commands import CancellationToken, CommandExecutor, CommandResult
from drug_discovery_agent.execution.scheduler import BoundedScheduler


class PLIPModel(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class PLIPJob(PLIPModel):
    ligand_id: str
    model_index: int
    structure: Path
    output_directory: Path


class PLIPResult(PLIPModel):
    ligand_id: str
    model_index: int
    status: str
    report_xml: Path | None = None
    interactions: list[dict[str, str]] = Field(default_factory=list)
    command: CommandResult | None = None
    error: str | None = None


def parse_plip_xml(path: str | Path) -> list[dict[str, str]]:
    """Parse interaction nodes while retaining the native PLIP field names."""
    root = ET.parse(path).getroot()
    rows = []
    interaction_groups = {
        "hydrophobic_interactions", "hydrogen_bonds", "salt_bridges",
        "pi_stacks", "pi_cation_interactions", "halogen_bonds",
    }
    for group in root.iter():
        group_name = group.tag.rsplit("}", 1)[-1]
        if group_name not in interaction_groups:
            continue
        for interaction in list(group):
            row = {"interaction_type": interaction.tag.rsplit("}", 1)[-1]}
            for child in list(interaction):
                if len(list(child)) == 0:
                    row[child.tag.rsplit("}", 1)[-1]] = child.text or ""
            rows.append(row)
    return rows


def run_plip_job(
    job: PLIPJob,
    *,
    executor: CommandExecutor | None = None,
    cancellation: CancellationToken | None = None,
    timeout_seconds: float | None = None,
    environment: Mapping[str, str] | None = None,
) -> PLIPResult:
    if not job.structure.is_file():
        return PLIPResult(ligand_id=job.ligand_id, model_index=job.model_index,
                          status="FAILED", error="structure file not found")
    job.output_directory.mkdir(parents=True, exist_ok=True)
    command = (executor or CommandExecutor()).run(
        ["plip", "-f", str(job.structure), "-x", "-t", "-o", str(job.output_directory)],
        working_directory=job.output_directory,
        environment=environment,
        cancellation=cancellation,
        timeout_seconds=timeout_seconds,
    )
    if not command.successful:
        return PLIPResult(ligand_id=job.ligand_id, model_index=job.model_index,
                          status="FAILED", command=command,
                          error=f"PLIP failed with exit code {command.return_code}: {command.stderr.strip()}")
    reports = sorted(job.output_directory.glob("*.xml"))
    if not reports:
        return PLIPResult(ligand_id=job.ligand_id, model_index=job.model_index,
                          status="NEEDS_REVIEW", command=command, error="PLIP produced no XML report")
    try:
        interactions = parse_plip_xml(reports[0])
    except (ET.ParseError, OSError) as exc:
        return PLIPResult(ligand_id=job.ligand_id, model_index=job.model_index,
                          status="NEEDS_REVIEW", report_xml=reports[0], command=command, error=str(exc))
    return PLIPResult(ligand_id=job.ligand_id, model_index=job.model_index,
                      status="SUCCESS", report_xml=reports[0], interactions=interactions, command=command)


def run_plip_jobs(
    jobs: Iterable[PLIPJob],
    *,
    executor: CommandExecutor | None = None,
    cancellation: CancellationToken | None = None,
    timeout_seconds: float | None = None,
    max_workers: int = 1,
    environment: Mapping[str, str] | None = None,
) -> list[PLIPResult]:
    """Run compound x model jobs independently so one failure cannot erase a batch."""
    executor = executor or CommandExecutor()
    return BoundedScheduler(max_workers).map(
        lambda job: run_plip_job(job, executor=executor, cancellation=cancellation,
                                 timeout_seconds=timeout_seconds, environment=environment),
        jobs,
    )
