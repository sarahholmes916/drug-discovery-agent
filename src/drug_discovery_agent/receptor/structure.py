from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex


@dataclass(frozen=True, slots=True)
class StructureAtom:
    record: str
    serial: int
    atom_name: str
    residue_name: str
    chain: str
    residue_number: int
    insertion_code: str
    x: float
    y: float
    z: float
    element: str
    alternate_location: str = ""
    occupancy: float = 1.0

    @property
    def identity(self) -> tuple[int, str, str, int, str, str]:
        return (
            self.serial, self.atom_name, self.chain, self.residue_number,
            self.insertion_code, self.residue_name,
        )


def parse_pdb_like(path: str | Path) -> list[StructureAtom]:
    atoms = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        parts = line.split()
        atom_name = line[12:16].strip()
        element = line[76:78].strip() if len(line) >= 78 else ""
        if not element:
            atom_type = parts[-1] if Path(path).suffix.lower() == ".pdbqt" else atom_name
            element = "".join(character for character in atom_type if character.isalpha())[:2].upper()
        atoms.append(
            StructureAtom(
                record=line[:6].strip(), serial=int(line[6:11]), atom_name=atom_name,
                residue_name=line[17:20].strip(), chain=line[21:22].strip(),
                residue_number=int(line[22:26]), insertion_code=line[26:27].strip(),
                x=float(line[30:38]), y=float(line[38:46]), z=float(line[46:54]),
                element=element.upper(),
                alternate_location=line[16:17].strip(),
                occupancy=float(line[54:60]) if len(line) >= 60 and line[54:60].strip() else 1.0,
            )
        )
    if not atoms:
        raise ValueError(f"no PDB/PDBQT atom records found in {path}")
    return atoms


def parse_mmcif(path: str | Path) -> list[StructureAtom]:
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    atoms: list[StructureAtom] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != "loop_":
            index += 1
            continue
        index += 1
        headers = []
        while index < len(lines) and lines[index].strip().startswith("_atom_site."):
            headers.append(lines[index].strip().removeprefix("_atom_site."))
            index += 1
        if not headers:
            continue
        positions = {name: position for position, name in enumerate(headers)}

        def value(tokens: list[str], *names: str, default: str = "") -> str:
            for name in names:
                if name in positions:
                    raw = tokens[positions[name]]
                    return default if raw in {".", "?"} else raw
            return default

        while index < len(lines):
            raw = lines[index].strip()
            if not raw or raw.startswith("#") or raw == "loop_" or raw.startswith("_"):
                break
            tokens = shlex.split(raw)
            if len(tokens) < len(headers):
                raise ValueError(f"multiline or malformed atom_site row is unsupported in {path}: {raw[:80]}")
            record = value(tokens, "group_PDB")
            if record in {"ATOM", "HETATM"}:
                atoms.append(
                    StructureAtom(
                        record=record,
                        serial=int(value(tokens, "id")),
                        atom_name=value(tokens, "auth_atom_id", "label_atom_id"),
                        residue_name=value(tokens, "auth_comp_id", "label_comp_id"),
                        chain=value(tokens, "auth_asym_id", "label_asym_id"),
                        residue_number=int(value(tokens, "auth_seq_id", "label_seq_id")),
                        insertion_code=value(tokens, "pdbx_PDB_ins_code"),
                        x=float(value(tokens, "Cartn_x")),
                        y=float(value(tokens, "Cartn_y")),
                        z=float(value(tokens, "Cartn_z")),
                        element=value(tokens, "type_symbol").upper(),
                        alternate_location=value(tokens, "label_alt_id", "auth_alt_id"),
                        occupancy=float(value(tokens, "occupancy", default="1.0")),
                    )
                )
            index += 1
    if not atoms:
        raise ValueError(f"no mmCIF atom_site records found in {path}")
    return atoms


def parse_structure(path: str | Path) -> list[StructureAtom]:
    suffix = Path(path).suffix.lower()
    return parse_mmcif(path) if suffix in {".cif", ".mmcif"} else parse_pdb_like(path)
