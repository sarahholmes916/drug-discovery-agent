from __future__ import annotations

from pathlib import Path

from drug_discovery_agent.project.state import (
    ItemState, ItemStatus, RunState, StageName, StageStatus, StateStore,
)


def test_hash_resumability_skips_only_success_with_outputs(tmp_path: Path) -> None:
    output = tmp_path / "vina" / "result.pdbqt"
    output.parent.mkdir()
    output.write_text("MODEL 1\nENDMDL\n", encoding="utf-8")
    store = StateStore(tmp_path / "state" / "run.json", tmp_path)
    item = ItemState(input_identifier="lig_1", status=ItemStatus.SUCCESS,
                     input_hash="hash_a", outputs=["vina/result.pdbqt"])
    assert store.reusable_item(item, "hash_a")
    assert not store.reusable_item(item, "hash_b")
    item.status = ItemStatus.FAILED
    assert not store.reusable_item(item, "hash_a")


def test_state_transitions_persist(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state" / "run.json", tmp_path)
    state = RunState(run_id="run_1", project_id="project_1")
    store.save(state)
    store.transition(state, StageName.RUN_VINA, StageStatus.READY)
    store.transition(state, StageName.RUN_VINA, StageStatus.RUNNING)
    store.transition(state, StageName.RUN_VINA, StageStatus.SUCCESS)
    assert store.load().stages[StageName.RUN_VINA].status == StageStatus.SUCCESS

