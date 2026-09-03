"""Legacy-compatible geometric interaction analysis for reconstructed Vina poses.

This module is PLIP-compatible logic. It does not invoke or impersonate native
PLIP; native PLIP execution for Boltz structures lives in ``plip``.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np

from drug_discovery_agent.config.models import InteractionThresholds

from .distances import ProteinModel
from .poses import PDBQTAtom
from .reconstruction import ReconstructedLigand


COVALENT_RADII = {
    "H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57,
    "P": 1.07, "S": 1.05, "CL": 1.02, "BR": 1.20, "I": 1.39,
}
PROTEIN_RING_ATOMS = {
    "PHE": [("CG", "CD1", "CE1", "CZ", "CE2", "CD2")],
    "TYR": [("CG", "CD1", "CE1", "CZ", "CE2", "CD2")],
    "HIS": [("CG", "ND1", "CE1", "NE2", "CD2")],
    "TRP": [
        ("CG", "CD1", "NE1", "CE2", "CD2"),
        ("CD2", "CE2", "CZ2", "CH2", "CZ3", "CE3"),
    ],
}


@dataclass(slots=True)
class Ring:
    atom_ids: tuple[int, ...]
    centroid: np.ndarray
    normal: np.ndarray
    residue: str | None = None


@dataclass(slots=True)
class ChargeCenter:
    coord: np.ndarray
    positive: bool
    label: str
    atom_ids: tuple[int, ...]


def _chem() -> tuple[object, object, object]:
    try:
        from rdkit import Chem, RDConfig
        from rdkit.Chem import ChemicalFeatures
    except ImportError as exc:
        raise RuntimeError("RDKit is required for Vina interaction analysis") from exc
    return Chem, RDConfig, ChemicalFeatures


def _distance(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.linalg.norm(first - second))


def _mol_coord(molecule: object, atom_index: int) -> np.ndarray:
    point = molecule.GetConformer().GetAtomPosition(atom_index)
    return np.array([point.x, point.y, point.z], dtype=float)


def _unit_normal(coords: Iterable[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    points = np.asarray(list(coords), dtype=float)
    centroid = points.mean(axis=0)
    _, _, vectors = np.linalg.svd(points - centroid, full_matrices=False)
    normal = vectors[-1]
    norm = np.linalg.norm(normal)
    return centroid, normal / norm if norm else np.array([0.0, 0.0, 1.0])


def _angle(first: np.ndarray, vertex: np.ndarray, third: np.ndarray) -> float:
    one, two = first - vertex, third - vertex
    denominator = np.linalg.norm(one) * np.linalg.norm(two)
    if not denominator:
        return float("nan")
    return math.degrees(math.acos(float(np.clip(np.dot(one, two) / denominator, -1.0, 1.0))))


def _acute_normals(first: np.ndarray, second: np.ndarray) -> float:
    return math.degrees(math.acos(float(np.clip(abs(np.dot(first, second)), -1.0, 1.0))))


def _offset(first: np.ndarray, second: np.ndarray, normal: np.ndarray) -> float:
    delta = second - first
    return float(np.linalg.norm(delta - np.dot(delta, normal) * normal))


def _feature_groups(molecule: object) -> dict[str, list[tuple[int, ...]]]:
    _, RDConfig, ChemicalFeatures = _chem()
    factory = ChemicalFeatures.BuildFeatureFactory(str(RDConfig.RDDataDir + "/BaseFeatures.fdef"))
    grouped: dict[str, list[tuple[int, ...]]] = {}
    for feature in factory.GetFeaturesForMol(molecule):
        grouped.setdefault(feature.GetFamily(), []).append(tuple(feature.GetAtomIds()))
    return grouped


def _infer_bonds(protein: ProteinModel) -> dict[int, PDBQTAtom]:
    by_serial = {atom.serial: atom for atom in protein.atoms}
    for atom in protein.atoms:
        atom.neighbors.clear()
    for index, first in enumerate(protein.atoms):
        for second in protein.atoms[index + 1:]:
            same_residue = (first.chain, first.resid) == (second.chain, second.resid)
            peptide = (
                first.chain == second.chain
                and abs(first.resid - second.resid) == 1
                and {first.atom_name, second.atom_name} == {"C", "N"}
            )
            if not (same_residue or peptide):
                continue
            cutoff = COVALENT_RADII.get(first.element, 0.77) + COVALENT_RADII.get(second.element, 0.77)
            cutoff += 0.30 if "H" in (first.element, second.element) else 0.45
            if _distance(np.asarray(first.coord), np.asarray(second.coord)) <= cutoff:
                first.neighbors.add(second.serial)
                second.neighbors.add(first.serial)
    return by_serial


def _protein_rings(protein: ProteinModel) -> list[Ring]:
    rings = []
    for (chain, resid, resname), atoms in protein.by_residue.items():
        by_name = {atom.atom_name: atom for atom in atoms}
        for names in PROTEIN_RING_ATOMS.get(resname, []):
            if all(name in by_name for name in names):
                selected = [by_name[name] for name in names]
                centroid, normal = _unit_normal(np.asarray(atom.coord) for atom in selected)
                rings.append(Ring(tuple(atom.serial for atom in selected), centroid, normal, f"{resname}{resid}"))
    return rings


def _ligand_rings(molecule: object) -> list[Ring]:
    Chem, _, _ = _chem()
    rings = []
    for raw_ids in Chem.GetSymmSSSR(molecule):
        atom_ids = tuple(int(value) for value in raw_ids)
        if len(atom_ids) >= 5 and all(molecule.GetAtomWithIdx(index).GetIsAromatic() for index in atom_ids):
            centroid, normal = _unit_normal(_mol_coord(molecule, index) for index in atom_ids)
            rings.append(Ring(atom_ids, centroid, normal))
    return rings


def _protein_charges(protein: ProteinModel) -> list[ChargeCenter]:
    templates = {
        "LYS": (True, ("NZ",)), "ARG": (True, ("CZ", "NH1", "NH2")),
        "HIS": (True, ("CG", "ND1", "CD2", "CE1", "NE2")),
        "ASP": (False, ("OD1", "OD2")), "GLU": (False, ("OE1", "OE2")),
    }
    centers = []
    for (_, _, resname), atoms in protein.by_residue.items():
        if resname not in templates:
            continue
        positive, names = templates[resname]
        by_name = {atom.atom_name: atom for atom in atoms}
        selected = [by_name[name] for name in names if name in by_name]
        if selected:
            centers.append(
                ChargeCenter(np.mean([atom.coord for atom in selected], axis=0), positive, resname,
                             tuple(atom.serial for atom in selected))
            )
    return centers


def _ligand_charges(molecule: object) -> list[ChargeCenter]:
    centers, seen = [], set()
    for atom in molecule.GetAtoms():
        if atom.GetFormalCharge():
            key = (atom.GetFormalCharge() > 0, (atom.GetIdx(),))
            seen.add(key)
            centers.append(ChargeCenter(_mol_coord(molecule, atom.GetIdx()), key[0], "FormalCharge", key[1]))
    features = _feature_groups(molecule)
    for family, positive, label in (("PosIonizable", True, "BasicGroup"), ("NegIonizable", False, "AcidicGroup")):
        for ids in features.get(family, []):
            atom_ids = tuple(sorted(set(ids)))
            key = (positive, atom_ids)
            if atom_ids and key not in seen:
                seen.add(key)
                centers.append(
                    ChargeCenter(np.mean([_mol_coord(molecule, index) for index in atom_ids], axis=0),
                                 positive, label, atom_ids)
                )
    return centers


def _row(kind: str, protein_atom: PDBQTAtom, distance: float, **details: object) -> dict[str, object]:
    return {
        "interaction_type": kind,
        "protein_chain": protein_atom.chain,
        "residue_name": protein_atom.resname,
        "residue_number": protein_atom.resid,
        "residue": protein_atom.residue,
        "primary_distance_angstrom": round(distance, 4),
        **details,
    }


def analyze_interactions(
    ligand: ReconstructedLigand,
    protein: ProteinModel,
    thresholds: InteractionThresholds | None = None,
) -> list[dict[str, object]]:
    """Calculate all six interaction categories from the legacy workflow."""
    thresholds = thresholds or InteractionThresholds()
    by_serial = _infer_bonds(protein)
    molecule = ligand.mol
    rows: list[dict[str, object]] = []

    # Hydrophobic: shortest ligand contact per protein hydrophobic atom.
    ligand_carbons = [
        atom.GetIdx() for atom in molecule.GetAtoms()
        if atom.GetAtomicNum() == 6 and all(neighbor.GetAtomicNum() in {1, 6} for neighbor in atom.GetNeighbors())
    ]
    protein_carbons = []
    for atom in protein.atoms:
        if atom.element != "C":
            continue
        neighbors = [by_serial[value] for value in atom.neighbors if by_serial[value].element != "H"]
        if neighbors and all(neighbor.element == "C" for neighbor in neighbors):
            protein_carbons.append(atom)
    best: dict[int, tuple[float, int, PDBQTAtom]] = {}
    for ligand_index in ligand_carbons:
        coordinate = _mol_coord(molecule, ligand_index)
        for atom in protein_carbons:
            distance = _distance(coordinate, np.asarray(atom.coord))
            if distance <= thresholds.hydrophobic_distance and (
                atom.serial not in best or distance < best[atom.serial][0]
            ):
                best[atom.serial] = (distance, ligand_index, atom)
    for distance, ligand_index, atom in sorted(best.values(), key=lambda item: (item[0], item[2].serial, item[1])):
        rows.append(_row("Hydrophobic interaction", atom, distance, ligand_atom_index=ligand_index,
                         protein_atom_serial=atom.serial))

    # Hydrogen bonds use explicit PDBQT polar hydrogens.
    features = _feature_groups(molecule)
    ligand_acceptors = sorted({index for ids in features.get("Acceptor", []) for index in ids})
    ligand_donors = sorted({index for ids in features.get("Donor", []) for index in ids})
    protein_acceptors = [atom for atom in protein.atoms if atom.atom_type.upper() in {"OA", "NA", "SA"}]
    protein_donors = []
    for atom in protein.atoms:
        hydrogens = [by_serial[value] for value in atom.neighbors if by_serial[value].element == "H"]
        if atom.element in {"N", "O", "S"} and hydrogens:
            protein_donors.append((atom, hydrogens))
    for donor, hydrogens in protein_donors:
        for acceptor_index in ligand_acceptors:
            acceptor = _mol_coord(molecule, acceptor_index)
            da = _distance(np.asarray(donor.coord), acceptor)
            candidates = [
                (_distance(np.asarray(hydrogen.coord), acceptor), _angle(np.asarray(donor.coord), np.asarray(hydrogen.coord), acceptor))
                for hydrogen in hydrogens
            ]
            candidates = [item for item in candidates if item[1] >= thresholds.hbond_donor_angle_min]
            if da <= thresholds.hbond_distance and candidates:
                ha, angle = min(candidates)
                rows.append(_row("Hydrogen bond", donor, da, donor_acceptor_distance=round(da, 4),
                                 hydrogen_acceptor_distance=round(ha, 4), angle_degrees=round(angle, 2),
                                 protein_role="Donor", ligand_atom_index=acceptor_index,
                                 protein_atom_serial=donor.serial))
    pose_atoms = ligand.pose.atom_by_serial
    for donor_index in ligand_donors:
        parent = ligand.source_to_pdbqt.get(donor_index)
        hydrogens = [pose_atoms[value] for value in ligand.pose.h_parent.get(parent, []) if value in pose_atoms]
        if not hydrogens:
            continue
        donor = _mol_coord(molecule, donor_index)
        for acceptor in protein_acceptors:
            da = _distance(donor, np.asarray(acceptor.coord))
            candidates = [
                (_distance(np.asarray(h.coord), np.asarray(acceptor.coord)),
                 _angle(donor, np.asarray(h.coord), np.asarray(acceptor.coord))) for h in hydrogens
            ]
            candidates = [item for item in candidates if item[1] >= thresholds.hbond_donor_angle_min]
            if da <= thresholds.hbond_distance and candidates:
                ha, angle = min(candidates)
                rows.append(_row("Hydrogen bond", acceptor, da, donor_acceptor_distance=round(da, 4),
                                 hydrogen_acceptor_distance=round(ha, 4), angle_degrees=round(angle, 2),
                                 protein_role="Acceptor", ligand_atom_index=donor_index,
                                 protein_atom_serial=acceptor.serial))

    # Opposite charge centers.
    for ligand_center in _ligand_charges(molecule):
        for protein_center in _protein_charges(protein):
            distance = _distance(ligand_center.coord, protein_center.coord)
            if ligand_center.positive != protein_center.positive and distance <= thresholds.salt_bridge_distance:
                atom = by_serial[protein_center.atom_ids[0]]
                rows.append(_row("Salt bridge", atom, distance, ligand_group=ligand_center.label,
                                 protein_group=protein_center.label,
                                 protein_role="Positive" if protein_center.positive else "Negative"))

    # Aromatic stacking.
    ligand_rings, protein_rings = _ligand_rings(molecule), _protein_rings(protein)
    for ligand_ring in ligand_rings:
        for protein_ring in protein_rings:
            distance = _distance(ligand_ring.centroid, protein_ring.centroid)
            angle = _acute_normals(ligand_ring.normal, protein_ring.normal)
            offset = min(_offset(protein_ring.centroid, ligand_ring.centroid, protein_ring.normal),
                         _offset(ligand_ring.centroid, protein_ring.centroid, ligand_ring.normal))
            parallel = angle <= thresholds.pi_stack_angle_deviation and offset <= thresholds.pi_stack_offset
            perpendicular = abs(90.0 - angle) <= thresholds.pi_stack_angle_deviation and offset <= thresholds.pi_stack_offset
            if distance <= thresholds.pi_stack_distance and (parallel or perpendicular):
                atom = by_serial[protein_ring.atom_ids[0]]
                rows.append(_row("π-stacking", atom, distance, angle_degrees=round(angle, 2),
                                 stacking_type="P" if parallel else "T", offset_angstrom=round(offset, 3),
                                 ligand_ring_atoms=list(ligand_ring.atom_ids),
                                 protein_ring_atoms=list(protein_ring.atom_ids)))

    # Pi-cation in either orientation. Legacy uses a 2.0 A lateral offset.
    for center in [item for item in _ligand_charges(molecule) if item.positive]:
        for ring in protein_rings:
            distance = _distance(center.coord, ring.centroid)
            offset = _offset(ring.centroid, center.coord, ring.normal)
            if distance <= thresholds.pi_cation_distance and offset <= thresholds.pi_cation_offset:
                atom = by_serial[ring.atom_ids[0]]
                rows.append(_row("π-cation interaction", atom, distance, protein_role="Aromatic",
                                 offset_angstrom=round(offset, 3), ligand_group=center.label))
    for ring in ligand_rings:
        for center in [item for item in _protein_charges(protein) if item.positive]:
            distance = _distance(ring.centroid, center.coord)
            offset = _offset(ring.centroid, center.coord, ring.normal)
            if distance <= thresholds.pi_cation_distance and offset <= thresholds.pi_cation_offset:
                atom = by_serial[center.atom_ids[0]]
                rows.append(_row("π-cation interaction", atom, distance, protein_role="Positive",
                                 offset_angstrom=round(offset, 3), ligand_ring_atoms=list(ring.atom_ids)))

    # Halogen bonds; the historical acceptor-angle range is 90--150 degrees.
    for halogen in [atom for atom in molecule.GetAtoms() if atom.GetAtomicNum() in {9, 17, 35, 53}]:
        carbons = [neighbor for neighbor in halogen.GetNeighbors() if neighbor.GetAtomicNum() == 6]
        if not carbons:
            continue
        carbon = carbons[0]
        x_coord, c_coord = _mol_coord(molecule, halogen.GetIdx()), _mol_coord(molecule, carbon.GetIdx())
        for acceptor in protein_acceptors:
            acceptor_coord = np.asarray(acceptor.coord)
            distance = _distance(x_coord, acceptor_coord)
            heavy_bases = [by_serial[value] for value in acceptor.neighbors if by_serial[value].element != "H"]
            if not heavy_bases:
                continue
            base = min(heavy_bases, key=lambda atom: _distance(np.asarray(atom.coord), acceptor_coord))
            donor_angle = _angle(c_coord, x_coord, acceptor_coord)
            acceptor_angle = _angle(np.asarray(base.coord), acceptor_coord, x_coord)
            if (distance <= thresholds.halogen_distance
                    and donor_angle >= thresholds.halogen_donor_angle_min
                    and thresholds.halogen_acceptor_angle_min <= acceptor_angle
                    <= thresholds.halogen_acceptor_angle_max):
                rows.append(_row("Halogen bond", acceptor, distance, donor_angle_degrees=round(donor_angle, 2),
                                 acceptor_angle_degrees=round(acceptor_angle, 2),
                                 ligand_atom_index=halogen.GetIdx(), protein_atom_serial=acceptor.serial))

    order = {
        "Hydrophobic interaction": 0, "Hydrogen bond": 1, "Salt bridge": 2,
        "π-stacking": 3, "π-cation interaction": 4, "Halogen bond": 5,
    }
    rows.sort(key=lambda row: (order[row["interaction_type"]], row["residue_number"], row["primary_distance_angstrom"]))
    return rows


def binding_site_residues(
    ligand: ReconstructedLigand,
    protein: ProteinModel,
    interactions: list[dict[str, object]],
    *,
    cutoff: float = 7.5,
) -> list[dict[str, object]]:
    ligand_coordinates = np.asarray([_mol_coord(ligand.mol, index) for index in range(ligand.mol.GetNumAtoms())])
    interacting = {row["residue"] for row in interactions}
    rows = []
    for (chain, residue_number, residue_name), atoms in sorted(protein.by_residue.items(), key=lambda item: (item[0][0], item[0][1])):
        heavy = np.asarray([atom.coord for atom in atoms if atom.element != "H"])
        if not heavy.size:
            continue
        distance = float(np.sqrt(np.square(heavy[:, None, :] - ligand_coordinates[None, :, :]).sum(axis=2).min()))
        residue = f"{residue_name}{residue_number}"
        if distance <= cutoff:
            rows.append({"protein_chain": chain, "residue": residue, "residue_name": residue_name,
                         "residue_number": residue_number, "interaction_contact": residue in interacting,
                         "minimum_distance_angstrom": round(distance, 4)})
    return rows
