from __future__ import annotations

import csv
import json
from pathlib import Path

from drug_discovery_agent.receptor.mapping import receptor_residues

from .models import ResidueIdentity, ResidueScore


def _ordered_receptor(path: str | Path) -> list[ResidueIdentity]:
    return [
        ResidueIdentity(chain=chain, residue_number=number, insertion_code=insertion, residue_name=name)
        for chain, number, insertion, name in receptor_residues(path)
    ]


def parse_native_predictions(predictions: str | Path, receptor: str | Path) -> list[ResidueScore]:
    """Parse the official one-number-per-residue PocketMiner text or NPY output."""
    source = Path(predictions)
    if source.suffix.lower() == ".npy":
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("NumPy is required to parse PocketMiner .npy output") from exc
        raw = np.asarray(np.load(source, allow_pickle=False)).reshape(-1).tolist()
    else:
        raw = [float(line.strip()) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    residues = _ordered_receptor(receptor)
    if len(raw) != len(residues):
        raise ValueError(
            f"PocketMiner score count does not match receptor residues: scores={len(raw)} residues={len(residues)}"
        )
    return [ResidueScore(residue=residue, score=float(score)) for residue, score in zip(residues, raw, strict=True)]


def parse_normalized_scores(path: str | Path) -> list[ResidueScore]:
    source = Path(path)
    if source.suffix.lower() == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        rows = payload.get("residues") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("score JSON must be a list or contain a residues list")
        result = [ResidueScore.model_validate(row) for row in rows]
    elif source.suffix.lower() == ".csv":
        result = []
        with source.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                result.append(ResidueScore(
                    residue=ResidueIdentity(
                        chain=row["chain"], residue_number=int(row["residue_number"]),
                        insertion_code=row.get("insertion_code", ""), residue_name=row["residue_name"],
                    ),
                    score=float(row["score"]),
                    smoothed_score=float(row["smoothed_score"]) if row.get("smoothed_score") else None,
                ))
    else:
        raise ValueError(f"unsupported normalized score format: {source.suffix}")
    keys = [item.residue.key for item in result]
    if len(keys) != len(set(keys)):
        raise ValueError("score artifact contains duplicate residue identities")
    return result


def write_normalized_scores(scores: list[ResidueScore], json_path: str | Path, csv_path: str | Path) -> None:
    json_target, csv_target = Path(json_path), Path(csv_path)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "residues": [item.model_dump(mode="json") for item in scores]}
    temporary = json_target.with_name(f".{json_target.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(json_target)
    csv_target.parent.mkdir(parents=True, exist_ok=True)
    temporary = csv_target.with_name(f".{csv_target.name}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        fields = ["chain", "residue_number", "insertion_code", "residue_name", "score", "smoothed_score"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in scores:
            writer.writerow({
                **item.residue.model_dump(mode="json"), "score": item.score,
                "smoothed_score": "" if item.smoothed_score is None else item.smoothed_score,
            })
    temporary.replace(csv_target)
