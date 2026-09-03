from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from drug_discovery_agent.receptor.conversion import (
    convert_pdb_template_to_mmcif,
    convert_pdbqt_to_pdb,
    validate_coordinates,
)


FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_receptor_conversion_preserves_all_coordinates(tmp_path: Path) -> None:
    # The PDB fixture is the exact coordinate-preserving legacy conversion. It
    # is parsed through the PDBQT-compatible fixed-width path to regression-test
    # removal of trailing tool fields without moving coordinates.
    source = tmp_path / "receptor.pdbqt"
    shutil.copy2(FIXTURES / "receptor" / "ns1_ed_receptor.pdb", source)
    validation = convert_pdbqt_to_pdb(source, tmp_path / "converted.pdb")
    assert validation.atom_count == 1207
    assert validation.coordinate_identity_verified
    assert validation.coordinate_max_abs_delta_angstrom == 0.0


def test_legacy_pdb_and_mmcif_templates_are_coordinate_identical() -> None:
    validation = validate_coordinates(
        FIXTURES / "receptor" / "ns1_ed_receptor.pdb",
        FIXTURES / "receptor" / "ns1_ed_receptor.cif",
        tolerance_angstrom=0.0,
    )
    assert validation.coordinate_identity_verified
    assert validation.atom_count == 1207
    assert validation.coordinate_max_abs_delta_angstrom == 0.0


def test_boltz_mmcif_compatibility_conversion_preserves_template_coordinates(tmp_path: Path) -> None:
    pytest.importorskip("gemmi")
    source = FIXTURES / "receptor" / "ns1_ed_receptor.pdb"
    target = tmp_path / "boltz_template.cif"

    validation = convert_pdb_template_to_mmcif(source, target)

    assert target.is_file()
    assert validation.coordinate_identity_verified
    assert validation.atom_count == 1207
    assert validation.coordinate_max_abs_delta_angstrom == 0.0
    assert "_atom_site.Cartn_x" in target.read_text(encoding="utf-8")
