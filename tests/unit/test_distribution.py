import json
import shutil

import pytest

from drug_discovery_agent.distribution import verify_pocketminer_resources
from drug_discovery_agent.pocketminer.runtime import VENDORED_HOME


def test_pinned_distribution_resources_are_complete():
    resources = verify_pocketminer_resources()
    assert "LICENSE" in resources
    assert "models/pocketminer.index" in resources
    assert len(resources) == 8


def test_packaging_rejects_corrupt_checkpoint(tmp_path):
    shutil.copytree(VENDORED_HOME, tmp_path / "vendor")
    (tmp_path / "vendor/models/pocketminer.index").write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="integrity failure"):
        verify_pocketminer_resources(tmp_path / "vendor")
