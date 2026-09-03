from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class PDBQTAtom:
    serial: int
    atom_name: str
    resname: str
    chain: str
    resid: int
    coord: tuple[float, float, float]
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
        return {atom.serial: atom for atom in self.atoms}

    @property
    def heavy_atoms(self) -> list[PDBQTAtom]:
        return [atom for atom in self.atoms if atom.element != "H"]


def normalize_element(atom_name: str, atom_type: str) -> str:
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
    parts = line.split()
    charge = None
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
        coord=(float(line[30:38]), float(line[38:46]), float(line[46:54])),
        charge=charge,
        atom_type=atom_type,
        element=normalize_element(line[12:16], atom_type),
        record=line[0:6].strip(),
    )


def _remark_pairs(line: str, prefix: str) -> list[tuple[int, int]]:
    values = [int(value) for value in line.strip().split(prefix, 1)[1].split()]
    if len(values) % 2:
        raise ValueError(f"odd number of values in {prefix!r}: {line.strip()}")
    return list(zip(values[0::2], values[1::2]))


def parse_vina_poses(path: str | Path, molecule: str | None = None) -> list[VinaPose]:
    source = Path(path)
    molecule = molecule or source.name.removesuffix("_out.pdbqt")
    poses: list[VinaPose] = []
    mode = None
    affinity = rmsd_lb = rmsd_ub = None
    atoms: list[PDBQTAtom] = []
    smiles = None
    smiles_to_pdbqt: dict[int, int] = {}
    h_parent: dict[int, list[int]] = {}

    def finish() -> None:
        nonlocal mode, affinity, rmsd_lb, rmsd_ub, atoms, smiles, smiles_to_pdbqt, h_parent
        if mode is None:
            return
        poses.append(
            VinaPose(molecule, mode, affinity, rmsd_lb, rmsd_ub, atoms, smiles, smiles_to_pdbqt, h_parent, source)
        )
        mode = None
        affinity = rmsd_lb = rmsd_ub = None
        atoms = []
        smiles = None
        smiles_to_pdbqt = {}
        h_parent = {}

    for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("MODEL"):
            finish()
            mode = int(line.split()[1])
        elif line.startswith("ENDMDL"):
            finish()
        elif mode is not None and line.startswith("REMARK VINA RESULT:"):
            affinity, rmsd_lb, rmsd_ub = map(float, line.split("RESULT:", 1)[1].split()[:3])
        elif mode is not None and line.startswith("REMARK SMILES IDX"):
            for smiles_index, serial in _remark_pairs(line, "REMARK SMILES IDX"):
                smiles_to_pdbqt[smiles_index] = serial
        elif mode is not None and line.startswith("REMARK H PARENT"):
            for parent, hydrogen in _remark_pairs(line, "REMARK H PARENT"):
                h_parent.setdefault(parent, []).append(hydrogen)
        elif mode is not None and line.startswith("REMARK SMILES "):
            smiles = line.split("REMARK SMILES ", 1)[1].strip()
        elif mode is not None and line.startswith(("ATOM", "HETATM")):
            atoms.append(parse_pdbqt_atom(line))
    finish()
    return poses


def mode1_pose(path: str | Path, molecule: str | None = None) -> VinaPose:
    for pose in parse_vina_poses(path, molecule):
        if pose.mode == 1:
            return pose
    raise ValueError(f"no mode 1 found in {path}")

