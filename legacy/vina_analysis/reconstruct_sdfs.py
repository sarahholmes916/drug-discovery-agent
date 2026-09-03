"""Reconstruct chemically complete Vina mode-1 SDF poses.

The source SDF supplies bond orders, aromaticity, charges, and stereochemistry;
the Vina PDBQT supplies the mode-1 coordinates. Atom mapping uses Meeko's
embedded REMARK SMILES and REMARK SMILES IDX records.
"""
from __future__ import annotations

from pathlib import Path
import json

from common import (
    locate_files,
    mode1_pose,
    read_top40,
    reconstruct_ligand,
    unzip_archive,
    write_sdf,
    zip_directory,
)


def reconstruct_all(
    top40_csv: str | Path,
    docked_dir: str | Path,
    sdf_zip: str | Path,
    work_dir: str | Path,
    output_zip: str | Path,
) -> tuple[dict[str, object], list[dict]]:
    work_dir = Path(work_dir)
    sdf_root = unzip_archive(sdf_zip, work_dir / "all_source_sdfs")
    sdf_index = locate_files(sdf_root, ".sdf")
    docked_index = locate_files(docked_dir, "_out.pdbqt")
    output_dir = work_dir / "vina_top40_mode1_docked_sdfs"
    output_dir.mkdir(parents=True, exist_ok=True)

    reconstructed: dict[str, object] = {}
    validation: list[dict] = []

    for rank, row in enumerate(read_top40(top40_csv), 1):
        molecule = row["molecule"]
        pdbqt = docked_index.get(molecule)
        source_sdf = sdf_index.get(molecule)
        if pdbqt is None or source_sdf is None:
            validation.append(
                {
                    "rank": rank,
                    "molecule": molecule,
                    "mapping_status": "Missing input",
                    "mapping_method": None,
                    "n_heavy_atoms": None,
                    "n_bonds": None,
                    "median_bond_length_A": None,
                    "max_bond_length_A": None,
                    "bonds_over_2_2A": None,
                    "validation_flag": "Not analyzed",
                }
            )
            continue

        pose = mode1_pose(pdbqt, molecule)
        ligand = reconstruct_ligand(source_sdf, pose)
        output_sdf = output_dir / f"{molecule}_vina_mode1.sdf"
        write_sdf(ligand.mol, output_sdf)
        reconstructed[molecule] = ligand
        validation.append(
            {
                "rank": rank,
                "molecule": molecule,
                "mapping_status": "Mapped",
                "mapping_method": ligand.mapping_method,
                "n_heavy_atoms": ligand.mol.GetNumHeavyAtoms(),
                "n_bonds": ligand.mol.GetNumBonds(),
                "median_bond_length_A": ligand.median_bond_length,
                "max_bond_length_A": ligand.max_bond_length,
                "bonds_over_2_2A": ligand.bonds_over_2_2,
                "validation_flag": ligand.validation_flag,
            }
        )

    zip_directory(output_dir, output_zip, "*.sdf")
    Path(work_dir, "vina_sdf_mapping_validation.json").write_text(
        json.dumps(validation, indent=2), encoding="utf-8"
    )
    return reconstructed, validation
