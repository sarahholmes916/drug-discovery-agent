from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


MODEL_NUMBER = re.compile(r"_model_(\d+)\.(?:pdb|cif|mmcif)$", re.IGNORECASE)


class BoltzModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_index: int
    structure: str
    confidence_json: str | None = None
    confidence_score: float | None = None
    ptm: float | None = None
    iptm: float | None = None
    ligand_iptm: float | None = None
    protein_iptm: float | None = None
    complex_plddt: float | None = None
    complex_iplddt: float | None = None
    complex_pde: float | None = None
    complex_ipde: float | None = None
    chains_ptm: dict[str, float] = Field(default_factory=dict)
    pair_chains_iptm: dict[str, dict[str, float]] = Field(default_factory=dict)


class BoltzPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ligand_id: str
    mode: str
    affinity_json: str | None = None
    affinity_pred_value: float | None = None
    affinity_probability_binary: float | None = None
    affinity_pred_value1: float | None = None
    affinity_probability_binary1: float | None = None
    affinity_pred_value2: float | None = None
    affinity_probability_binary2: float | None = None
    models: list[BoltzModel] = Field(default_factory=list)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def parse_prediction_directory(
    directory: str | Path,
    *,
    ligand_id: str,
    mode: str,
) -> BoltzPrediction:
    root = Path(directory)
    affinity_files = sorted(root.glob("affinity_*.json"))
    if len(affinity_files) > 1:
        raise ValueError(f"ambiguous affinity files in {root}")
    affinity = _load_json(affinity_files[0]) if affinity_files else {}
    structures: dict[int, Path] = {}
    for path in [*root.glob("*.pdb"), *root.glob("*.cif"), *root.glob("*.mmcif")]:
        match = MODEL_NUMBER.search(path.name)
        if match:
            model_index = int(match.group(1))
            if model_index in structures:
                raise ValueError(f"multiple structures for Boltz model {model_index} in {root}")
            structures[model_index] = path
    models = []
    for model_index, structure in sorted(structures.items()):
        candidates = list(root.glob(f"confidence_*_model_{model_index}.json"))
        if len(candidates) > 1:
            raise ValueError(f"ambiguous confidence JSON for model {model_index}")
        confidence_path = candidates[0] if candidates else None
        confidence = _load_json(confidence_path) if confidence_path else {}
        metrics = {
            name: confidence.get(name) for name in (
                "confidence_score", "ptm", "iptm", "ligand_iptm", "protein_iptm",
                "complex_plddt", "complex_iplddt", "complex_pde", "complex_ipde",
            )
        }
        models.append(
            BoltzModel(
                model_index=model_index, structure=str(structure),
                confidence_json=str(confidence_path) if confidence_path else None,
                chains_ptm=confidence.get("chains_ptm", {}),
                pair_chains_iptm=confidence.get("pair_chains_iptm", {}),
                **metrics,
            )
        )
    return BoltzPrediction(
        ligand_id=ligand_id, mode=mode,
        affinity_json=str(affinity_files[0]) if affinity_files else None,
        models=models,
        **{name: affinity.get(name) for name in (
            "affinity_pred_value", "affinity_probability_binary",
            "affinity_pred_value1", "affinity_probability_binary1",
            "affinity_pred_value2", "affinity_probability_binary2",
        )},
    )

