from __future__ import annotations

from pathlib import Path

import pytest

from drug_discovery_agent.config.models import PocketMinerConfig
from drug_discovery_agent.execution.commands import CancellationToken, CommandExecutor
from drug_discovery_agent.pocketminer.box import build_box
from drug_discovery_agent.pocketminer.clustering import smooth_scores, spatial_components
from drug_discovery_agent.pocketminer.geometry import attach_representatives
from drug_discovery_agent.pocketminer.parser import parse_native_predictions
from drug_discovery_agent.pocketminer.ranking import rank_components
from drug_discovery_agent.pocketminer.regression import compare_with_reference
from drug_discovery_agent.pocketminer.runtime import inspect_installation, run_official


NS1_CENTER = (26.448, 12.021, 27.940)
NS1_SIZE = (28.0, 28.0, 28.0)


def test_real_ns1_pocketminer_regression_when_official_runtime_is_installed(tmp_path: Path) -> None:
    config = PocketMinerConfig()
    report = inspect_installation(config.runtime)
    if not report["available"]:
        pytest.skip("pinned official PocketMiner runtime is not installed on this test host")
    receptor = Path("tests/fixtures/receptor/ns1_ed_receptor.pdb").resolve()
    raw = tmp_path / "ns1-predictions.npy"
    result = run_official(config.runtime, receptor=receptor, output_npy=raw, executor=CommandExecutor(tmp_path / "commands"), cancellation=CancellationToken(), timeout_seconds=300)
    assert result.successful
    scores = attach_representatives(parse_native_predictions(raw, receptor), receptor)
    scores = smooth_scores(scores, neighbor_count=config.smoothing.neighbor_count, radius_angstrom=config.smoothing.radius_angstrom)
    components = spatial_components(
        scores,
        threshold=config.clustering.score_threshold,
        edge_distance_angstrom=config.clustering.edge_distance_angstrom,
        minimum_residues=config.clustering.minimum_residues,
        hotspot_radius_angstrom=config.clustering.hotspot_radius_angstrom,
        maximum_core_residues=config.clustering.maximum_core_residues,
    )
    boxes = [build_box(group, receptor, padding_angstrom=config.box.padding_angstrom, minimum_size=config.box.minimum_size, maximum_size=config.box.maximum_size) for group in components]
    candidates = rank_components(components, boxes=boxes, weights=config.ranking.weights, count_saturation=config.ranking.count_saturation, compactness_scale_angstrom=config.ranking.compactness_scale_angstrom)
    comparisons = [compare_with_reference(item, reference_center=NS1_CENTER, reference_size=NS1_SIZE) for item in candidates]
    assert comparisons, "PocketMiner produced no NS1 candidates at the configured threshold"
    best = min(comparisons, key=lambda item: item.center_distance_angstrom)
    print(best.as_dict())
    assert best.center_distance_angstrom < 35.0
    assert best.box_intersection_over_union > 0 or best.shared_hotspot
