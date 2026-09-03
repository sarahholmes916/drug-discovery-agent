from __future__ import annotations

import csv
from pathlib import Path

from drug_discovery_agent.boltz.inputs import load_boltz_input
from drug_discovery_agent.config.models import PocketResidue
from drug_discovery_agent.receptor.mapping import map_pocket_residues


ROOT = Path(__file__).parents[2]


def test_ns1_reference_residue_mapping() -> None:
    with (ROOT / "legacy" / "boltz" / "pocket_residues.csv").open(newline="", encoding="utf-8") as handle:
        reference = list(csv.DictReader(handle))
    residues = [
        PocketResidue(chain=row["pdb_chain"], residue_number=int(row["pdb_residue_number"]),
                      insertion_code=row["insertion_code"], residue_name=row["residue_name"],
                      sequence_position=int(row["receptor_sequence_ordinal"]))
        for row in reference
    ]
    boltz_input = load_boltz_input(ROOT / "tests" / "fixtures" / "boltz" / "ns1_structures_12233.yaml")
    sequence = boltz_input["sequences"][0]["protein"]["sequence"]
    mappings = map_pocket_residues(ROOT / "tests" / "fixtures" / "receptor" / "ns1_ed_receptor.pdb",
                                   sequence, residues)
    assert [item.pdb_residue_number for item in mappings] == [84, 85, 86, 87, 88, 89, 135, 136, 137, 138, 142, 143]
    assert [item.boltz_sequence_position for item in mappings] == [6, 7, 8, 9, 10, 11, 57, 58, 59, 60, 64, 65]

