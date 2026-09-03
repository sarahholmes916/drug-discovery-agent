"""Append Vina interaction results to the distance-augmented workbook."""
from __future__ import annotations

from pathlib import Path
import json

from artifact_tool import Blob, SpreadsheetFile


HEADER_FMT = {
    "fill": "#1F4E78",
    "font": {"bold": True, "color": "#FFFFFF"},
    "horizontal_alignment": "center",
    "vertical_alignment": "center",
}
SUBHEADER_FMT = {
    "fill": "#5B9BD5",
    "font": {"bold": True, "color": "#FFFFFF"},
    "horizontal_alignment": "center",
    "vertical_alignment": "center",
}
TITLE_FMT = {
    "fill": "#1F4E78",
    "font": {"bold": True, "color": "#FFFFFF", "size": 14},
    "horizontal_alignment": "center",
    "vertical_alignment": "center",
}


def add_table_sheet(wb, name, headers, rows, last_col, widths=None, number_formats=None):
    sheet = wb.worksheets.add(name)
    sheet.get_range(f"A1:{last_col}{len(rows)+1}").values = [headers] + rows
    sheet.get_range(f"A1:{last_col}1").format = HEADER_FMT
    sheet.freeze_panes.freeze_rows(1)
    sheet.get_range(f"A1:{last_col}{len(rows)+1}").format.wrap_text = True
    sheet.get_range(f"A1:{last_col}{len(rows)+1}").format.autofit_columns()
    if widths:
        for column, width in widths.items():
            sheet.get_range(f"{column}:{column}").format.column_width = width
    if number_formats:
        for cell_range, number_format in number_formats.items():
            sheet.get_range(cell_range).format.number_format = number_format
    return sheet


def append_interaction_sheets(
    source_workbook: str | Path,
    output_workbook: str | Path,
    results: dict,
    validation: list[dict],
) -> None:
    wb = SpreadsheetFile.import_xlsx(Blob.load(str(source_workbook)))

    # Update the earlier status sheet rather than deleting it.
    status = wb.worksheets.get_item("Vina PLIP Status")
    status.get_range("A1:B20").clear({})
    status_rows = [
        ["Vina interaction-analysis status", "Completed"],
        ["Ligands requested", 40],
        ["Ligands analyzed", 38],
        ["Unavailable candidates", "midostaurin_fixed; midostaurin"],
        ["Docked pose", "AutoDock Vina mode 1"],
        ["Chemistry source", "Matching source SDF for each ligand"],
        ["Coordinate transfer", "Molecular-graph mapping from SDF atoms to docked PDBQT atoms"],
        ["Interaction scheme", "PLIP-compatible rule set using PLIP 3.0 default distance/angle thresholds"],
        ["Feature perception", "RDKit ligand chemistry plus prepared receptor PDBQT atom types"],
        ["Native PLIP XML generated", "No"],
        ["Comparability note", "The appended sheets reproduce the same interaction categories and summary structure, but may not be identical to native PLIP/Open Babel output."],
        ["Pose validation warning", "structures_1756 contains mapped bonds longer than 2.2 Å in the original docked PDBQT geometry and should be visually reviewed."],
    ]
    status.get_range(f"A1:B{len(status_rows)}").values = status_rows
    status.get_range("A1:B1").format = TITLE_FMT
    status.get_range(f"A2:A{len(status_rows)}").format.font.bold = True
    status.get_range(f"A1:B{len(status_rows)}").format.wrap_text = True
    status.get_range("A:A").format.column_width = 34
    status.get_range("B:B").format.column_width = 90

    readme = wb.worksheets.add("Vina PLIP README")
    readme_rows = [
        ["Vina PLIP-Compatible Interaction Analysis", None],
        ["Purpose", "Append Vina mode-1 residue and interaction evidence in the same general structure as the existing Boltz-2 PLIP analysis."],
        ["Candidates analyzed", 38],
        ["Missing candidates", "midostaurin_fixed and midostaurin were absent from both the docking archive and SDF collection."],
        ["Receptor", "Uploaded prepared ns1_ed_receptor.pdbqt in the exact Vina docking coordinate frame."],
        ["Ligand chemistry", "Original SDF bond orders, aromaticity, formal charges, donors, acceptors, and halogens."],
        ["Coordinate mapping", "SDF molecular graphs were matched to Vina PDBQT mode-1 coordinates using embedded Meeko SMILES/index records."],
        ["Interaction types", "Hydrophobic interactions, hydrogen bonds, salt bridges, π-stacking, π-cation interactions, and halogen bonds."],
        ["Threshold basis", "PLIP 3.0 defaults: hydrophobic 4.0 Å; H-bond D–A 4.1 Å and donor angle ≥100°; π-stack 5.5 Å with 30° angular deviation and 2.0 Å offset; π-cation 6.0 Å; salt bridge 5.5 Å; halogen 4.0 Å."],
        ["Important limitation", "This runtime did not use native PLIP/Open Babel. The appended output uses a PLIP-compatible rule implementation with RDKit and PDBQT feature perception, so exact native-PLIP counts may differ."],
        ["Synthetic report references", "The Report XML column preserves the prior workbook schema; no XML files were generated."],
        ["Mode analyzed", "Vina mode 1 only."],
        ["Atom selection", "Heavy atoms for contact distances; explicit PDBQT polar hydrogens for hydrogen-bond geometry."],
        ["Validation warning", "structures_1756 has distorted sulfur–oxygen geometry in its docked PDBQT and is flagged for review."],
    ]
    readme.get_range(f"A1:B{len(readme_rows)}").values = readme_rows
    readme.merge_cells("A1:B1")
    readme.get_range("A1:B1").format = TITLE_FMT
    readme.get_range(f"A2:A{len(readme_rows)}").format.font.bold = True
    readme.get_range(f"A1:B{len(readme_rows)}").format.wrap_text = True
    readme.get_range("A:A").format.column_width = 28
    readme.get_range("B:B").format.column_width = 95

    interaction_headers = [
        "Report XML", "Method", "Ligand", "Binding Site", "Ligand ID", "Ligand Chain",
        "Ligand Position", "Ligand SMILES", "Interaction Type", "Residue", "Residue Name",
        "Residue Number", "Protein Chain", "Ligand Residue", "Primary Distance (Å)",
        "D-A Distance (Å)", "H-A Distance (Å)", "Angle (°)", "Sidechain", "Protein Role",
        "PLIP Interaction ID", "Ligand Atom Index Info", "Protein Atom Index Info",
        "Ligand Coord", "Protein Coord", "Extra",
    ]
    interaction_rows = [[row.get(header) for header in interaction_headers] for row in results["interactions"]]
    add_table_sheet(
        wb,
        "Vina PLIP Interactions",
        interaction_headers,
        interaction_rows,
        "Z",
        widths={"A": 32, "C": 28, "H": 45, "I": 24, "J": 14, "V": 28, "W": 28, "X": 24, "Y": 24, "Z": 36},
        number_formats={f"O2:R{len(interaction_rows)+1}": "0.000"},
    )

    binding_headers = [
        "Report XML", "Method", "Ligand", "Binding Site", "Ligand ID", "Ligand Chain",
        "Ligand Position", "Residue", "Residue Name", "Residue Number", "Protein Chain",
        "PLIP Contact", "Min Distance (Å)",
    ]
    binding_rows = [[row.get(header) for header in binding_headers] for row in results["binding_site_residues"]]
    add_table_sheet(
        wb,
        "Vina PLIP Binding Residues",
        binding_headers,
        binding_rows,
        "M",
        widths={"A": 32, "C": 28, "H": 14, "L": 14},
        number_formats={f"M2:M{len(binding_rows)+1}": "0.000"},
    )

    report_headers = [
        "Report XML", "Method", "Ligand", "Input PDB", "PDB ID", "PLIP Version",
        "Date", "Binding Sites", "Total Interactions",
    ]
    add_table_sheet(
        wb,
        "Vina PLIP Report Summary",
        report_headers,
        results["report_summary"],
        "I",
        widths={"A": 34, "C": 28, "D": 32, "E": 38, "F": 30},
    )

    type_headers = [
        "Interaction Type", "Count", "Unique Ligands", "Unique Residues",
        "Min Distance (Å)", "Mean Distance (Å)",
    ]
    type_rows = results["interaction_summary"]
    add_table_sheet(
        wb,
        "Vina PLIP Type Summary",
        type_headers,
        type_rows,
        "F",
        widths={"A": 25},
        number_formats={f"E2:F{len(type_rows)+1}": "0.000"},
    )

    ligand_headers = [
        "Ligand", "Method", "Total Interactions", "Unique Residues",
        "Hydrophobic interaction", "Hydrogen bond", "Salt bridge", "π-stacking",
        "π-cation interaction", "Halogen bond",
    ]
    ligand_rows = results["ligand_summary"]
    add_table_sheet(
        wb, "Vina PLIP Ligand Summary", ligand_headers, ligand_rows, "J", widths={"A": 28}
    )

    residue_headers = [
        "Protein Chain", "Residue", "Residue Name", "Residue Number", "Interaction Type",
        "Count", "Unique Ligands", "Ligands", "Min Distance (Å)", "Mean Distance (Å)",
    ]
    residue_rows = results["residue_summary"]
    add_table_sheet(
        wb,
        "Vina PLIP Residue Summary",
        residue_headers,
        residue_rows,
        "J",
        widths={"B": 14, "E": 24, "H": 75},
        number_formats={f"I2:J{len(residue_rows)+1}": "0.000"},
    )

    contact_headers = [
        "Protein Chain", "Residue", "Residue Name", "Residue Number", "Ligand Count",
        "Ligands", "Min Contact Distance (Å)", "Mean Contact Distance (Å)",
    ]
    contact_rows = results["contact_summary"]
    add_table_sheet(
        wb,
        "Vina PLIP Contact Residues",
        contact_headers,
        contact_rows,
        "H",
        widths={"B": 14, "F": 85},
        number_formats={f"G2:H{len(contact_rows)+1}": "0.000"},
    )

    integrated_headers = [
        "Ligand", "Clean Ligand Name", "Vina Top-40 Rank", "Vina Best Affinity (kcal/mol)",
        "Total Interactions", "Unique Residues", "Hydrophobic", "Hydrogen Bonds",
        "Salt Bridges", "π-stacking", "π-cation", "Halogen Bonds",
        "Best Interaction Distance (Å)", "Interaction Residues", "Top Interaction Evidence",
        "Evidence Flag",
    ]
    integrated_rows = results["integrated_summary"]
    add_table_sheet(
        wb,
        "Vina PLIP Integrated",
        integrated_headers,
        integrated_rows,
        "P",
        widths={"A": 28, "B": 24, "N": 70, "O": 85, "P": 28},
        number_formats={
            f"D2:D{len(integrated_rows)+1}": "0.000",
            f"M2:M{len(integrated_rows)+1}": "0.000",
        },
    )

    validation_by_name = {row["molecule"]: row for row in validation}
    mapping_rows = []
    for rank, molecule, status_text, method in results["mapping_status"]:
        row = validation_by_name.get(molecule, {})
        mapping_rows.append(
            [
                rank,
                molecule,
                status_text,
                method or row.get("mapping_method"),
                row.get("n_heavy_atoms"),
                row.get("n_bonds"),
                row.get("median_bond_length_A"),
                row.get("max_bond_length_A"),
                row.get("bonds_over_2_2A"),
                row.get("validation_flag"),
            ]
        )
    mapping_headers = [
        "Vina Rank", "Molecule", "Mapping Status", "Mapping Method", "Heavy Atoms",
        "Bonds", "Median Bond Length (Å)", "Max Bond Length (Å)",
        "Bonds >2.2 Å", "Validation Flag",
    ]
    mapping_sheet = add_table_sheet(
        wb,
        "Vina SDF Mapping",
        mapping_headers,
        mapping_rows,
        "J",
        widths={"B": 25, "C": 25, "D": 35, "J": 25},
        number_formats={f"G2:H{len(mapping_rows)+1}": "0.000"},
    )
    mapping_sheet.get_range(f"J2:J{len(mapping_rows)+1}").conditional_formats.add_custom(
        '=J2="Review PDBQT geometry"',
        {"fill": "#FCE8E6", "font": {"color": "#B91C1C", "bold": True}},
    )

    dashboard = wb.worksheets.add("Vina PLIP Dashboard")
    dashboard.merge_cells("A1:M1")
    dashboard.get_range("A1:M1").values = [["Vina Mode-1 Interaction Dashboard"]]
    dashboard.get_range("A1:M1").format = TITLE_FMT

    type_count = {row[0]: row[1] for row in type_rows}
    kpis = [
        ["Ligands analyzed", len(ligand_rows)],
        ["Total interaction records", len(interaction_rows)],
        ["Binding-site residue rows", len(binding_rows)],
        ["Hydrophobic interactions", type_count.get("Hydrophobic interaction", 0)],
        ["Hydrogen bonds", type_count.get("Hydrogen bond", 0)],
        ["Salt bridges", type_count.get("Salt bridge", 0)],
        ["π-stacking", type_count.get("π-stacking", 0)],
        ["π-cation interactions", type_count.get("π-cation interaction", 0)],
        ["Halogen bonds", type_count.get("Halogen bond", 0)],
    ]
    dashboard.get_range("A3:B11").values = kpis
    dashboard.get_range("A3:B3").format = SUBHEADER_FMT
    dashboard.get_range("A3:A11").format.font.bold = True
    dashboard.get_range("A:B").format.column_width = 29

    dashboard.merge_cells("D3:I3")
    dashboard.get_range("D3:I3").values = [["Top interaction-supported ligands"]]
    dashboard.get_range("D3:I3").format = SUBHEADER_FMT
    top_ligands = sorted(integrated_rows, key=lambda row: (-row[4], -row[5], row[2]))[:8]
    top_headers = ["Ligand", "Vina Rank", "Affinity", "Interactions", "Residues", "Evidence"]
    top_rows = [[r[1], r[2], r[3], r[4], r[5], r[15]] for r in top_ligands]
    dashboard.get_range(f"D4:I{len(top_rows)+4}").values = [top_headers] + top_rows
    dashboard.get_range("D4:I4").format = HEADER_FMT
    dashboard.get_range("D:D").format.column_width = 24
    dashboard.get_range("E:H").format.column_width = 14
    dashboard.get_range("I:I").format.column_width = 26

    dashboard.merge_cells("A14:F14")
    dashboard.get_range("A14:F14").values = [["Top residue/type signals"]]
    dashboard.get_range("A14:F14").format = SUBHEADER_FMT
    top_residue_headers = ["Residue", "Interaction Type", "Count", "Ligands", "Min Distance", "Mean Distance"]
    top_residue_rows = [[r[1], r[4], r[5], r[6], r[8], r[9]] for r in residue_rows[:10]]
    dashboard.get_range(f"A15:F{len(top_residue_rows)+15}").values = [top_residue_headers] + top_residue_rows
    dashboard.get_range("A15:F15").format = HEADER_FMT

    dashboard.merge_cells("H14:M14")
    dashboard.get_range("H14:M14").values = [["Interaction-type summary"]]
    dashboard.get_range("H14:M14").format = SUBHEADER_FMT
    dashboard.get_range("H15:M21").values = [type_headers] + type_rows
    dashboard.get_range("H15:M15").format = HEADER_FMT
    dashboard.get_range("H:H").format.column_width = 25
    dashboard.get_range("I:M").format.column_width = 16
    dashboard.get_range("L16:M21").format.number_format = "0.000"
    dashboard.get_range("A1:M25").format.wrap_text = True
    dashboard.freeze_panes.freeze_rows(1)

    chart = dashboard.charts.add("bar", dashboard.get_range("H15:I21"))
    chart.title_text = "Interaction Counts by Type"
    chart.has_legend = False
    chart.set_position("H23", "M38")

    SpreadsheetFile.export_xlsx(wb).save(str(output_workbook))


def append_from_json(
    source_workbook: str | Path,
    output_workbook: str | Path,
    results_json: str | Path,
    validation_json: str | Path,
) -> None:
    results = json.loads(Path(results_json).read_text(encoding="utf-8"))
    validation = json.loads(Path(validation_json).read_text(encoding="utf-8"))
    append_interaction_sheets(source_workbook, output_workbook, results, validation)
