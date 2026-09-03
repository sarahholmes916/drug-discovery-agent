from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .poses import VinaPose


@dataclass(slots=True)
class ReconstructedLigand:
    molecule: str
    mol: object
    pose: VinaPose
    source_to_pdbqt: dict[int, int]
    mapping_method: str
    median_bond_length: float
    max_bond_length: float
    bonds_over_2_2: int
    validation_flag: str


def _chem() -> object:
    try:
        from rdkit import Chem
    except ImportError as exc:
        raise RuntimeError("RDKit is required for Vina SDF reconstruction") from exc
    return Chem


def load_sdf(path: str | Path) -> object:
    Chem = _chem()
    supplier = Chem.SDMolSupplier(str(path), removeHs=True, sanitize=True)
    if not supplier or supplier[0] is None:
        raise ValueError(f"RDKit could not read {path}")
    return supplier[0]


def reconstruct_ligand(source_sdf: str | Path, pose: VinaPose) -> ReconstructedLigand:
    """Transfer mode coordinates using the source graph and Meeko index remarks."""
    Chem = _chem()
    source = load_sdf(source_sdf)
    if not pose.smiles:
        raise ValueError(f"no REMARK SMILES in {pose.source_file}")
    query = Chem.MolFromSmiles(pose.smiles)
    if query is None:
        raise ValueError(f"RDKit could not parse embedded SMILES for {pose.molecule}")
    if source.GetNumAtoms() != query.GetNumAtoms():
        raise ValueError(
            f"atom-count mismatch for {pose.molecule}: SDF={source.GetNumAtoms()} embedded={query.GetNumAtoms()}"
        )

    match = source.GetSubstructMatch(query, useChirality=False)
    mapping_method = "SDF.GetSubstructMatch(embedded SMILES)"
    if len(match) != query.GetNumAtoms():
        reverse = query.GetSubstructMatch(source, useChirality=False)
        if len(reverse) != source.GetNumAtoms():
            raise ValueError(f"no complete molecular-graph match for {pose.molecule}")
        query_to_source = {query_index: source_index for source_index, query_index in enumerate(reverse)}
        match = tuple(query_to_source[index] for index in range(query.GetNumAtoms()))
        mapping_method = "embedded SMILES.GetSubstructMatch(SDF), inverted"

    by_serial = pose.atom_by_serial
    source_to_pdbqt: dict[int, int] = {}
    conformer = Chem.Conformer(source.GetNumAtoms())
    conformer.Set3D(True)
    for query_index, source_index in enumerate(match):
        serial = pose.smiles_to_pdbqt.get(query_index + 1)
        if serial is None or serial not in by_serial:
            raise ValueError(
                f"missing PDBQT coordinate for embedded-SMILES atom {query_index + 1} in {pose.molecule}"
            )
        source_to_pdbqt[source_index] = serial
        conformer.SetAtomPosition(source_index, by_serial[serial].coord)

    result = Chem.Mol(source)
    result.RemoveAllConformers()
    result.AddConformer(conformer, assignId=True)
    result.SetProp("_Name", f"{pose.molecule}_vina_mode{pose.mode}")
    result.SetProp("VINA_MODE", str(pose.mode))
    if pose.affinity is not None:
        result.SetProp("VINA_AFFINITY_KCAL_MOL", f"{pose.affinity:.6f}")

    coords = result.GetConformer()
    lengths = []
    for bond in result.GetBonds():
        first = np.asarray(coords.GetAtomPosition(bond.GetBeginAtomIdx()), dtype=float)
        second = np.asarray(coords.GetAtomPosition(bond.GetEndAtomIdx()), dtype=float)
        lengths.append(float(np.linalg.norm(first - second)))
    median = float(np.median(lengths)) if lengths else 0.0
    maximum = float(max(lengths)) if lengths else 0.0
    over = sum(length > 2.2 for length in lengths)
    return ReconstructedLigand(
        molecule=pose.molecule,
        mol=result,
        pose=pose,
        source_to_pdbqt=source_to_pdbqt,
        mapping_method=mapping_method,
        median_bond_length=median,
        max_bond_length=maximum,
        bonds_over_2_2=over,
        validation_flag="Review PDBQT geometry" if over else "OK",
    )


def write_sdf(molecule: object, path: str | Path) -> None:
    Chem = _chem()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    writer = Chem.SDWriter(str(target))
    try:
        writer.write(molecule)
    finally:
        writer.close()

