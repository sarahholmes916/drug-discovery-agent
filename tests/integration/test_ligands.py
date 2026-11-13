from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from drug_discovery_agent.config.models import LigandSourceConfig
from drug_discovery_agent.ligands.ingest import ingest_ligands
from drug_discovery_agent.ligands.prepare import prepare_rdkit_sdf


pytestmark = pytest.mark.skipif(importlib.util.find_spec("rdkit") is None, reason="RDKit is optional")
FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_directory_sdf_ingestion_preserves_name_fallbacks(tmp_path: Path) -> None:
    result = ingest_ligands(
        [(LigandSourceConfig(source_ref="set_1", kind="sdf_directory"), FIXTURES / "ligands")],
        tmp_path / "source",
    )
    assert len(result.records) == 3
    assert {record.original_name for record in result.records} >= {None, "UCM"}
    assert all(record.ligand_id.startswith("lig_") for record in result.records)


def test_malformed_middle_record_does_not_hide_or_renumber_neighbors(tmp_path: Path) -> None:
    valid = (FIXTURES / "ligands" / "structures_12233.sdf").read_text()
    source = tmp_path / "mixed.sdf"
    source.write_text(valid + "bad record\n$$$$\n" + valid)
    result = ingest_ligands([(LigandSourceConfig(source_ref="set_1", kind="multi_sdf"), source)], tmp_path / "out")
    assert [item.status for item in result.records] == ["SUCCESS", "FAILED", "SUCCESS"]
    assert [item.source_record_index for item in result.records] == [1, 2, 3]


def test_valid_record_parsing_matches_previous_whole_file_reader():
    from rdkit import Chem
    from drug_discovery_agent.ligands.ingest import _sdf_records, _canonical_id
    for source in sorted((FIXTURES / "ligands").glob("*.sdf")):
        old = list(Chem.SDMolSupplier(str(source), removeHs=False))
        new = list(_sdf_records(source, Chem))
        assert len(old) == len(new)
        for index, (before, after) in enumerate(zip(old, new), 1):
            assert Chem.MolToMolBlock(before) == Chem.MolToMolBlock(after)
            assert Chem.MolToSmiles(before, isomericSmiles=True) == Chem.MolToSmiles(after, isomericSmiles=True)
            assert _canonical_id("source", index, Chem.MolToMolBlock(before)) == _canonical_id("source", index, Chem.MolToMolBlock(after))


def test_multi_sdf_missing_duplicate_and_invalid_entries_are_all_recorded(tmp_path: Path) -> None:
    source_record = (FIXTURES / "ligands" / "structures_12233.sdf").read_text(encoding="utf-8")
    molecule = source_record.rsplit("$$$$", 1)[0]
    lines = molecule.splitlines()
    duplicate_one = "\n".join(["Duplicate Name", *lines[1:]])
    duplicate_two = "\n".join(["Duplicate Name", *lines[1:]])
    unnamed = "\n".join(["", *lines[1:]])
    multi = tmp_path / "collection.sdf"
    multi.write_text(
        duplicate_one + "\n$$$$\n" + duplicate_two + "\n$$$$\n" + unnamed
        + "\n$$$$\nthis is invalid\n$$$$\n",
        encoding="utf-8",
    )
    result = ingest_ligands(
        [(LigandSourceConfig(source_ref="set_1", kind="multi_sdf"), multi)],
        tmp_path / "source",
    )
    assert [record.legacy_name for record in result.records[:3]] == [
        "Duplicate_Name", "Duplicate_Name_2", "structures_3",
    ]
    assert result.records[2].original_name is None
    assert result.records[3].status == "FAILED"
    assert "record 4" in result.records[3].error


def test_preparation_generates_conformer_and_explicit_hydrogens(tmp_path: Path) -> None:
    count, existing, modifications = prepare_rdkit_sdf(
        FIXTURES / "ligands" / "structures_12233.sdf", tmp_path / "prepared.sdf", random_seed=42
    )
    assert count > 0
    assert not existing
    assert {item.kind for item in modifications} >= {"explicit_hydrogens", "conformer_generation"}


def test_preparation_preserves_existing_3d(tmp_path: Path) -> None:
    count, existing, modifications = prepare_rdkit_sdf(
        FIXTURES / "vina" / "structures_12233_prepared.sdf", tmp_path / "prepared.sdf"
    )
    assert count > 0
    assert existing
    assert "conformer_generation" not in {item.kind for item in modifications}


def test_invalid_preparation_fails(tmp_path: Path) -> None:
    bad = tmp_path / "bad.sdf"
    bad.write_text("not an sdf\n$$$$\n", encoding="utf-8")
    with pytest.raises(ValueError, match="could not read"):
        prepare_rdkit_sdf(bad, tmp_path / "out.sdf")
