"""Extract the top-40 Vina files, summarize poses, and append distance sheets.

This is the cleaned standalone version of the two notebook stages used before
ligand chemistry/interaction typing was added.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import csv
import json
import shutil

import numpy as np
from artifact_tool import Blob, Workbook, SpreadsheetFile

from common import (
    locate_files,
    mode1_pose,
    parse_receptor,
    parse_vina_poses,
    read_top40,
    unzip_archive,
    zip_directory,
)


HEADER_FMT = {
    "fill": "#1F4E78",
    "font": {"bold": True, "color": "#FFFFFF"},
    "horizontal_alignment": "center",
    "vertical_alignment": "center",
}


def extract_matching_docked_files(
    top40_csv: str | Path,
    docked_zip: str | Path,
    work_dir: str | Path,
    output_zip: str | Path,
) -> tuple[list[dict[str, str]], dict[str, Path], list[str]]:
    work_dir = Path(work_dir)
    extracted = unzip_archive(docked_zip, work_dir / "all_docked")
    index = locate_files(extracted, "_out.pdbqt")
    selected_dir = work_dir / "vina_top40_docked"
    selected_dir.mkdir(parents=True, exist_ok=True)

    rows = read_top40(top40_csv)
    selected: dict[str, Path] = {}
    missing: list[str] = []
    for row in rows:
        molecule = row["molecule"]
        source = index.get(molecule)
        if source is None:
            missing.append(molecule)
            continue
        target = selected_dir / f"{molecule}_out.pdbqt"
        shutil.copy2(source, target)
        selected[molecule] = target

    zip_directory(selected_dir, output_zip, "*_out.pdbqt")
    return rows, selected, missing


def pose_records(rows: list[dict[str, str]], selected: dict[str, Path]) -> tuple[list[dict], list[dict]]:
    poses: list[dict] = []
    mode1_atoms: list[dict] = []
    for row in rows:
        molecule = row["molecule"]
        path = selected.get(molecule)
        if path is None:
            continue
        for pose in parse_vina_poses(path, molecule):
            coords = np.asarray([a.coord for a in pose.heavy_atoms], dtype=float)
            mins = coords.min(axis=0)
            maxs = coords.max(axis=0)
            centroid = coords.mean(axis=0)
            poses.append(
                {
                    "molecule": molecule,
                    "mode": pose.mode,
                    "affinity_kcal_mol": pose.affinity,
                    "rmsd_lb_A": pose.rmsd_lb,
                    "rmsd_ub_A": pose.rmsd_ub,
                    "n_atoms": len(pose.heavy_atoms),
                    "centroid_x": float(centroid[0]),
                    "centroid_y": float(centroid[1]),
                    "centroid_z": float(centroid[2]),
                    "bbox_x_A": float(maxs[0] - mins[0]),
                    "bbox_y_A": float(maxs[1] - mins[1]),
                    "bbox_z_A": float(maxs[2] - mins[2]),
                    "file": path.name,
                }
            )
            if pose.mode == 1:
                for atom in pose.heavy_atoms:
                    mode1_atoms.append(
                        {
                            "molecule": molecule,
                            "mode": pose.mode,
                            "serial": atom.serial,
                            "atom_name": atom.atom_name,
                            "x": float(atom.coord[0]),
                            "y": float(atom.coord[1]),
                            "z": float(atom.coord[2]),
                            "partial_charge": atom.charge,
                            "vina_atom_type": atom.atom_type,
                        }
                    )
    return poses, mode1_atoms


def build_pose_workbook(
    rows: list[dict[str, str]],
    selected: dict[str, Path],
    missing: list[str],
    poses: list[dict],
    atom_rows: list[dict],
    output_path: str | Path,
) -> None:
    wb = Workbook.create()
    readme = wb.worksheets.add("README")
    values = [
        ["Vina Top-40 Pose Extraction and Analysis", None],
        ["Candidates requested", len(rows)],
        ["Matched docking files", len(selected)],
        ["Missing docking files", len(missing)],
        ["Pose used for coordinate tables", "Mode 1"],
        ["Missing candidates", ", ".join(missing)],
    ]
    readme.get_range(f"A1:B{len(values)}").values = values
    readme.merge_cells("A1:B1")
    readme.get_range("A1:B1").format = {
        "fill": "#1F4E78",
        "font": {"bold": True, "color": "#FFFFFF", "size": 14},
    }
    readme.get_range("A2:A6").format.font.bold = True
    readme.get_range("A:A").format.column_width = 30
    readme.get_range("B:B").format.column_width = 60

    status = wb.worksheets.add("Candidate Match Status")
    headers = [
        "rank", "molecule", "best_affinity_kcal_mol", "num_modes_csv",
        "expected_file", "file_found", "status", "note",
    ]
    status_rows = []
    for rank, row in enumerate(rows, 1):
        molecule = row["molecule"]
        found = molecule in selected
        status_rows.append(
            [
                rank,
                molecule,
                float(row["best_affinity_kcal_mol"]),
                int(float(row["num_modes"])),
                f"{molecule}_out.pdbqt",
                found,
                row["status"],
                "" if found else "Not present in uploaded docked.zip",
            ]
        )
    status.get_range(f"A1:H{len(status_rows)+1}").values = [headers] + status_rows

    pose_sheet = wb.worksheets.add("Vina Pose Summary")
    pose_headers = [
        "molecule", "mode", "affinity_kcal_mol", "rmsd_lb_A", "rmsd_ub_A",
        "n_atoms", "centroid_x", "centroid_y", "centroid_z", "bbox_x_A",
        "bbox_y_A", "bbox_z_A", "file",
    ]
    pose_sheet.get_range(f"A1:M{len(poses)+1}").values = [pose_headers] + [
        [p.get(h) for h in pose_headers] for p in poses
    ]

    mode1_sheet = wb.worksheets.add("Vina Mode 1 Summary")
    rank_map = {row["molecule"]: i + 1 for i, row in enumerate(rows)}
    mode1_headers = [
        "rank", "molecule", "affinity_kcal_mol", "n_atoms", "centroid_x",
        "centroid_y", "centroid_z", "bbox_x_A", "bbox_y_A", "bbox_z_A", "file",
    ]
    mode1 = [p for p in poses if p["mode"] == 1]
    mode1_values = [
        [
            rank_map[p["molecule"]], p["molecule"], p["affinity_kcal_mol"],
            p["n_atoms"], p["centroid_x"], p["centroid_y"], p["centroid_z"],
            p["bbox_x_A"], p["bbox_y_A"], p["bbox_z_A"], p["file"],
        ]
        for p in mode1
    ]
    mode1_sheet.get_range(f"A1:K{len(mode1_values)+1}").values = [mode1_headers] + mode1_values

    atoms_sheet = wb.worksheets.add("Vina Mode 1 Atoms")
    atom_headers = [
        "molecule", "mode", "serial", "atom_name", "x", "y", "z",
        "partial_charge", "vina_atom_type",
    ]
    atoms_sheet.get_range(f"A1:I{len(atom_rows)+1}").values = [atom_headers] + [
        [a.get(h) for h in atom_headers] for a in atom_rows
    ]

    for sheet_name, last_col, last_row in [
        ("Candidate Match Status", "H", len(status_rows) + 1),
        ("Vina Pose Summary", "M", len(poses) + 1),
        ("Vina Mode 1 Summary", "K", len(mode1_values) + 1),
        ("Vina Mode 1 Atoms", "I", len(atom_rows) + 1),
    ]:
        sheet = wb.worksheets.get_item(sheet_name)
        sheet.get_range(f"A1:{last_col}1").format = HEADER_FMT
        sheet.freeze_panes.freeze_rows(1)
        sheet.get_range(f"A1:{last_col}{last_row}").format.wrap_text = True
        sheet.get_range(f"A1:{last_col}{last_row}").format.autofit_columns()

    SpreadsheetFile.export_xlsx(wb).save(str(output_path))


def distance_tables(
    rows: list[dict[str, str]],
    selected: dict[str, Path],
    receptor_path: str | Path,
) -> dict[str, list]:
    receptor = parse_receptor(receptor_path)
    residue_keys = sorted(receptor.by_residue, key=lambda x: (x[0], x[1], x[2]))
    rank_map = {row["molecule"]: i + 1 for i, row in enumerate(rows)}
    score_map = {row["molecule"]: float(row["best_affinity_kcal_mol"]) for row in rows}

    distance_rows: list[list] = []
    contact_rows: list[list] = []
    ligand_summary: list[list] = []

    for row in rows:
        molecule = row["molecule"]
        path = selected.get(molecule)
        if path is None:
            continue
        pose = mode1_pose(path, molecule)
        ligand_atoms = pose.heavy_atoms
        ligand_coords = np.asarray([a.coord for a in ligand_atoms], dtype=float)
        contacts: list[tuple[str, float]] = []
        closest_distance = float("inf")
        closest_residue = None

        for chain, resid, resname in residue_keys:
            protein_coords = np.asarray(
                [a.coord for a in receptor.by_residue[(chain, resid, resname)] if a.element != "H"],
                dtype=float,
            )
            pairwise = protein_coords[:, None, :] - ligand_coords[None, :, :]
            distance = float(np.sqrt(np.square(pairwise).sum(axis=2).min()))
            residue = f"{resname}{resid}"
            record = [
                "vina", molecule, molecule, path.name, chain, resid, resname,
                residue, distance, "UNL", len(ligand_atoms), 1,
                pose.affinity if pose.affinity is not None else score_map[molecule],
                rank_map[molecule],
            ]
            distance_rows.append(record)
            if distance < 4.0:
                contact_rows.append(record)
                contacts.append((residue, distance))
            if distance < closest_distance:
                closest_distance = distance
                closest_residue = residue

        ligand_summary.append(
            [
                rank_map[molecule], molecule,
                pose.affinity if pose.affinity is not None else score_map[molecule],
                len(ligand_atoms), len(contacts), len({x[0] for x in contacts}),
                closest_residue, closest_distance,
                ", ".join(x[0] for x in sorted(contacts, key=lambda x: x[1])[:10]),
            ]
        )

    by_residue: dict[str, list[float]] = defaultdict(list)
    by_residue_ligands: dict[str, set[str]] = defaultdict(set)
    exemplar: dict[str, list] = {}
    for row in contact_rows:
        by_residue[row[7]].append(row[8])
        by_residue_ligands[row[7]].add(row[1])
        exemplar[row[7]] = row

    contact_summary = []
    for residue, distances in by_residue.items():
        row = exemplar[residue]
        contact_summary.append(
            [
                residue, row[6], row[5], row[4], len(by_residue_ligands[residue]),
                float(np.mean(distances)), float(np.min(distances)),
                ", ".join(sorted(by_residue_ligands[residue], key=lambda x: rank_map[x])),
            ]
        )
    contact_summary.sort(key=lambda x: (-x[4], x[5], x[2]))
    ligand_summary.sort(key=lambda x: x[0])

    return {
        "distance_rows": distance_rows,
        "contact_rows": contact_rows,
        "contact_summary": contact_summary,
        "ligand_summary": ligand_summary,
        "receptor_residue_count": len(residue_keys),
    }


def append_distance_sheets(
    base_workbook: str | Path,
    output_workbook: str | Path,
    rows: list[dict[str, str]],
    missing: list[str],
    tables: dict[str, list],
) -> None:
    wb = SpreadsheetFile.import_xlsx(Blob.load(str(base_workbook)))
    contact_rows = tables["contact_rows"]
    distance_rows = tables["distance_rows"]
    contact_summary = tables["contact_summary"]
    ligand_summary = tables["ligand_summary"]
    contact_distances = [row[8] for row in contact_rows]

    dashboard = wb.worksheets.add("Vina Distance Dashboard")
    kpis = [
        ["Metric", "Value"],
        ["Top-40 candidates requested", len(rows)],
        ["Docking files analyzed", len(ligand_summary)],
        ["Missing docking files", len(missing)],
        ["Receptor residues analyzed", tables["receptor_residue_count"]],
        ["Total ligand-residue contacts <4 Å", len(contact_rows)],
        ["Mean contact distance (Å)", float(np.mean(contact_distances))],
        ["Median contact distance (Å)", float(np.median(contact_distances))],
        ["Minimum contact distance (Å)", float(np.min(contact_distances))],
        ["Maximum contact distance (Å)", float(np.max(contact_distances))],
        ["Mode analyzed", 1],
        ["Atom selection", "Heavy atoms only"],
        ["Missing ligands", ", ".join(missing)],
    ]
    dashboard.get_range(f"A1:B{len(kpis)}").values = kpis
    dashboard.merge_cells("D1:G1")
    dashboard.get_range("D1").values = [["Most recurrent Vina contact residues (<4 Å)"]]
    top_residues = [["Residue", "Ligands contacted", "Mean distance (Å)", "Best distance (Å)"]]
    top_residues.extend([[r[0], r[4], r[5], r[6]] for r in contact_summary[:15]])
    dashboard.get_range(f"D2:G{len(top_residues)+1}").values = top_residues
    dashboard.get_range("A1:B1").format = HEADER_FMT
    dashboard.get_range("D1:G1").format = {
        "fill": "#1F4E78",
        "font": {"bold": True, "color": "#FFFFFF", "size": 13},
        "horizontal_alignment": "center",
    }
    dashboard.get_range("D2:G2").format = {
        "fill": "#5B9BD5", "font": {"bold": True, "color": "#FFFFFF"}
    }
    dashboard.get_range("A2:A13").format.font.bold = True
    dashboard.get_range("A:A").format.column_width = 31
    dashboard.get_range("B:B").format.column_width = 38
    dashboard.get_range("D:G").format.column_width = 18
    dashboard.get_range("B7:B10").format.number_format = "0.000"

    summary_sheet = wb.worksheets.add("Vina Contact Summary")
    summary_headers = [
        "residue", "resname", "resid", "chain", "n_ligands",
        "mean_min_dist_A", "best_min_dist_A", "ligands",
    ]
    summary_sheet.get_range(f"A1:H{len(contact_summary)+1}").values = [summary_headers] + contact_summary

    distance_headers = [
        "method", "molecule", "input", "structure_file", "chain", "resid",
        "resname", "residue", "min_dist_A", "ligand_resname", "n_ligand_atoms",
        "vina_mode", "vina_affinity_kcal_mol", "vina_rank",
    ]
    contacts_sheet = wb.worksheets.add("Vina Contacts <4A")
    contacts_sheet.get_range(f"A1:N{len(contact_rows)+1}").values = [distance_headers] + contact_rows
    distance_sheet = wb.worksheets.add("Vina Residue Dist")
    distance_sheet.get_range(f"A1:N{len(distance_rows)+1}").values = [distance_headers] + distance_rows

    ligand_sheet = wb.worksheets.add("Vina Ligand Summary")
    ligand_headers = [
        "vina_rank", "molecule", "vina_affinity_kcal_mol", "n_ligand_heavy_atoms",
        "contacts_under_4A", "unique_contact_residues", "closest_residue",
        "closest_distance_A", "nearest_10_contact_residues",
    ]
    ligand_sheet.get_range(f"A1:I{len(ligand_summary)+1}").values = [ligand_headers] + ligand_summary

    status_sheet = wb.worksheets.add("Vina PLIP Status")
    status_values = [
        ["Item", "Status / explanation"],
        ["Geometric residue-distance analysis", "Completed using the prepared receptor and Vina mode-1 poses."],
        ["Contacts under 4 Å", "Completed using heavy atoms only."],
        ["Interaction typing", "Added by the later interaction-analysis stage."],
    ]
    status_sheet.get_range("A1:B4").values = status_values

    for name, last_col, last_row in [
        ("Vina Contact Summary", "H", len(contact_summary) + 1),
        ("Vina Contacts <4A", "N", len(contact_rows) + 1),
        ("Vina Residue Dist", "N", len(distance_rows) + 1),
        ("Vina Ligand Summary", "I", len(ligand_summary) + 1),
        ("Vina PLIP Status", "B", 4),
    ]:
        sheet = wb.worksheets.get_item(name)
        sheet.get_range(f"A1:{last_col}1").format = HEADER_FMT
        sheet.freeze_panes.freeze_rows(1)
        sheet.get_range(f"A1:{last_col}{last_row}").format.wrap_text = True
        sheet.get_range(f"A1:{last_col}{last_row}").format.autofit_columns()

    summary_sheet.get_range(f"F2:G{len(contact_summary)+1}").format.number_format = "0.000"
    contacts_sheet.get_range(f"I2:I{len(contact_rows)+1}").format.number_format = "0.000"
    distance_sheet.get_range(f"I2:I{len(distance_rows)+1}").format.number_format = "0.000"
    ligand_sheet.get_range(f"C2:C{len(ligand_summary)+1}").format.number_format = "0.000"
    ligand_sheet.get_range(f"H2:H{len(ligand_summary)+1}").format.number_format = "0.000"
    ligand_sheet.get_range("I:I").format.column_width = 52
    status_sheet.get_range("A:A").format.column_width = 34
    status_sheet.get_range("B:B").format.column_width = 90

    SpreadsheetFile.export_xlsx(wb).save(str(output_workbook))


def run(
    base_workbook: str | Path,
    top40_csv: str | Path,
    docked_zip: str | Path,
    receptor_path: str | Path,
    work_dir: str | Path,
    output_workbook: str | Path,
    pose_workbook: str | Path,
    selected_zip: str | Path,
) -> dict:
    rows, selected, missing = extract_matching_docked_files(
        top40_csv, docked_zip, work_dir, selected_zip
    )
    poses, atom_rows = pose_records(rows, selected)
    build_pose_workbook(rows, selected, missing, poses, atom_rows, pose_workbook)
    tables = distance_tables(rows, selected, receptor_path)
    append_distance_sheets(base_workbook, output_workbook, rows, missing, tables)
    payload = {
        "rows": rows,
        "selected": {k: str(v) for k, v in selected.items()},
        "missing": missing,
        "poses": poses,
        "mode1_atoms": atom_rows,
        "distance_table_counts": {k: len(v) if isinstance(v, list) else v for k, v in tables.items()},
    }
    Path(work_dir, "pose_and_distance_summary.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return payload
