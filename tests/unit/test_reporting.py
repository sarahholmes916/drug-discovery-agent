from __future__ import annotations

from drug_discovery_agent.reporting.workbook import build_workbook_tables


def test_workbook_tables_use_runtime_counts_and_keep_legacy_names() -> None:
    tables = build_workbook_tables([{
        "ligand_id": "lig_opaque",
        "legacy_name": "structures_7",
        "status": "SUCCESS",
        "mapping": {"mapping_method": "meeko_index_map", "bonds_over_2_2_angstrom": 0},
        "interactions": [{
            "interaction_type": "Hydrogen bond",
            "residue": "ASN42",
            "primary_distance_angstrom": 3.1,
        }],
        "binding_site_residues": [{"residue": "ASN42", "minimum_distance_angstrom": 3.1}],
        "distances": [{"residue": "ASN42", "minimum_distance_angstrom": 3.1}],
    }])

    assert "Vina PLIP Interactions" in tables
    assert tables["Vina PLIP Dashboard"][1] == ["Ligands analyzed", 1]
    ligand_row = tables["Vina PLIP Ligand Summary"][1]
    assert ligand_row[:5] == ["lig_opaque", "structures_7", "SUCCESS", 1, 1]
    assert ligand_row[6] == 1


def test_workbook_tables_have_no_target_specific_fixture_data() -> None:
    serialized = str(build_workbook_tables([])).lower()
    assert "ns1" not in serialized
    assert "structures_1756" not in serialized
