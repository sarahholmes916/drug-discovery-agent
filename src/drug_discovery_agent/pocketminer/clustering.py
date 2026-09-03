from __future__ import annotations

from math import dist

from .models import ResidueScore


def smooth_scores(scores: list[ResidueScore], *, neighbor_count: int, radius_angstrom: float) -> list[ResidueScore]:
    """Mean-smooth each residue over its nearest spatial neighbors within the configured radius."""
    if neighbor_count < 1 or radius_angstrom <= 0:
        raise ValueError("smoothing neighbor_count and radius must be positive")
    result = []
    for item in scores:
        if item.representative_coordinate is None:
            raise ValueError("residue representatives must be attached before smoothing")
        nearby = sorted(
            (
                (dist(item.representative_coordinate, other.representative_coordinate), other)
                for other in scores
                if other.representative_coordinate is not None and other is not item
                and dist(item.representative_coordinate, other.representative_coordinate) <= radius_angstrom
            ),
            key=lambda value: (value[0], value[1].residue.key),
        )[:neighbor_count]
        values = [item.score, *(other.score for _, other in nearby)]
        result.append(item.model_copy(update={"smoothed_score": sum(values) / len(values)}))
    return result


def spatial_components(
    scores: list[ResidueScore],
    *,
    threshold: float,
    edge_distance_angstrom: float,
    minimum_residues: int,
    hotspot_radius_angstrom: float | None = None,
    maximum_core_residues: int | None = None,
) -> list[list[ResidueScore]]:
    if not 0 <= threshold <= 1 or edge_distance_angstrom <= 0 or minimum_residues < 1:
        raise ValueError("invalid pocket clustering configuration")
    if (hotspot_radius_angstrom is None) != (maximum_core_residues is None):
        raise ValueError("hotspot radius and maximum core residues must be configured together")
    if hotspot_radius_angstrom is not None and (
        hotspot_radius_angstrom <= 0
        or maximum_core_residues is None
        or maximum_core_residues < minimum_residues
    ):
        raise ValueError("invalid hotspot-core configuration")
    active = sorted((item for item in scores if item.active_score >= threshold), key=lambda item: item.residue.key)
    neighbors = {index: set() for index in range(len(active))}
    for left in range(len(active)):
        first = active[left].representative_coordinate
        if first is None:
            raise ValueError("residue representatives must be attached before clustering")
        for right in range(left + 1, len(active)):
            second = active[right].representative_coordinate
            if second is not None and dist(first, second) <= edge_distance_angstrom:
                neighbors[left].add(right)
                neighbors[right].add(left)
    components = []
    unseen = set(neighbors)
    while unseen:
        seed = min(unseen)
        stack, indexes = [seed], []
        unseen.remove(seed)
        while stack:
            current = stack.pop()
            indexes.append(current)
            discovered = sorted(neighbors[current] & unseen, reverse=True)
            for value in discovered:
                unseen.remove(value)
                stack.append(value)
        component = [active[index] for index in sorted(indexes)]
        if hotspot_radius_angstrom is not None and maximum_core_residues is not None:
            seed = min(component, key=lambda item: (-item.active_score, item.residue.key))
            assert seed.representative_coordinate is not None
            component = sorted(
                (
                    item for item in component
                    if item.representative_coordinate is not None
                    and dist(seed.representative_coordinate, item.representative_coordinate)
                    <= hotspot_radius_angstrom
                ),
                key=lambda item: (
                    -item.active_score,
                    dist(seed.representative_coordinate, item.representative_coordinate),
                    item.residue.key,
                ),
            )[:maximum_core_residues]
            component.sort(key=lambda item: item.residue.key)
        if len(component) >= minimum_residues:
            components.append(component)
    return components
