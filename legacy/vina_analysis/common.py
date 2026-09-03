"""Shared parsing, geometry, and atom-mapping utilities.

This module is intentionally dependency-light apart from NumPy and RDKit.
It parses AutoDock Vina PDBQT files directly, maps Vina coordinates back to
source-SDF chemistry using Meeko's REMARK SMILES / REMARK SMILES IDX records,
and parses the prepared protein receptor PDBQT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator
import csv
import math
import re
import zipfile

import numpy as np
from rdkit import Chem
from rdkit.Chem import ChemicalFeatures
from rdkit import RDConfig


COVALENT_RADII = {
    "H": 0.31,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "P": 1.07,
    "S": 1.05,
    "CL": 1.02,
    "BR": 1.20,
    "I": 1.39,
}


@dataclass(slots=True)
class PDBQTAtom:
    serial: int
    atom_name: str
    resname: str
    chain: str
    resid: int
    coord: np.ndarray
    charge: float | None
    atom_type: str
    element: str
    record: str = "ATOM"
    neighbors: set[int] = field(default_factory=set)

    @property
    def residue(self) -> str:
        return f"{self.resname}{self.resid}"


@dataclass(slots=True)
class VinaPose:
    molecule: str
    mode: int
    affinity: float | None
    rmsd_lb: float | None
    rmsd_ub: float | None
    atoms: list[PDBQTAtom]
    smiles: str | None
    smiles_to_pdbqt: dict[int, int]
    h_parent: dict[int, list[int]]
    source_file: Path

    @property
    def atom_by_serial(self) -> dict[int, PDBQTAtom]:
        return {a.serial: a for a in self.atoms}

    @property
    def heavy_atoms(self) -> list[PDBQTAtom]:
        return [a for a in self.atoms if a.element != "H"]


@dataclass(slots=True)
class ReconstructedLigand:
    molecule: str
    mol: Chem.Mol
    pose: VinaPose
    source_to_pdbqt: dict[int, int]
    mapping_method: str
    median_bond_length: float
    max_bond_length: float
    bonds_over_2_2: int
    validation_flag: str


@dataclass(slots=True)
class ProteinModel:
    atoms: list[PDBQTAtom]
    by_serial: dict[int, PDBQTAtom]
    by_residue: dict[tuple[str, int, str], list[PDBQTAtom]]


@dataclass(slots=True)
class Ring:
    atom_ids: tuple[int, ...]
    centroid: np.ndarray
    normal: np.ndarray
    label: str
    residue: str | None = None


def normalize_element(atom_name: str, atom_type: str) -> str:
    """Infer chemical element from PDBQT atom name/type."""
    atom_type = atom_type.upper()
    atom_name = atom_name.strip().upper()
    if atom_type.startswith("CL") or atom_name.startswith("CL"):
        return "CL"
    if atom_type.startswith("BR") or atom_name.startswith("BR"):
        return "BR"
    if atom_type.startswith("HD") or atom_name.startswith("H"):
        return "H"
    if atom_type.startswith("OA") or atom_type == "O":
        return "O"
    if atom_type.startswith("NA") or atom_type == "N":
        return "N"
    if atom_type.startswith("SA") or atom_type == "S":
        return "S"
    if atom_type.startswith("P"):
        return "P"
    if atom_type.startswith("F"):
        return "F"
    if atom_type == "I" or atom_name.startswith("I"):
        return "I"
    return "C"


def parse_pdbqt_atom(line: str) -> PDBQTAtom:
    """Parse a fixed-width PDBQT ATOM/HETATM line."""
    parts = line.split()
    charge: float | None = None
    try:
        charge = float(parts[-2])
    except (ValueError, IndexError):
        pass
    atom_type = parts[-1]
    return PDBQTAtom(
        serial=int(line[6:11]),
        atom_name=line[12:16].strip(),
        resname=line[17:20].strip() or "UNL",
        chain=line[21:22].strip(),
        resid=int(line[22:26]),
        coord=np.array(
            [float(line[30:38]), float(line[38:46]), float(line[46:54])],
            dtype=float,
        ),
        charge=charge,
        atom_type=atom_type,
        element=normalize_element(line[12:16], atom_type),
        record=line[0:6].strip(),
    )


def read_top40(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def unzip_archive(zip_path: str | Path, output_dir: str | Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(output_dir)
    return output_dir


def locate_files(root: str | Path, suffix: str) -> dict[str, Path]:
    """Index files by basename with the provided suffix removed."""
    root = Path(root)
    out: dict[str, Path] = {}
    for path in root.rglob(f"*{suffix}"):
        out[path.name[: -len(suffix)]] = path
    return out


def _parse_remark_pairs(line: str, prefix: str) -> list[tuple[int, int]]:
    values = [int(x) for x in line.strip().split(prefix, 1)[1].split()]
    if len(values) % 2:
        raise ValueError(f"Odd number of values in {prefix!r} record: {line.strip()}")
    return list(zip(values[0::2], values[1::2]))


def parse_vina_poses(path: str | Path, molecule: str | None = None) -> list[VinaPose]:
    """Parse every MODEL from a Vina/Meeko PDBQT output."""
    path = Path(path)
    molecule = molecule or path.name.removesuffix("_out.pdbqt")
    poses: list[VinaPose] = []

    mode: int | None = None
    affinity = rmsd_lb = rmsd_ub = None
    atoms: list[PDBQTAtom] = []
    smiles: str | None = None
    smiles_to_pdbqt: dict[int, int] = {}
    h_parent: dict[int, list[int]] = {}

    def finish() -> None:
        nonlocal mode, affinity, rmsd_lb, rmsd_ub, atoms, smiles, smiles_to_pdbqt, h_parent
        if mode is None:
            return
        poses.append(
            VinaPose(
                molecule=molecule,
                mode=mode,
                affinity=affinity,
                rmsd_lb=rmsd_lb,
                rmsd_ub=rmsd_ub,
                atoms=atoms,
                smiles=smiles,
                smiles_to_pdbqt=smiles_to_pdbqt,
                h_parent=h_parent,
                source_file=path,
            )
        )
        mode = None
        affinity = rmsd_lb = rmsd_ub = None
        atoms = []
        smiles = None
        smiles_to_pdbqt = {}
        h_parent = {}

    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("MODEL"):
                finish()
                mode = int(line.split()[1])
            elif line.startswith("ENDMDL"):
                finish()
            elif mode is not None and line.startswith("REMARK VINA RESULT:"):
                values = line.split("RESULT:", 1)[1].split()
                affinity, rmsd_lb, rmsd_ub = map(float, values[:3])
            elif mode is not None and line.startswith("REMARK SMILES IDX"):
                for smiles_idx, serial in _parse_remark_pairs(line, "REMARK SMILES IDX"):
                    smiles_to_pdbqt[smiles_idx] = serial
            elif mode is not None and line.startswith("REMARK H PARENT"):
                for parent, hydrogen in _parse_remark_pairs(line, "REMARK H PARENT"):
                    h_parent.setdefault(parent, []).append(hydrogen)
            elif mode is not None and line.startswith("REMARK SMILES "):
                smiles = line.split("REMARK SMILES ", 1)[1].strip()
            elif mode is not None and line.startswith(("ATOM", "HETATM")):
                atoms.append(parse_pdbqt_atom(line))
    finish()
    return poses


def mode1_pose(path: str | Path, molecule: str | None = None) -> VinaPose:
    poses = parse_vina_poses(path, molecule)
    for pose in poses:
        if pose.mode == 1:
            return pose
    raise ValueError(f"No mode 1 found in {path}")


def _bond_cutoff(a: PDBQTAtom, b: PDBQTAtom) -> float:
    base = COVALENT_RADII.get(a.element, 0.77) + COVALENT_RADII.get(b.element, 0.77)
    return base + (0.30 if "H" in (a.element, b.element) else 0.45)


def infer_pdbqt_bonds(atoms: list[PDBQTAtom], include_peptide: bool = True) -> None:
    """Infer local covalent bonds using residue identity and covalent radii."""
    for atom in atoms:
        atom.neighbors.clear()
    for i, a in enumerate(atoms):
        for b in atoms[i + 1 :]:
            same_residue = (a.chain, a.resid) == (b.chain, b.resid)
            peptide = (
                include_peptide
                and a.chain == b.chain
                and abs(a.resid - b.resid) == 1
                and {a.atom_name, b.atom_name} == {"C", "N"}
            )
            if not (same_residue or peptide):
                continue
            if np.linalg.norm(a.coord - b.coord) <= _bond_cutoff(a, b):
                a.neighbors.add(b.serial)
                b.neighbors.add(a.serial)


def parse_receptor(path: str | Path) -> ProteinModel:
    atoms = [
        parse_pdbqt_atom(line)
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith(("ATOM", "HETATM"))
    ]
    infer_pdbqt_bonds(atoms, include_peptide=True)
    by_serial = {a.serial: a for a in atoms}
    by_residue: dict[tuple[str, int, str], list[PDBQTAtom]] = {}
    for atom in atoms:
        by_residue.setdefault((atom.chain, atom.resid, atom.resname), []).append(atom)
    return ProteinModel(atoms=atoms, by_serial=by_serial, by_residue=by_residue)


def load_sdf(path: str | Path) -> Chem.Mol:
    supplier = Chem.SDMolSupplier(str(path), removeHs=True, sanitize=True)
    if not supplier or supplier[0] is None:
        raise ValueError(f"RDKit could not read {path}")
    return supplier[0]


def reconstruct_ligand(source_sdf: str | Path, pose: VinaPose) -> ReconstructedLigand:
    """Transfer Vina mode coordinates to the source-SDF molecular graph.

    Meeko writes both the canonical docking SMILES and an atom-index map. The
    source SDF is graph-matched to that SMILES, after which each source atom is
    assigned its corresponding PDBQT coordinate.
    """
    source = load_sdf(source_sdf)
    if not pose.smiles:
        raise ValueError(f"No REMARK SMILES in {pose.source_file}")
    query = Chem.MolFromSmiles(pose.smiles)
    if query is None:
        raise ValueError(f"RDKit could not parse embedded SMILES for {pose.molecule}")
    if source.GetNumAtoms() != query.GetNumAtoms():
        raise ValueError(
            f"Atom-count mismatch for {pose.molecule}: SDF={source.GetNumAtoms()} "
            f"embedded SMILES={query.GetNumAtoms()}"
        )

    # Query-atom index -> source-atom index.
    match = source.GetSubstructMatch(query, useChirality=False)
    mapping_method = "SDF.GetSubstructMatch(embedded SMILES)"
    if len(match) != query.GetNumAtoms():
        # Reverse matching is useful when sanitization/kekulization differs.
        reverse = query.GetSubstructMatch(source, useChirality=False)
        if len(reverse) != source.GetNumAtoms():
            raise ValueError(f"No complete molecular-graph match for {pose.molecule}")
        # reverse[source_idx] = query_idx
        query_to_source = {q_idx: s_idx for s_idx, q_idx in enumerate(reverse)}
        match = tuple(query_to_source[q_idx] for q_idx in range(query.GetNumAtoms()))
        mapping_method = "embedded SMILES.GetSubstructMatch(SDF), inverted"

    atom_by_serial = pose.atom_by_serial
    source_to_pdbqt: dict[int, int] = {}
    conformer = Chem.Conformer(source.GetNumAtoms())
    conformer.Set3D(True)
    for query_idx, source_idx in enumerate(match):
        pdbqt_serial = pose.smiles_to_pdbqt.get(query_idx + 1)
        if pdbqt_serial is None or pdbqt_serial not in atom_by_serial:
            raise ValueError(
                f"Missing PDBQT coordinate for embedded-SMILES atom {query_idx + 1} "
                f"in {pose.molecule}"
            )
        source_to_pdbqt[source_idx] = pdbqt_serial
        xyz = atom_by_serial[pdbqt_serial].coord
        conformer.SetAtomPosition(source_idx, tuple(float(v) for v in xyz))

    result = Chem.Mol(source)
    result.RemoveAllConformers()
    result.AddConformer(conformer, assignId=True)
    result.SetProp("_Name", f"{pose.molecule}_vina_mode{pose.mode}")
    result.SetProp("VINA_MODE", str(pose.mode))
    if pose.affinity is not None:
        result.SetProp("VINA_AFFINITY_KCAL_MOL", f"{pose.affinity:.6f}")

    lengths: list[float] = []
    conf = result.GetConformer()
    for bond in result.GetBonds():
        p1 = np.array(conf.GetAtomPosition(bond.GetBeginAtomIdx()))
        p2 = np.array(conf.GetAtomPosition(bond.GetEndAtomIdx()))
        lengths.append(float(np.linalg.norm(p1 - p2)))
    median = float(np.median(lengths)) if lengths else 0.0
    maximum = float(max(lengths)) if lengths else 0.0
    over = sum(d > 2.2 for d in lengths)
    flag = "Review PDBQT geometry" if over else "OK"

    return ReconstructedLigand(
        molecule=pose.molecule,
        mol=result,
        pose=pose,
        source_to_pdbqt=source_to_pdbqt,
        mapping_method=mapping_method,
        median_bond_length=median,
        max_bond_length=maximum,
        bonds_over_2_2=over,
        validation_flag=flag,
    )


def write_sdf(mol: Chem.Mol, path: str | Path) -> None:
    writer = Chem.SDWriter(str(path))
    try:
        writer.write(mol)
    finally:
        writer.close()


def feature_factory() -> ChemicalFeatures.MolChemicalFeatureFactory:
    return ChemicalFeatures.BuildFeatureFactory(str(Path(RDConfig.RDDataDir) / "BaseFeatures.fdef"))


def ligand_features(mol: Chem.Mol) -> dict[str, list[tuple[int, ...]]]:
    """Return RDKit feature atom ids grouped by feature family."""
    grouped: dict[str, list[tuple[int, ...]]] = {}
    for feature in feature_factory().GetFeaturesForMol(mol):
        grouped.setdefault(feature.GetFamily(), []).append(tuple(feature.GetAtomIds()))
    return grouped


def unit_normal(coords: Iterable[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    points = np.asarray(list(coords), dtype=float)
    centroid = points.mean(axis=0)
    centered = points - centroid
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    normal = vh[-1]
    norm = np.linalg.norm(normal)
    if norm == 0:
        normal = np.array([0.0, 0.0, 1.0])
    else:
        normal = normal / norm
    return centroid, normal


def acute_angle_degrees(v1: np.ndarray, v2: np.ndarray) -> float:
    dot = float(np.clip(abs(np.dot(v1, v2)), -1.0, 1.0))
    return math.degrees(math.acos(dot))


def angle_degrees(a: np.ndarray, vertex: np.ndarray, c: np.ndarray) -> float:
    v1 = a - vertex
    v2 = c - vertex
    denom = np.linalg.norm(v1) * np.linalg.norm(v2)
    if denom == 0:
        return float("nan")
    cosine = float(np.clip(np.dot(v1, v2) / denom, -1.0, 1.0))
    return math.degrees(math.acos(cosine))


def lateral_offset(center_a: np.ndarray, center_b: np.ndarray, normal: np.ndarray) -> float:
    delta = center_b - center_a
    perpendicular = delta - np.dot(delta, normal) * normal
    return float(np.linalg.norm(perpendicular))


def format_coord(coord: np.ndarray) -> str:
    return "(" + ", ".join(f"{float(x):.3f}" for x in coord) + ")"


def residue_sidechain(atom: PDBQTAtom) -> bool:
    return atom.atom_name not in {"N", "CA", "C", "O", "OXT"}


def zip_directory(directory: str | Path, output_zip: str | Path, pattern: str = "*") -> None:
    directory = Path(directory)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(directory.glob(pattern)):
            if path.is_file():
                zf.write(path, arcname=path.name)
