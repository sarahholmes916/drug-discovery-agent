from __future__ import annotations

from .geometry import bounds_for_points, extent, rms_distance, weighted_center
from .models import CandidatePocket, PocketMetrics, ResidueScore


def rank_components(
    components: list[list[ResidueScore]],
    *,
    boxes: list[tuple],
    weights: dict[str, float],
    count_saturation: int,
    compactness_scale_angstrom: float,
) -> list[CandidatePocket]:
    required = {"mean_score", "max_score", "residue_count", "compactness"}
    if set(weights) != required or sum(weights.values()) <= 0 or any(value < 0 for value in weights.values()):
        raise ValueError(f"ranking weights must contain exactly {sorted(required)} and be non-negative")
    if len(boxes) != len(components) or count_saturation < 1 or compactness_scale_angstrom <= 0:
        raise ValueError("invalid pocket ranking inputs")
    candidates = []
    for index, (residues, box_values) in enumerate(zip(components, boxes, strict=True), start=1):
        scores = [item.active_score for item in residues]
        center = weighted_center(residues)
        points = [item.representative_coordinate for item in residues]
        if any(point is None for point in points):
            raise ValueError("ranked residues require representative coordinates")
        compactness = rms_distance(points, center)  # type: ignore[arg-type]
        spatial_extent = extent(bounds_for_points(points))  # type: ignore[arg-type]
        normalized = {
            "mean_score": sum(scores) / len(scores),
            "max_score": max(scores),
            "residue_count": min(len(residues) / count_saturation, 1.0),
            "compactness": 1.0 / (1.0 + compactness / compactness_scale_angstrom),
        }
        denominator = sum(weights.values())
        contributions = {name: weights[name] * value / denominator for name, value in normalized.items()}
        ranking_score = sum(contributions.values())
        box_center, size, bounds, atom_bounds = box_values
        candidates.append(CandidatePocket(
            pocket_id=f"component_{index}", residues=residues,
            metrics=PocketMetrics(
                mean_score=normalized["mean_score"], max_score=normalized["max_score"],
                residue_count=len(residues), compactness_angstrom=compactness,
                spatial_extent_angstrom=spatial_extent, ranking_score=ranking_score,
                ranking_contributions=contributions,
            ),
            center=box_center, size=size, bounds=bounds, atom_extent_bounds=atom_bounds,
        ))
    ordered = sorted(candidates, key=lambda item: (
        -item.metrics.ranking_score, -item.metrics.mean_score, -item.metrics.max_score,
        -item.metrics.residue_count, tuple(residue.residue.key for residue in item.residues),
    ))
    return [item.model_copy(update={"pocket_id": f"pocket_{rank}", "rank": rank}) for rank, item in enumerate(ordered, 1)]
