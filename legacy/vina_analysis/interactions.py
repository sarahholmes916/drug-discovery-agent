"""PLIP-compatible interaction analysis for reconstructed Vina mode-1 poses.

Important: this is a transparent geometric/chemical rule implementation. It
uses PLIP 3.0-style default thresholds and the same output categories, but it
does not invoke native PLIP/Open Babel. The exact rows from the original run
are also included in reference_outputs/reference_run.json in this bundle.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable
import json
import math

import numpy as np
from rdkit import Chem

from common import (
    PDBQTAtom,
    ProteinModel,
    ReconstructedLigand,
    Ring,
    acute_angle_degrees,
    angle_degrees,
    format_coord,
    lateral_offset,
    ligand_features,
    parse_receptor,
    residue_sidechain,
    unit_normal,
)


# PLIP 3.0-compatible thresholds used in the original notebook implementation.
HYDROPH_DIST_MAX = 4.0
HBOND_DIST_MAX = 4.1
HBOND_DON_ANGLE_MIN = 100.0
SALTBRIDGE_DIST_MAX = 5.5
PISTACK_DIST_MAX = 5.5
PISTACK_ANG_DEV = 30.0
PISTACK_OFFSET_MAX = 2.0
PICATION_DIST_MAX = 6.0
PICATION_OFFSET_MAX = 2.0
HALOGEN_DIST_MAX = 4.0
HALOGEN_DON_ANGLE_MIN = 135.0
HALOGEN_ACC_ANGLE_MIN = 90.0
HALOGEN_ACC_ANGLE_MAX = 150.0
BINDING_SITE_CUTOFF = 7.5


INTERACTION_TYPES = [
    "Hydrophobic interaction",
    "Hydrogen bond",
    "Salt bridge",
    "π-stacking",
    "π-cation interaction",
    "Halogen bond",
]


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
class ChargeCenter:
    coord: np.ndarray
    positive: bool
    label: str
    atom_ids: tuple[int, ...]
    residue: str | None = None
    residue_name: str | None = None
    residue_number: int | None = None
    chain: str | None = None


def distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def mol_coord(mol: Chem.Mol, atom_idx: int) -> np.ndarray:
    point = mol.GetConformer().GetAtomPosition(atom_idx)
    return np.array([point.x, point.y, point.z], dtype=float)


def center_of_mol_atoms(mol: Chem.Mol, atom_ids: Iterable[int]) -> np.ndarray:
    coords = [mol_coord(mol, idx) for idx in atom_ids]
    return np.mean(np.asarray(coords), axis=0)


def protein_acceptors(protein: ProteinModel) -> list[PDBQTAtom]:
    return [a for a in protein.atoms if a.atom_type.upper() in {"OA", "NA", "SA"}]


def protein_donors(protein: ProteinModel) -> list[tuple[PDBQTAtom, list[PDBQTAtom]]]:
    out = []
    for atom in protein.atoms:
        if atom.element not in {"N", "O", "S"}:
            continue
        hydrogens = [protein.by_serial[n] for n in atom.neighbors if protein.by_serial[n].element == "H"]
        if hydrogens:
            out.append((atom, hydrogens))
    return out


def protein_hydrophobic_atoms(protein: ProteinModel) -> list[PDBQTAtom]:
    out = []
    for atom in protein.atoms:
        if atom.element != "C":
            continue
        heavy_neighbors = [protein.by_serial[n] for n in atom.neighbors if protein.by_serial[n].element != "H"]
        if heavy_neighbors and all(n.element == "C" for n in heavy_neighbors):
            out.append(atom)
    return out


def ligand_hydrophobic_atoms(mol: Chem.Mol) -> list[int]:
    return [
        atom.GetIdx()
        for atom in mol.GetAtoms()
        if atom.GetAtomicNum() == 6
        and all(neighbor.GetAtomicNum() in {1, 6} for neighbor in atom.GetNeighbors())
    ]


def protein_rings(protein: ProteinModel) -> list[Ring]:
    rings: list[Ring] = []
    for (chain, resid, resname), atoms in protein.by_residue.items():
        templates = PROTEIN_RING_ATOMS.get(resname, [])
        by_name = {a.atom_name: a for a in atoms}
        for template in templates:
            if not all(name in by_name for name in template):
                continue
            selected = [by_name[name] for name in template]
            centroid, normal = unit_normal(a.coord for a in selected)
            rings.append(
                Ring(
                    atom_ids=tuple(a.serial for a in selected),
                    centroid=centroid,
                    normal=normal,
                    label=resname,
                    residue=f"{resname}{resid}",
                )
            )
    return rings


def ligand_rings(mol: Chem.Mol) -> list[Ring]:
    rings: list[Ring] = []
    for ring_ids in Chem.GetSymmSSSR(mol):
        ids = tuple(int(x) for x in ring_ids)
        if len(ids) < 5 or not all(mol.GetAtomWithIdx(i).GetIsAromatic() for i in ids):
            continue
        centroid, normal = unit_normal(mol_coord(mol, i) for i in ids)
        rings.append(Ring(atom_ids=ids, centroid=centroid, normal=normal, label="Aromatic"))
    return rings


def protein_charge_centers(protein: ProteinModel) -> list[ChargeCenter]:
    centers: list[ChargeCenter] = []
    templates = {
        "LYS": (True, ("NZ",)),
        "ARG": (True, ("CZ", "NH1", "NH2")),
        "HIS": (True, ("CG", "ND1", "CD2", "CE1", "NE2")),
        "ASP": (False, ("OD1", "OD2")),
        "GLU": (False, ("OE1", "OE2")),
    }
    for (chain, resid, resname), atoms in protein.by_residue.items():
        if resname not in templates:
            continue
        positive, names = templates[resname]
        by_name = {a.atom_name: a for a in atoms}
        selected = [by_name[name] for name in names if name in by_name]
        if not selected:
            continue
        centers.append(
            ChargeCenter(
                coord=np.mean([a.coord for a in selected], axis=0),
                positive=positive,
                label=resname,
                atom_ids=tuple(a.serial for a in selected),
                residue=f"{resname}{resid}",
                residue_name=resname,
                residue_number=resid,
                chain=chain,
            )
        )
    return centers


def ligand_charge_centers(mol: Chem.Mol) -> list[ChargeCenter]:
    features = ligand_features(mol)
    centers: list[ChargeCenter] = []
    seen: set[tuple[bool, tuple[int, ...]]] = set()

    for atom in mol.GetAtoms():
        charge = atom.GetFormalCharge()
        if charge:
            key = (charge > 0, (atom.GetIdx(),))
            if key not in seen:
                seen.add(key)
                centers.append(
                    ChargeCenter(
                        coord=mol_coord(mol, atom.GetIdx()),
                        positive=charge > 0,
                        label="FormalCharge",
                        atom_ids=(atom.GetIdx(),),
                    )
                )

    for family, positive, label in [
        ("PosIonizable", True, "BasicGroup"),
        ("NegIonizable", False, "AcidicGroup"),
    ]:
        for ids in features.get(family, []):
            ids = tuple(sorted(set(ids)))
            key = (positive, ids)
            if not ids or key in seen:
                continue
            seen.add(key)
            aromatic_n = sum(
                mol.GetAtomWithIdx(i).GetIsAromatic() and mol.GetAtomWithIdx(i).GetAtomicNum() == 7
                for i in ids
            )
            group_label = "Imidazole" if positive and aromatic_n >= 1 and len(ids) <= 6 else label
            centers.append(
                ChargeCenter(
                    coord=center_of_mol_atoms(mol, ids),
                    positive=positive,
                    label=group_label,
                    atom_ids=ids,
                )
            )
    return centers


def protein_acceptor_base(protein: ProteinModel, acceptor: PDBQTAtom) -> PDBQTAtom | None:
    heavy = [protein.by_serial[n] for n in acceptor.neighbors if protein.by_serial[n].element != "H"]
    if not heavy:
        return None
    return min(heavy, key=lambda x: distance(x.coord, acceptor.coord))


def _base_row(ligand: ReconstructedLigand, interaction_type: str, protein_atom: PDBQTAtom | None) -> dict:
    residue = protein_atom.residue if protein_atom is not None else None
    resname = protein_atom.resname if protein_atom is not None else None
    resid = protein_atom.resid if protein_atom is not None else None
    chain = protein_atom.chain if protein_atom is not None else None
    report = f"vina_interactions/vina_{ligand.molecule}/vina_{ligand.molecule}_report.xml"
    return {
        "Report XML": report,
        "Method": "Vina",
        "Ligand": f"vina_{ligand.molecule}",
        "Binding Site": 1,
        "Ligand ID": "LIG",
        "Ligand Chain": "L",
        "Ligand Position": 1,
        "Ligand SMILES": ligand.pose.smiles or Chem.MolToSmiles(ligand.mol),
        "Interaction Type": interaction_type,
        "Residue": residue,
        "Residue Name": resname,
        "Residue Number": resid,
        "Protein Chain": chain,
        "Ligand Residue": "LIG1:L",
        "Primary Distance (Å)": None,
        "D-A Distance (Å)": None,
        "H-A Distance (Å)": None,
        "Angle (°)": None,
        "Sidechain": None,
        "Protein Role": None,
        "PLIP Interaction ID": None,
        "Ligand Atom Index Info": None,
        "Protein Atom Index Info": None,
        "Ligand Coord": None,
        "Protein Coord": None,
        "Extra": None,
    }


def hydrophobic_interactions(ligand: ReconstructedLigand, protein: ProteinModel) -> list[dict]:
    candidates: list[tuple[float, int, PDBQTAtom]] = []
    for ligand_idx in ligand_hydrophobic_atoms(ligand.mol):
        ligand_coord = mol_coord(ligand.mol, ligand_idx)
        for protein_atom in protein_hydrophobic_atoms(protein):
            d = distance(ligand_coord, protein_atom.coord)
            if d <= HYDROPH_DIST_MAX:
                candidates.append((d, ligand_idx, protein_atom))

    # PLIP suppresses many redundant atom-pair contacts. Keeping the shortest
    # ligand contact for each protein hydrophobic atom closely reproduces that
    # behavior while remaining deterministic.
    best_by_protein: dict[int, tuple[float, int, PDBQTAtom]] = {}
    for candidate in sorted(candidates):
        d, ligand_idx, protein_atom = candidate
        previous = best_by_protein.get(protein_atom.serial)
        if previous is None or d < previous[0]:
            best_by_protein[protein_atom.serial] = candidate

    rows = []
    for interaction_id, (d, ligand_idx, protein_atom) in enumerate(
        sorted(best_by_protein.values(), key=lambda x: (x[0], x[2].serial, x[1])), 1
    ):
        row = _base_row(ligand, "Hydrophobic interaction", protein_atom)
        row.update(
            {
                "Primary Distance (Å)": round(d, 4),
                "PLIP Interaction ID": interaction_id,
                "Ligand Atom Index Info": f"ligcarbonidx={ligand_idx}",
                "Protein Atom Index Info": f"protcarbonidx={protein_atom.serial}",
                "Ligand Coord": format_coord(mol_coord(ligand.mol, ligand_idx)),
                "Protein Coord": format_coord(protein_atom.coord),
            }
        )
        rows.append(row)
    return rows


def hydrogen_bonds(ligand: ReconstructedLigand, protein: ProteinModel) -> list[dict]:
    features = ligand_features(ligand.mol)
    ligand_acceptors = sorted({i for ids in features.get("Acceptor", []) for i in ids})
    ligand_donors = sorted({i for ids in features.get("Donor", []) for i in ids})
    pose_atoms = ligand.pose.atom_by_serial
    rows: list[dict] = []
    seen: set[tuple[str, int, int]] = set()

    # Protein donor -> ligand acceptor.
    for donor, hydrogens in protein_donors(protein):
        for acceptor_idx in ligand_acceptors:
            acceptor_coord = mol_coord(ligand.mol, acceptor_idx)
            da = distance(donor.coord, acceptor_coord)
            if da > HBOND_DIST_MAX:
                continue
            best = None
            for hydrogen in hydrogens:
                angle = angle_degrees(donor.coord, hydrogen.coord, acceptor_coord)
                ha = distance(hydrogen.coord, acceptor_coord)
                if angle >= HBOND_DON_ANGLE_MIN and (best is None or ha < best[0]):
                    best = (ha, angle, hydrogen)
            if best is None:
                continue
            key = ("P", donor.serial, acceptor_idx)
            if key in seen:
                continue
            seen.add(key)
            ha, angle, _ = best
            row = _base_row(ligand, "Hydrogen bond", donor)
            row.update(
                {
                    "Primary Distance (Å)": round(da, 4),
                    "D-A Distance (Å)": round(da, 4),
                    "H-A Distance (Å)": round(ha, 4),
                    "Angle (°)": round(angle, 2),
                    "Sidechain": str(residue_sidechain(donor)),
                    "Protein Role": "Donor",
                    "Ligand Atom Index Info": f"acceptoridx={acceptor_idx}",
                    "Protein Atom Index Info": f"donoridx={donor.serial}",
                    "Ligand Coord": format_coord(acceptor_coord),
                    "Protein Coord": format_coord(donor.coord),
                    "Extra": f"donortype={donor.atom_type}; acceptortype={ligand.mol.GetAtomWithIdx(acceptor_idx).GetSymbol()}",
                }
            )
            rows.append(row)

    # Ligand donor -> protein acceptor.
    for donor_idx in ligand_donors:
        parent_serial = ligand.source_to_pdbqt.get(donor_idx)
        hydrogen_serials = ligand.pose.h_parent.get(parent_serial, []) if parent_serial else []
        hydrogens = [pose_atoms[s] for s in hydrogen_serials if s in pose_atoms]
        if not hydrogens:
            continue
        donor_coord = mol_coord(ligand.mol, donor_idx)
        for acceptor in protein_acceptors(protein):
            da = distance(donor_coord, acceptor.coord)
            if da > HBOND_DIST_MAX:
                continue
            best = None
            for hydrogen in hydrogens:
                angle = angle_degrees(donor_coord, hydrogen.coord, acceptor.coord)
                ha = distance(hydrogen.coord, acceptor.coord)
                if angle >= HBOND_DON_ANGLE_MIN and (best is None or ha < best[0]):
                    best = (ha, angle, hydrogen)
            if best is None:
                continue
            key = ("L", donor_idx, acceptor.serial)
            if key in seen:
                continue
            seen.add(key)
            ha, angle, _ = best
            row = _base_row(ligand, "Hydrogen bond", acceptor)
            row.update(
                {
                    "Primary Distance (Å)": round(da, 4),
                    "D-A Distance (Å)": round(da, 4),
                    "H-A Distance (Å)": round(ha, 4),
                    "Angle (°)": round(angle, 2),
                    "Sidechain": str(residue_sidechain(acceptor)),
                    "Protein Role": "Acceptor",
                    "Ligand Atom Index Info": f"donoridx={donor_idx}",
                    "Protein Atom Index Info": f"acceptoridx={acceptor.serial}",
                    "Ligand Coord": format_coord(donor_coord),
                    "Protein Coord": format_coord(acceptor.coord),
                    "Extra": f"donortype={ligand.mol.GetAtomWithIdx(donor_idx).GetSymbol()}; acceptortype={acceptor.atom_type}",
                }
            )
            rows.append(row)

    rows.sort(key=lambda r: (r["Residue Number"], r["Primary Distance (Å)"], r["Protein Role"]))
    for idx, row in enumerate(rows, 1):
        row["PLIP Interaction ID"] = idx
    return rows


def salt_bridges(ligand: ReconstructedLigand, protein: ProteinModel) -> list[dict]:
    rows = []
    for ligand_center in ligand_charge_centers(ligand.mol):
        for protein_center in protein_charge_centers(protein):
            if ligand_center.positive == protein_center.positive:
                continue
            d = distance(ligand_center.coord, protein_center.coord)
            if d > SALTBRIDGE_DIST_MAX:
                continue
            representative = protein.by_serial[protein_center.atom_ids[0]]
            row = _base_row(ligand, "Salt bridge", representative)
            row.update(
                {
                    "Primary Distance (Å)": round(d, 4),
                    "Protein Role": "Positive" if protein_center.positive else "Negative",
                    "Ligand Atom Index Info": f"lig_group={ligand_center.label}",
                    "Protein Atom Index Info": f"protein_group={protein_center.label}",
                    "Ligand Coord": format_coord(ligand_center.coord),
                    "Protein Coord": format_coord(protein_center.coord),
                    "Extra": f"protispos={protein_center.positive}; lig_group={ligand_center.label}",
                }
            )
            rows.append(row)
    rows.sort(key=lambda r: (r["Residue Number"], r["Primary Distance (Å)"]))
    for idx, row in enumerate(rows, 1):
        row["PLIP Interaction ID"] = idx
    return rows


def pi_stacking(ligand: ReconstructedLigand, protein: ProteinModel) -> list[dict]:
    rows = []
    for ligand_ring in ligand_rings(ligand.mol):
        for protein_ring in protein_rings(protein):
            cent_dist = distance(ligand_ring.centroid, protein_ring.centroid)
            if cent_dist > PISTACK_DIST_MAX:
                continue
            angle = acute_angle_degrees(ligand_ring.normal, protein_ring.normal)
            p_offset = lateral_offset(protein_ring.centroid, ligand_ring.centroid, protein_ring.normal)
            l_offset = lateral_offset(ligand_ring.centroid, protein_ring.centroid, ligand_ring.normal)
            offset = min(p_offset, l_offset)
            parallel = angle <= PISTACK_ANG_DEV and offset <= PISTACK_OFFSET_MAX
            perpendicular = abs(90.0 - angle) <= PISTACK_ANG_DEV and offset <= PISTACK_OFFSET_MAX
            if not (parallel or perpendicular):
                continue
            representative = protein.by_serial[protein_ring.atom_ids[0]]
            row = _base_row(ligand, "π-stacking", representative)
            row.update(
                {
                    "Primary Distance (Å)": round(cent_dist, 4),
                    "Angle (°)": round(angle, 2),
                    "Ligand Atom Index Info": "ring_atoms=" + ",".join(map(str, ligand_ring.atom_ids)),
                    "Protein Atom Index Info": "ring_atoms=" + ",".join(map(str, protein_ring.atom_ids)),
                    "Ligand Coord": format_coord(ligand_ring.centroid),
                    "Protein Coord": format_coord(protein_ring.centroid),
                    "Extra": f"type={'P' if parallel else 'T'}; offset={offset:.2f}",
                }
            )
            rows.append(row)
    rows.sort(key=lambda r: (r["Residue Number"], r["Primary Distance (Å)"]))
    for idx, row in enumerate(rows, 1):
        row["PLIP Interaction ID"] = idx
    return rows


def pi_cation(ligand: ReconstructedLigand, protein: ProteinModel) -> list[dict]:
    rows = []
    # Ligand positive center to protein aromatic ring.
    for center in [c for c in ligand_charge_centers(ligand.mol) if c.positive]:
        for ring in protein_rings(protein):
            d = distance(center.coord, ring.centroid)
            offset = lateral_offset(ring.centroid, center.coord, ring.normal)
            if d <= PICATION_DIST_MAX and offset <= PICATION_OFFSET_MAX:
                representative = protein.by_serial[ring.atom_ids[0]]
                row = _base_row(ligand, "π-cation interaction", representative)
                row.update(
                    {
                        "Primary Distance (Å)": round(d, 4),
                        "Protein Role": "Aromatic",
                        "Ligand Atom Index Info": f"lig_group={center.label}",
                        "Protein Atom Index Info": "ring_atoms=" + ",".join(map(str, ring.atom_ids)),
                        "Ligand Coord": format_coord(center.coord),
                        "Protein Coord": format_coord(ring.centroid),
                        "Extra": f"protcharged=False; offset={offset:.2f}",
                    }
                )
                rows.append(row)

    # Ligand aromatic ring to protein positive center.
    for ring in ligand_rings(ligand.mol):
        for center in [c for c in protein_charge_centers(protein) if c.positive]:
            d = distance(ring.centroid, center.coord)
            offset = lateral_offset(ring.centroid, center.coord, ring.normal)
            if d <= PICATION_DIST_MAX and offset <= PICATION_OFFSET_MAX:
                representative = protein.by_serial[center.atom_ids[0]]
                row = _base_row(ligand, "π-cation interaction", representative)
                row.update(
                    {
                        "Primary Distance (Å)": round(d, 4),
                        "Protein Role": "Positive",
                        "Ligand Atom Index Info": "ring_atoms=" + ",".join(map(str, ring.atom_ids)),
                        "Protein Atom Index Info": f"protein_group={center.label}",
                        "Ligand Coord": format_coord(ring.centroid),
                        "Protein Coord": format_coord(center.coord),
                        "Extra": f"protcharged=True; offset={offset:.2f}",
                    }
                )
                rows.append(row)
    rows.sort(key=lambda r: (r["Residue Number"], r["Primary Distance (Å)"]))
    for idx, row in enumerate(rows, 1):
        row["PLIP Interaction ID"] = idx
    return rows


def halogen_bonds(ligand: ReconstructedLigand, protein: ProteinModel) -> list[dict]:
    rows = []
    halogens = [a for a in ligand.mol.GetAtoms() if a.GetAtomicNum() in {9, 17, 35, 53}]
    for halogen in halogens:
        carbon_neighbors = [n for n in halogen.GetNeighbors() if n.GetAtomicNum() == 6]
        if not carbon_neighbors:
            continue
        carbon = carbon_neighbors[0]
        x_coord = mol_coord(ligand.mol, halogen.GetIdx())
        c_coord = mol_coord(ligand.mol, carbon.GetIdx())
        for acceptor in protein_acceptors(protein):
            xa = distance(x_coord, acceptor.coord)
            if xa > HALOGEN_DIST_MAX:
                continue
            donor_angle = angle_degrees(c_coord, x_coord, acceptor.coord)
            base = protein_acceptor_base(protein, acceptor)
            if base is None:
                continue
            acceptor_angle = angle_degrees(base.coord, acceptor.coord, x_coord)
            if donor_angle < HALOGEN_DON_ANGLE_MIN:
                continue
            if not (HALOGEN_ACC_ANGLE_MIN <= acceptor_angle <= HALOGEN_ACC_ANGLE_MAX):
                continue
            row = _base_row(ligand, "Halogen bond", acceptor)
            row.update(
                {
                    "Primary Distance (Å)": round(xa, 4),
                    "Angle (°)": round(donor_angle, 2),
                    "Sidechain": str(residue_sidechain(acceptor)),
                    "Protein Role": "Acceptor",
                    "Ligand Atom Index Info": f"halogenidx={halogen.GetIdx()}; carbonidx={carbon.GetIdx()}",
                    "Protein Atom Index Info": f"acceptoridx={acceptor.serial}",
                    "Ligand Coord": format_coord(x_coord),
                    "Protein Coord": format_coord(acceptor.coord),
                    "Extra": f"acc_angle={acceptor_angle:.2f}; donor_angle={donor_angle:.2f}",
                }
            )
            rows.append(row)
    rows.sort(key=lambda r: (r["Residue Number"], r["Primary Distance (Å)"]))
    for idx, row in enumerate(rows, 1):
        row["PLIP Interaction ID"] = idx
    return rows


def binding_site_residue_rows(ligand: ReconstructedLigand, protein: ProteinModel, interactions: list[dict]) -> list[dict]:
    ligand_coords = np.asarray([mol_coord(ligand.mol, i) for i in range(ligand.mol.GetNumAtoms())])
    interaction_residues = {r["Residue"] for r in interactions}
    rows = []
    for (chain, resid, resname), atoms in sorted(protein.by_residue.items(), key=lambda x: (x[0][0], x[0][1])):
        heavy = np.asarray([a.coord for a in atoms if a.element != "H"])
        min_distance = float(
            np.sqrt(np.square(heavy[:, None, :] - ligand_coords[None, :, :]).sum(axis=2).min())
        )
        if min_distance > BINDING_SITE_CUTOFF:
            continue
        residue = f"{resname}{resid}"
        rows.append(
            {
                "Report XML": f"vina_interactions/vina_{ligand.molecule}/vina_{ligand.molecule}_report.xml",
                "Method": "Vina",
                "Ligand": f"vina_{ligand.molecule}",
                "Binding Site": 1,
                "Ligand ID": "LIG",
                "Ligand Chain": "L",
                "Ligand Position": 1,
                "Residue": residue,
                "Residue Name": resname,
                "Residue Number": resid,
                "Protein Chain": chain,
                "PLIP Contact": str(residue in interaction_residues),
                "Min Distance (Å)": round(min_distance, 4),
            }
        )
    return rows


def analyze_ligand(ligand: ReconstructedLigand, protein: ProteinModel) -> tuple[list[dict], list[dict]]:
    interactions = []
    interactions.extend(hydrophobic_interactions(ligand, protein))
    interactions.extend(hydrogen_bonds(ligand, protein))
    interactions.extend(salt_bridges(ligand, protein))
    interactions.extend(pi_stacking(ligand, protein))
    interactions.extend(pi_cation(ligand, protein))
    interactions.extend(halogen_bonds(ligand, protein))
    interactions.sort(
        key=lambda r: (
            INTERACTION_TYPES.index(r["Interaction Type"]),
            r["Residue Number"] or 0,
            r["Primary Distance (Å)"] or 0,
        )
    )
    binding = binding_site_residue_rows(ligand, protein, interactions)
    return interactions, binding


def evidence_flag(total: int, residues: int) -> str:
    if total >= 8 and residues >= 5:
        return "Strong interaction support"
    if total >= 5 and residues >= 4:
        return "Good interaction support"
    if total >= 3:
        return "Moderate interaction support"
    return "Limited interaction support"


def summarize(
    reconstructed: dict[str, ReconstructedLigand],
    all_interactions: list[dict],
    binding_rows: list[dict],
    top40_rows: list[dict[str, str]],
    mapping_validation: list[dict],
) -> dict:
    rank_map = {row["molecule"]: i + 1 for i, row in enumerate(top40_rows)}
    score_map = {row["molecule"]: float(row["best_affinity_kcal_mol"]) for row in top40_rows}

    by_type: dict[str, list[dict]] = defaultdict(list)
    by_ligand: dict[str, list[dict]] = defaultdict(list)
    by_residue_type: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in all_interactions:
        by_type[row["Interaction Type"]].append(row)
        by_ligand[row["Ligand"]].append(row)
        by_residue_type[(row["Residue"], row["Interaction Type"])].append(row)

    interaction_summary = []
    for interaction_type in INTERACTION_TYPES:
        rows = by_type.get(interaction_type, [])
        distances = [float(r["Primary Distance (Å)"]) for r in rows]
        interaction_summary.append(
            [
                interaction_type,
                len(rows),
                len({r["Ligand"] for r in rows}),
                len({r["Residue"] for r in rows}),
                min(distances) if distances else None,
                float(np.mean(distances)) if distances else None,
            ]
        )

    ligand_summary = []
    integrated = []
    report_summary = []
    for molecule in [r["molecule"] for r in top40_rows if r["molecule"] in reconstructed]:
        ligand_name = f"vina_{molecule}"
        rows = by_ligand.get(ligand_name, [])
        counts = Counter(r["Interaction Type"] for r in rows)
        residues = sorted({r["Residue"] for r in rows}, key=lambda x: int("".join(filter(str.isdigit, x))))
        ligand_summary.append(
            [
                ligand_name, "Vina", len(rows), len(residues),
                counts["Hydrophobic interaction"], counts["Hydrogen bond"],
                counts["Salt bridge"], counts["π-stacking"],
                counts["π-cation interaction"], counts["Halogen bond"],
            ]
        )
        evidence_counts = Counter((r["Residue"], r["Interaction Type"]) for r in rows)
        evidence = "; ".join(
            f"{residue} {itype}×{count}"
            for (residue, itype), count in evidence_counts.most_common(5)
        )
        best_distance = min((r["Primary Distance (Å)"] for r in rows), default=None)
        integrated.append(
            [
                ligand_name,
                molecule,
                rank_map[molecule],
                score_map[molecule],
                len(rows),
                len(residues),
                counts["Hydrophobic interaction"],
                counts["Hydrogen bond"],
                counts["Salt bridge"],
                counts["π-stacking"],
                counts["π-cation interaction"],
                counts["Halogen bond"],
                best_distance,
                ", ".join(residues),
                evidence,
                evidence_flag(len(rows), len(residues)),
            ]
        )
        report_summary.append(
            [
                f"vina_interactions/vina_{molecule}/vina_{molecule}_report.xml",
                "Vina",
                ligand_name,
                f"vina_{molecule}.pdb",
                f"VINA_{molecule.upper()}_PROTEIN",
                "PLIP-compatible RDKit/PDBQT rules",
                date.today().isoformat(),
                1,
                len(rows),
            ]
        )

    residue_summary = []
    for (residue, interaction_type), rows in by_residue_type.items():
        first = rows[0]
        distances = [float(r["Primary Distance (Å)"]) for r in rows]
        ligands = sorted({r["Ligand"] for r in rows})
        residue_summary.append(
            [
                first["Protein Chain"], residue, first["Residue Name"],
                first["Residue Number"], interaction_type, len(rows), len(ligands),
                ", ".join(ligands), min(distances), float(np.mean(distances)),
            ]
        )
    residue_summary.sort(key=lambda r: (-r[5], r[3], r[4]))

    contact_by_residue: dict[str, list[dict]] = defaultdict(list)
    for row in all_interactions:
        contact_by_residue[row["Residue"]].append(row)
    contact_summary = []
    for residue, rows in contact_by_residue.items():
        first = rows[0]
        ligands = sorted({r["Ligand"] for r in rows})
        # Use minimum distance per ligand before averaging.
        per_ligand = {}
        for row in rows:
            d = float(row["Primary Distance (Å)"])
            per_ligand[row["Ligand"]] = min(d, per_ligand.get(row["Ligand"], float("inf")))
        contact_summary.append(
            [
                first["Protein Chain"], residue, first["Residue Name"],
                first["Residue Number"], len(ligands), ", ".join(ligands),
                min(per_ligand.values()), float(np.mean(list(per_ligand.values()))),
            ]
        )
    contact_summary.sort(key=lambda r: (-r[4], r[3]))
    integrated.sort(key=lambda r: r[2])

    return {
        "interactions": all_interactions,
        "binding_site_residues": binding_rows,
        "interaction_summary": interaction_summary,
        "ligand_summary": ligand_summary,
        "residue_summary": residue_summary,
        "contact_summary": contact_summary,
        "integrated_summary": integrated,
        "report_summary": report_summary,
        "mapping_status": [
            [
                row.get("rank"), row.get("molecule"), row.get("mapping_status"),
                row.get("mapping_method"),
            ]
            for row in mapping_validation
        ],
    }


def analyze_all(
    reconstructed: dict[str, ReconstructedLigand],
    receptor_path: str | Path,
    top40_rows: list[dict[str, str]],
    mapping_validation: list[dict],
    output_json: str | Path | None = None,
) -> dict:
    protein = parse_receptor(receptor_path)
    all_interactions = []
    all_binding = []
    for row in top40_rows:
        ligand = reconstructed.get(row["molecule"])
        if ligand is None:
            continue
        interactions, binding = analyze_ligand(ligand, protein)
        all_interactions.extend(interactions)
        all_binding.extend(binding)
    result = summarize(
        reconstructed, all_interactions, all_binding, top40_rows, mapping_validation
    )
    if output_json is not None:
        Path(output_json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
