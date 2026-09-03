from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.runner.local_pipeline import LocalStageHandlers
from drug_discovery_agent.config.models import ProjectConfig
from drug_discovery_agent.execution.commands import CancellationToken
from drug_discovery_agent.pipeline.orchestrator import PipelineContext, PipelineOrchestrator, StageOutcome, stage_fingerprint
from drug_discovery_agent.pocketminer.box import build_box
from drug_discovery_agent.pocketminer.clustering import smooth_scores, spatial_components
from drug_discovery_agent.pocketminer.geometry import attach_representatives
from drug_discovery_agent.pocketminer.models import CandidatePocket, PocketMetrics, PocketSelectionRequest, ResidueIdentity, ResidueScore
from drug_discovery_agent.pocketminer.parser import parse_native_predictions
from drug_discovery_agent.pocketminer.ranking import rank_components
from drug_discovery_agent.pocketminer.selection import load_valid_selection, make_selection, write_selection
from drug_discovery_agent.pocketminer.visualization import write_probability_pdb
from drug_discovery_agent.project.io import atomic_write_json
from drug_discovery_agent.project.layout import create_project
from drug_discovery_agent.project.state import RunState, StageName, StageState, StageStatus, StateStore
from drug_discovery_agent.receptor.conversion import validate_coordinates


def _pdb(tmp_path: Path) -> Path:
    path = tmp_path / "receptor.pdb"
    serial, lines = 1, []
    for number, origin in [(1, (0.0, 0.0, 0.0)), (2, (3.0, 1.0, 0.0)), (3, (30.0, 0.0, 0.0)), (4, (34.0, 1.0, 0.0))]:
        for atom_name, delta, element in [
            ("N", (-1.0, 0.0, 0.0), "N"), ("CA", (0.0, 0.0, 0.0), "C"),
            ("C", (1.0, 0.0, 0.0), "C"), ("O", (1.5, 0.5, 0.0), "O"),
            ("CB", (0.0, 1.5, 0.5), "C"),
        ]:
            x, y, z = (origin[index] + delta[index] for index in range(3))
            lines.append(
                f"ATOM  {serial:5d} {atom_name:>4} ALA A{number:4d}    {x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2}  "
            )
            serial += 1
    path.write_text("\n".join([*lines, "TER", "END"]) + "\n", encoding="ascii")
    return path


def _scores(receptor: Path) -> list[ResidueScore]:
    raw = [
        ResidueScore(residue=ResidueIdentity(chain="A", residue_number=number, residue_name="ALA"), score=score)
        for number, score in [(1, .95), (2, .85), (3, .75), (4, .65)]
    ]
    return attach_representatives(raw, receptor)


def _candidate(receptor: Path) -> CandidatePocket:
    residues = _scores(receptor)[:2]
    center, size, bounds, atom_bounds = build_box(
        residues, receptor, padding_angstrom=2, minimum_size=(4, 5, 6), maximum_size=(30, 30, 30),
    )
    return rank_components(
        [residues], boxes=[(center, size, bounds, atom_bounds)],
        weights={"mean_score": .4, "max_score": .2, "residue_count": .2, "compactness": .2},
        count_saturation=10, compactness_scale_angstrom=8,
    )[0]


def test_native_parser_maps_scores_to_exact_receptor_identity(tmp_path: Path) -> None:
    receptor = _pdb(tmp_path)
    predictions = tmp_path / "predictions.txt"
    predictions.write_text("0.1\n0.2\n0.3\n0.4\n", encoding="utf-8")
    scores = parse_native_predictions(predictions, receptor)
    assert scores[1].residue.key == ("A", 2, "", "ALA")
    assert scores[1].score == .2
    predictions.write_text("0.1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="score count"):
        parse_native_predictions(predictions, receptor)


def test_spatial_clustering_and_smoothing_are_deterministic(tmp_path: Path) -> None:
    scores = _scores(_pdb(tmp_path))
    smoothed = smooth_scores(scores, neighbor_count=1, radius_angstrom=6)
    assert smoothed[0].smoothed_score == pytest.approx(.9)
    components = spatial_components(smoothed, threshold=.6, edge_distance_angstrom=6, minimum_residues=2)
    assert [[item.residue.residue_number for item in group] for group in components] == [[1, 2], [3, 4]]


def test_large_connected_component_is_localized_around_highest_score() -> None:
    scores = [
        ResidueScore(
            residue=ResidueIdentity(chain="A", residue_number=number, residue_name="ALA"),
            score=score,
            representative_coordinate=(x, 0.0, 0.0),
            representative_method="ca",
        )
        for number, x, score in [
            (1, 0.0, .99), (2, 3.0, .70), (3, 6.0, .65), (4, 9.0, .80),
        ]
    ]

    components = spatial_components(
        scores,
        threshold=.5,
        edge_distance_angstrom=4,
        minimum_residues=2,
        hotspot_radius_angstrom=4,
        maximum_core_residues=12,
    )

    assert [[item.residue.residue_number for item in group] for group in components] == [[1, 2]]


def test_box_is_score_weighted_non_cubic_and_ranking_exposes_metrics(tmp_path: Path) -> None:
    receptor = _pdb(tmp_path)
    residues = _scores(receptor)[:2]
    center, size, bounds, atom_bounds = build_box(
        residues, receptor, padding_angstrom=2, minimum_size=(4, 5, 6), maximum_size=(30, 30, 30),
    )
    assert center[0] < 1.5
    assert size[1] != size[2]
    ranked = rank_components(
        [residues], boxes=[(center, size, bounds, atom_bounds)],
        weights={"mean_score": .4, "max_score": .2, "residue_count": .2, "compactness": .2},
        count_saturation=10, compactness_scale_angstrom=8,
    )
    assert ranked[0].pocket_id == "pocket_1"
    assert set(ranked[0].metrics.ranking_contributions) == {"mean_score", "max_score", "residue_count", "compactness"}


def test_colored_pdb_preserves_coordinates_and_stores_probability(tmp_path: Path) -> None:
    receptor = _pdb(tmp_path)
    output = tmp_path / "colored.pdb"
    write_probability_pdb(receptor, _scores(receptor), output)
    assert validate_coordinates(receptor, output).coordinate_identity_verified
    atom_line = next(line for line in output.read_text().splitlines() if line.startswith("ATOM"))
    assert float(atom_line[60:66]) == pytest.approx(.95)


def test_colored_pdb_uses_the_same_smoothed_score_as_candidate_detection(tmp_path: Path) -> None:
    receptor = _pdb(tmp_path)
    scores = [item.model_copy(update={"smoothed_score": .25}) for item in _scores(receptor)]
    output = tmp_path / "colored-smoothed.pdb"

    write_probability_pdb(receptor, scores, output)

    atom_line = next(line for line in output.read_text().splitlines() if line.startswith("ATOM"))
    assert float(atom_line[60:66]) == pytest.approx(.25)


def test_selection_persists_until_receptor_or_config_changes(tmp_path: Path) -> None:
    receptor, candidate = _pdb(tmp_path), None
    candidate = _candidate(receptor)
    config = {"threshold": .5}
    selected = make_selection(PocketSelectionRequest(candidate_id="pocket_1"), candidates=[candidate], receptor=receptor, pocketminer_config=config)
    path = tmp_path / "selected.json"
    write_selection(selected, path)
    assert load_valid_selection(path, candidates=[candidate], receptor=receptor, pocketminer_config=config) == selected
    assert load_valid_selection(path, candidates=[candidate], receptor=receptor, pocketminer_config={"threshold": .7}) is None
    receptor.write_text(receptor.read_text() + "REMARK changed\n", encoding="ascii")
    assert load_valid_selection(path, candidates=[candidate], receptor=receptor, pocketminer_config=config) is None


def test_custom_manual_box_derives_residues_for_boltz(tmp_path: Path) -> None:
    receptor = _pdb(tmp_path)
    selected = make_selection(
        PocketSelectionRequest(center=(1.0, 0.5, 0.0), size=(10.0, 10.0, 10.0)),
        candidates=[_candidate(receptor)], receptor=receptor, pocketminer_config={},
    )
    assert selected.source == "manual"
    assert {item.residue.residue_number for item in selected.residues} == {1, 2}


def test_pocketminer_gate_pauses_even_with_one_candidate(tmp_path: Path) -> None:
    config = ProjectConfig.model_validate({
        "project": {"id": "gate"}, "workflow": "custom",
        "custom_stages": ["AWAIT_POCKET_SELECTION"],
        "target": {"receptor_ref": "receptor"},
        "pocket": {"mode": "pocketminer"},
        "ligands": [{"source_ref": "ligands", "kind": "multi_sdf"}],
    })
    receptor = _pdb(tmp_path)
    ligands = tmp_path / "ligands.sdf"; ligands.write_text("$$$$\n")
    layout = create_project(tmp_path / "projects", config, {"receptor": receptor, "ligands": ligands})
    atomic_write_json(layout.root / "pocketminer" / "candidates" / "ranked_pockets.json", {"candidates": [_candidate(receptor).model_dump(mode="json")]})
    state = RunState(run_id="run_gate", project_id="gate"); store = StateStore(layout.run_state, layout.root); store.save(state)
    context = PipelineContext(config=config, layout=layout, run_state=state, state_store=store, cancellation=CancellationToken(), local_references={"receptor": receptor, "ligands": ligands})
    result = PipelineOrchestrator({StageName.AWAIT_POCKET_SELECTION: LocalStageHandlers().await_pocket_selection}).run(context)
    assert result.status == StageStatus.AWAITING_USER_SELECTION
    assert not (layout.state / "selected_pocket.json").exists()


def test_vina_box_comes_only_from_selected_pocket(tmp_path: Path) -> None:
    receptor = _pdb(tmp_path); candidate = _candidate(receptor)
    config = ProjectConfig.model_validate({
        "project": {"id": "downstream"}, "workflow": "vina_only",
        "target": {"receptor_ref": "receptor", "receptor_pdbqt_ref": "pdbqt"},
        "pocket": {"mode": "pocketminer"},
        "ligands": [{"source_ref": "ligands", "kind": "multi_sdf"}], "vina": {"enabled": True},
    })
    layout = create_project(tmp_path / "projects", config, {"receptor": receptor, "pdbqt": receptor, "ligands": receptor})
    selected = make_selection(PocketSelectionRequest(candidate_id="pocket_1", center=(2, 3, 4), size=(9, 10, 11)), candidates=[candidate], receptor=receptor, pocketminer_config=config.pocketminer.model_dump(mode="json"))
    write_selection(selected, layout.state / "selected_pocket.json")
    state = RunState(run_id="run", project_id="downstream"); store = StateStore(layout.run_state, layout.root); store.save(state)
    context = PipelineContext(config=config, layout=layout, run_state=state, state_store=store, cancellation=CancellationToken(), local_references={})
    assert LocalStageHandlers._active_pocket_box(context) == ((2, 3, 4), (9, 10, 11))


def test_selected_pocket_invalidates_constrained_boltz_but_not_unconstrained(tmp_path: Path) -> None:
    receptor = _pdb(tmp_path); ligands = tmp_path / "ligands.sdf"; ligands.write_text("$$$$\n")
    config = ProjectConfig.model_validate({
        "project": {"id": "branches"}, "workflow": "vina_to_both_boltz",
        "target": {"receptor_ref": "receptor", "receptor_pdbqt_ref": "pdbqt", "receptor_template_ref": "template", "protein_sequence": "AAAA"},
        "pocket": {"mode": "pocketminer"},
        "ligands": [{"source_ref": "ligands", "kind": "multi_sdf"}], "vina": {"enabled": True},
        "boltz": {"constrained": {"enabled": True}, "unconstrained": {"enabled": True}},
    })
    refs = {"receptor": receptor, "pdbqt": receptor, "template": receptor, "ligands": ligands}
    layout = create_project(tmp_path / "projects", config, refs)
    state = RunState(run_id="run", project_id="branches", stages={
        StageName.DEFINE_OR_IMPORT_POCKET: StageState(name=StageName.DEFINE_OR_IMPORT_POCKET, status=StageStatus.SUCCESS, input_hash="pocket-a"),
        StageName.SHORTLIST_VINA: StageState(name=StageName.SHORTLIST_VINA, status=StageStatus.SUCCESS, input_hash="shortlist"),
        StageName.PREPARE_RECEPTOR: StageState(name=StageName.PREPARE_RECEPTOR, status=StageStatus.SUCCESS, input_hash="receptor"),
    })
    store = StateStore(layout.run_state, layout.root); store.save(state)
    context = PipelineContext(config=config, layout=layout, run_state=state, state_store=store, cancellation=CancellationToken(), local_references=refs)
    selected = {StageName.DEFINE_OR_IMPORT_POCKET, StageName.SHORTLIST_VINA, StageName.PREPARE_RECEPTOR, StageName.PREPARE_BOLTZ_CONSTRAINED, StageName.PREPARE_BOLTZ_UNCONSTRAINED}
    constrained_before = stage_fingerprint(context, StageName.PREPARE_BOLTZ_CONSTRAINED, selected)
    unconstrained_before = stage_fingerprint(context, StageName.PREPARE_BOLTZ_UNCONSTRAINED, selected)
    context.run_state.stages[StageName.DEFINE_OR_IMPORT_POCKET].input_hash = "pocket-b"
    assert stage_fingerprint(context, StageName.PREPARE_BOLTZ_CONSTRAINED, selected) != constrained_before
    assert stage_fingerprint(context, StageName.PREPARE_BOLTZ_UNCONSTRAINED, selected) == unconstrained_before
