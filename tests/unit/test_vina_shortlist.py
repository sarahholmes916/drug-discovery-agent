from __future__ import annotations

import pytest

from drug_discovery_agent.vina.models import VinaMode, VinaResult
from drug_discovery_agent.vina.shortlist import rank_vina_results, shortlist_vina


def result(ligand_id: str, affinities: list[float], heavy_atoms: int) -> VinaResult:
    return VinaResult(
        ligand_id=ligand_id,
        status="SUCCESS",
        best_affinity_kcal_mol=affinities[0],
        heavy_atom_count=heavy_atoms,
        modes=[
            VinaMode(mode=index, affinity_kcal_mol=value, rmsd_lb=0.0, rmsd_ub=0.0)
            for index, value in enumerate(affinities, start=1)
        ],
    )


def test_vina_gate_can_rank_by_each_supported_metric() -> None:
    large_strong = result("large_strong", [-9.0, -4.0], 30)
    small_consistent = result("small_consistent", [-8.0, -7.5], 10)

    assert shortlist_vina([large_strong, small_consistent], 1)[0].ligand_id == "large_strong"
    assert shortlist_vina(
        [large_strong, small_consistent], 1, "mean_affinity"
    )[0].ligand_id == "small_consistent"
    efficient = shortlist_vina(
        [large_strong, small_consistent], 1, "ligand_efficiency"
    )[0]
    assert efficient.ligand_id == "small_consistent"
    assert efficient.selected_for_downstream is True
    assert efficient.selection_rank == 1


def test_full_vina_ranking_is_retained_beyond_the_downstream_subset() -> None:
    results = [result(f"ligand_{index}", [-float(index)], 10) for index in range(1, 4)]
    ranked = rank_vina_results(results)
    selected = shortlist_vina(results, 2)

    assert len(ranked) == 3
    assert len(selected) == 2
    assert [item.selection_rank for item in ranked] == [1, 2, 3]
    assert {item.ligand_id for item in selected} == {"ligand_2", "ligand_3"}


def test_vina_gate_enforces_the_fifty_ligand_maximum() -> None:
    with pytest.raises(ValueError, match="between 1 and 50"):
        shortlist_vina([result("ligand", [-7.0], 10)], 51)
