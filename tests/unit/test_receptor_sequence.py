from __future__ import annotations

from pathlib import Path

import pytest

from drug_discovery_agent.config.models import PocketResidue
from drug_discovery_agent.receptor.mapping import extract_protein_sequence, map_pocket_residues


ROOT = Path(__file__).parents[2]


def test_extracts_the_selected_chain_from_pdb_and_mmcif() -> None:
    receptor = ROOT / "tests" / "fixtures" / "receptor"

    pdb = extract_protein_sequence(receptor / "ns1_ed_receptor.pdb", "A")
    mmcif = extract_protein_sequence(receptor / "ns1_ed_receptor.cif", "A")

    assert pdb.chain == "A"
    assert pdb.source == "coordinate_records"
    assert pdb.sequence == mmcif.sequence
    assert len(pdb.sequence) == 127
    assert pdb.sequence.startswith("MTMASVPASR")


def test_extraction_reports_available_chains_when_selection_is_missing(tmp_path) -> None:
    receptor = tmp_path / "chain_b.pdb"
    receptor.write_text(
        "ATOM      1  CA  ALA B   1       1.000   2.000   3.000  1.00 20.00           C  \nEND\n",
        encoding="ascii",
    )

    with pytest.raises(ValueError, match=r"chain 'A'.*available chains: B"):
        extract_protein_sequence(receptor, "A")


def test_mapping_is_limited_to_the_configured_protein_chain(tmp_path) -> None:
    receptor = tmp_path / "two_chains.pdb"
    receptor.write_text(
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 20.00           C  \n"
        "ATOM      2  CA  GLY A   2       2.000   2.000   3.000  1.00 20.00           C  \n"
        "ATOM      3  CA  VAL B   1       3.000   2.000   3.000  1.00 20.00           C  \n"
        "END\n",
        encoding="ascii",
    )

    mappings = map_pocket_residues(
        receptor,
        "AG",
        [PocketResidue(chain="A", residue_number=2, residue_name="GLY")],
        protein_chain="A",
    )

    assert mappings[0].boltz_sequence_position == 2
