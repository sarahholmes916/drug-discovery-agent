from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Mapping


@dataclass(frozen=True, slots=True)
class MetricSpec:
    name: str
    direction: Literal["higher", "lower"]
    weight: float


def rank_weighted_consensus(
    rows: Iterable[Mapping[str, object]],
    specs: Iterable[MetricSpec],
    *,
    id_field: str = "ligand_id",
) -> list[dict[str, object]]:
    """Min-max normalize configured metrics and retain every raw input value."""
    records, metrics = [dict(row) for row in rows], list(specs)
    if not metrics or any(spec.weight < 0 for spec in metrics) or sum(spec.weight for spec in metrics) <= 0:
        raise ValueError("consensus ranking requires explicit non-negative weights with a positive sum")
    ranges: dict[str, tuple[float, float]] = {}
    for spec in metrics:
        values = [float(row[spec.name]) for row in records if row.get(spec.name) is not None]
        if values:
            ranges[spec.name] = (min(values), max(values))
    weight_sum = sum(spec.weight for spec in metrics)
    output = []
    for row in records:
        contributions, weighted, present = {}, 0.0, 0.0
        for spec in metrics:
            if row.get(spec.name) is None or spec.name not in ranges:
                contributions[spec.name] = None
                continue
            low, high = ranges[spec.name]
            normalized = 0.5 if high == low else (float(row[spec.name]) - low) / (high - low)
            if spec.direction == "lower":
                normalized = 1.0 - normalized
            contribution = normalized * spec.weight
            contributions[spec.name] = contribution
            weighted += contribution
            present += spec.weight
        score = weighted / present if present else None
        output.append({**row, "consensus_score": score, "metric_contributions": contributions,
                       "configured_weight_sum": weight_sum})
    output.sort(key=lambda row: (row["consensus_score"] is None,
                                 -(row["consensus_score"] or 0), str(row.get(id_field, ""))))
    for index, row in enumerate(output, start=1):
        row["consensus_rank"] = index if row["consensus_score"] is not None else None
    return output

