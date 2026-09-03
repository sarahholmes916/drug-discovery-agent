from __future__ import annotations

from dataclasses import asdict, dataclass
from math import dist, prod

from .models import CandidatePocket, PocketBounds, Vector3


@dataclass(frozen=True, slots=True)
class PocketReferenceComparison:
    pocket_id: str
    center_distance_angstrom: float
    box_intersection_over_union: float
    shared_hotspot: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def box_from_center_size(center: Vector3, size: Vector3) -> PocketBounds:
    return PocketBounds(
        minimum=tuple(center[axis] - size[axis] / 2 for axis in range(3)),
        maximum=tuple(center[axis] + size[axis] / 2 for axis in range(3)),
    )


def box_iou(first: PocketBounds, second: PocketBounds) -> float:
    intersection_axes = [
        max(0.0, min(first.maximum[axis], second.maximum[axis]) - max(first.minimum[axis], second.minimum[axis]))
        for axis in range(3)
    ]
    intersection = intersection_axes[0] * intersection_axes[1] * intersection_axes[2]
    first_volume = prod(first.maximum[axis] - first.minimum[axis] for axis in range(3))
    second_volume = prod(second.maximum[axis] - second.minimum[axis] for axis in range(3))
    union = first_volume + second_volume - intersection
    return intersection / union if union > 0 else 0.0


def compare_with_reference(
    candidate: CandidatePocket,
    *,
    reference_center: Vector3,
    reference_size: Vector3,
) -> PocketReferenceComparison:
    reference = box_from_center_size(reference_center, reference_size)
    shared_hotspot = any(
        item.representative_coordinate is not None
        and all(
            reference.minimum[axis] <= item.representative_coordinate[axis] <= reference.maximum[axis]
            for axis in range(3)
        )
        for item in candidate.residues
    )
    return PocketReferenceComparison(
        pocket_id=candidate.pocket_id,
        center_distance_angstrom=dist(candidate.center, reference_center),
        box_intersection_over_union=box_iou(candidate.bounds, reference),
        shared_hotspot=shared_hotspot,
    )
