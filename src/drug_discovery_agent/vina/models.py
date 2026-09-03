from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from drug_discovery_agent.execution.commands import CommandResult


class VinaModel(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class VinaMode(VinaModel):
    mode: int
    affinity_kcal_mol: float
    rmsd_lb: float
    rmsd_ub: float


class VinaResult(VinaModel):
    ligand_id: str
    status: str
    output_pdbqt: Path | None = None
    best_affinity_kcal_mol: float | None = None
    seed: int | None = None
    modes: list[VinaMode] = Field(default_factory=list)
    mean_affinity_kcal_mol: float | None = None
    heavy_atom_count: int | None = Field(default=None, ge=1)
    ligand_efficiency_kcal_mol_per_heavy_atom: float | None = None
    selection_metric: str | None = None
    selection_value: float | None = None
    selection_rank: int | None = Field(default=None, ge=1)
    selected_for_downstream: bool = False
    command: CommandResult | None = None
    error: str | None = None
