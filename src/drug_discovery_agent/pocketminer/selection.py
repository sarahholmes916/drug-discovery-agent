from __future__ import annotations

from pathlib import Path

from drug_discovery_agent.project.hashing import sha256_file, stable_json_hash
from drug_discovery_agent.project.io import atomic_write_json, read_json

from .geometry import residues_inside_box
from .models import CandidatePocket, PocketBounds, PocketDefinition, PocketSelectionRequest, ResidueScore


def candidate_set_hash(candidates: list[CandidatePocket]) -> str:
    return stable_json_hash([item.model_dump(mode="json") for item in candidates])


def _bounds(center: tuple[float, float, float], size: tuple[float, float, float]) -> PocketBounds:
    return PocketBounds(
        minimum=tuple(center[axis] - size[axis] / 2 for axis in range(3)),
        maximum=tuple(center[axis] + size[axis] / 2 for axis in range(3)),
    )


def make_selection(
    request: PocketSelectionRequest,
    *,
    candidates: list[CandidatePocket],
    receptor: str | Path,
    pocketminer_config: object,
    scores: list[ResidueScore] | None = None,
) -> PocketDefinition:
    by_id = {item.pocket_id: item for item in candidates}
    candidate = by_id.get(request.candidate_id) if request.candidate_id else None
    if request.candidate_id and candidate is None:
        raise ValueError(f"unknown PocketMiner candidate: {request.candidate_id}")
    config_hash = stable_json_hash(pocketminer_config)
    set_hash = candidate_set_hash(candidates)
    if candidate:
        original_center, original_size, original_bounds = candidate.center, candidate.size, candidate.bounds
        final_center = request.center or candidate.center
        final_size = request.size or candidate.size
        score_map = {item.residue.key: item for item in candidate.residues}
        residues = candidate.residues
        if request.residues:
            missing = [item.key for item in request.residues if item.key not in score_map]
            if missing:
                raise ValueError(f"manual residue selection contains residues outside the candidate: {missing[:3]}")
            residues = [score_map[item.key] for item in request.residues]
        elif request.center is not None:
            all_scores = {score.residue.key: score for score in (scores or [])}
            all_scores.update({score.residue.key: score for pocket in candidates for score in pocket.residues})
            residues = residues_inside_box(receptor, center=final_center, size=final_size, scores=all_scores)
        source, pocket_id, metrics = "pocketminer", candidate.pocket_id, candidate.metrics
    else:
        assert request.center is not None and request.size is not None
        original_center, original_size = request.center, request.size
        original_bounds = _bounds(request.center, request.size)
        final_center, final_size = request.center, request.size
        all_scores = {score.residue.key: score for score in (scores or [])}
        all_scores.update({score.residue.key: score for pocket in candidates for score in pocket.residues})
        residues = residues_inside_box(receptor, center=final_center, size=final_size, scores=all_scores)
        if request.residues:
            selected_keys = {item.key for item in request.residues}
            inside = {item.residue.key: item for item in residues}
            absent = selected_keys - set(inside)
            if absent:
                raise ValueError(f"manual residues are absent from the manual box: {sorted(absent)[:3]}")
            residues = [inside[item.key] for item in request.residues]
        source, pocket_id, metrics = "manual", "manual_pocket", None
    final_bounds = _bounds(final_center, final_size)
    return PocketDefinition(
        pocket_id=pocket_id,
        source=source,
        residues=residues,
        metrics=metrics,
        original_center=original_center,
        original_size=original_size,
        original_bounds=original_bounds,
        final_center=final_center,
        final_size=final_size,
        final_bounds=final_bounds,
        manual_box_edit=(final_center != original_center or final_size != original_size),
        candidate_set_hash=set_hash,
        receptor_sha256=sha256_file(receptor),
        pocketminer_config_hash=config_hash,
    )


def write_selection(selection: PocketDefinition, path: str | Path) -> None:
    atomic_write_json(path, selection.model_dump(mode="json"))


def load_valid_selection(
    path: str | Path,
    *,
    candidates: list[CandidatePocket],
    receptor: str | Path,
    pocketminer_config: object,
) -> PocketDefinition | None:
    payload = read_json(path)
    if payload is None:
        return None
    try:
        selection = PocketDefinition.model_validate(payload)
    except ValueError:
        return None
    if (
        selection.candidate_set_hash != candidate_set_hash(candidates)
        or selection.receptor_sha256 != sha256_file(receptor)
        or selection.pocketminer_config_hash != stable_json_hash(pocketminer_config)
    ):
        return None
    return selection
