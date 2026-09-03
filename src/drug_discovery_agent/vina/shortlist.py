from __future__ import annotations

from typing import Iterable, Literal

from .models import VinaResult


SelectionMetric = Literal["best_affinity", "mean_affinity", "ligand_efficiency"]
MAX_DOWNSTREAM_LIGANDS = 50


def _selection_values(result: VinaResult) -> tuple[float | None, float | None, float | None]:
    affinities = [mode.affinity_kcal_mol for mode in result.modes]
    mean_affinity = (
        sum(affinities) / len(affinities)
        if affinities else result.best_affinity_kcal_mol
    )
    efficiency = (
        result.best_affinity_kcal_mol / result.heavy_atom_count
        if result.best_affinity_kcal_mol is not None and result.heavy_atom_count
        else None
    )
    return result.best_affinity_kcal_mol, mean_affinity, efficiency


def rank_vina_results(
    results: Iterable[VinaResult],
    metric: SelectionMetric = "best_affinity",
) -> list[VinaResult]:
    if metric not in {"best_affinity", "mean_affinity", "ligand_efficiency"}:
        raise ValueError(f"unsupported Vina selection metric: {metric}")
    candidates: list[tuple[VinaResult, float | None]] = []
    for result in results:
        if result.status != "SUCCESS" or result.best_affinity_kcal_mol is None:
            continue
        best, mean, efficiency = _selection_values(result)
        values = {
            "best_affinity": best,
            "mean_affinity": mean,
            "ligand_efficiency": efficiency,
        }
        enriched = result.model_copy(update={
            "mean_affinity_kcal_mol": mean,
            "ligand_efficiency_kcal_mol_per_heavy_atom": efficiency,
            "selection_metric": metric,
            "selection_value": values[metric],
            "selection_rank": None,
            "selected_for_downstream": False,
        })
        candidates.append((enriched, values[metric]))
    candidates.sort(key=lambda item: (
        item[1] is None,
        item[1] if item[1] is not None else float("inf"),
        item[0].ligand_id,
    ))
    ranked = []
    rank = 0
    for result, value in candidates:
        if value is not None:
            rank += 1
        ranked.append(result.model_copy(update={"selection_rank": rank if value is not None else None}))
    return ranked


def shortlist_vina(
    results: Iterable[VinaResult],
    size: int,
    metric: SelectionMetric = "best_affinity",
) -> list[VinaResult]:
    if not 1 <= size <= MAX_DOWNSTREAM_LIGANDS:
        raise ValueError(f"shortlist size must be between 1 and {MAX_DOWNSTREAM_LIGANDS}")
    return [
        item.model_copy(update={"selected_for_downstream": True})
        for item in rank_vina_results(results, metric)
        if item.selection_rank is not None and item.selection_rank <= size
    ]
