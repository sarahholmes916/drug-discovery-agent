from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from drug_discovery_agent.project.hashing import sha256_file

from .structure import StructureAtom, parse_pdb_like, parse_structure


@dataclass(frozen=True, slots=True)
class CoordinateValidation:
    source_sha256: str
    output_sha256: str
    atom_count: int
    coordinate_max_abs_delta_angstrom: float
    coordinate_identity_verified: bool
    error: str | None = None


def _pdb_line(atom: StructureAtom) -> str:
    element = atom.element.title().rjust(2)
    return (
        f"{atom.record:<6}{atom.serial:>5} {atom.atom_name:>4} {atom.residue_name:>3} "
        f"{atom.chain:1}{atom.residue_number:>4}{atom.insertion_code:1}   "
        f"{atom.x:>8.3f}{atom.y:>8.3f}{atom.z:>8.3f}{1.00:>6.2f}{0.00:>6.2f}          {element}  "
    )


def convert_pdbqt_to_pdb(source_pdbqt: str | Path, output_pdb: str | Path) -> CoordinateValidation:
    source = Path(source_pdbqt)
    target = Path(output_pdb)
    atoms = parse_pdb_like(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "REMARK   Converted from PDBQT without coordinate transformation.",
        "REMARK   PDBQT partial charges and AutoDock atom types are omitted because PDB has no equivalent fields.",
        *(_pdb_line(atom) for atom in atoms),
        "TER",
        "END",
    ]
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="ascii")
    temporary.replace(target)
    return validate_coordinates(source, target, tolerance_angstrom=0.0)


def convert_pdb_template_to_mmcif(
    source_pdb: str | Path,
    output_mmcif: str | Path,
    *,
    protein_sequence: str | None = None,
    protein_chain: str | None = None,
) -> CoordinateValidation:
    """Write Boltz's PDB-to-mmCIF normalization without its locked Windows temp file.

    Boltz 2.2.1 opens a ``NamedTemporaryFile`` and then asks Gemmi to reopen that
    same path. Windows denies the second writer. Performing the identical Gemmi
    normalization before invoking Boltz lets Boltz read mmCIF directly and does
    not alter coordinates or scientific settings.
    """
    try:
        import gemmi
    except ImportError as exc:  # pragma: no cover - companion scientific build includes Gemmi
        raise RuntimeError("Gemmi is required to prepare a Windows-safe Boltz template") from exc

    source = Path(source_pdb).resolve()
    target = Path(output_mmcif).resolve()
    if source.suffix.lower() not in {".pdb", ".ent"}:
        raise ValueError(f"Boltz template conversion requires PDB input, got: {source}")
    if target.suffix.lower() not in {".cif", ".mmcif"}:
        raise ValueError(f"Boltz template conversion requires mmCIF output, got: {target}")

    structure = gemmi.read_structure(str(source))
    if len(structure) == 0:
        raise ValueError(f"Boltz receptor template has no coordinate model: {source}")
    structure.setup_entities()

    target_subchains: set[str] = set()
    if protein_chain:
        target_subchains = {
            residue.subchain
            for chain in structure[0]
            if chain.name == protein_chain
            for residue in chain
        }
        if not target_subchains:
            raise ValueError(f"protein chain {protein_chain!r} is absent from Boltz template")

    # Coordinate-only PDB files (including PDBs converted from prepared
    # PDBQT) have no SEQRES records. Gemmi therefore creates polymer entities
    # with an empty full_sequence, which Boltz's mmCIF parser cannot index. Fill
    # that metadata from the user-validated sequence for the target chain, or
    # from the modeled residue names when no separate sequence was supplied.
    for entity in structure.entities:
        entity_subchains = set(entity.subchains)
        observed = [
            residue.name
            for chain in structure[0]
            for residue in chain
            if residue.subchain in entity_subchains
        ]
        if not observed:
            continue
        if protein_sequence and target_subchains.intersection(entity_subchains):
            sequence = "".join(protein_sequence.split()).upper()
            if not sequence:
                raise ValueError("Boltz protein sequence cannot be empty")
            entity.full_sequence = gemmi.expand_one_letter_sequence(
                sequence, gemmi.ResidueKind.AA
            )
        elif not entity.full_sequence:
            entity.full_sequence = observed

    # This mirrors Boltz 2.2.1's parse_pdb normalization exactly. In
    # particular, it preserves the subchain/entity labels that its mmCIF parser
    # expects after converting a PDB template.
    subchain_counts: dict[str, int] = {}
    subchain_renaming: dict[str, str] = {}
    for chain in structure[0]:
        subchain_counts[chain.name] = 0
        for residue in chain:
            if residue.subchain not in subchain_renaming:
                subchain_counts[chain.name] += 1
                subchain_renaming[residue.subchain] = (
                    chain.name + str(subchain_counts[chain.name])
                )
            residue.subchain = subchain_renaming[residue.subchain]
    for entity in structure.entities:
        entity.subchains = [subchain_renaming[value] for value in entity.subchains]

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        structure.make_mmcif_document().write_file(str(temporary))
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("Gemmi did not write the Boltz mmCIF template")
        # Keep the output mtime stable when resuming an unchanged project so
        # item fingerprints remain reusable.
        if target.is_file() and target.read_bytes() == temporary.read_bytes():
            temporary.unlink()
        else:
            os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)

    validation = validate_coordinates(source, target, tolerance_angstrom=0.0)
    if not validation.coordinate_identity_verified:
        raise ValueError(
            validation.error or "PDB-to-mmCIF conversion changed receptor coordinates"
        )
    return validation


def validate_coordinates(
    source_path: str | Path,
    output_path: str | Path,
    *,
    tolerance_angstrom: float = 0.001,
) -> CoordinateValidation:
    source_path, output_path = Path(source_path), Path(output_path)
    source, output = parse_structure(source_path), parse_structure(output_path)
    error = None
    maximum = float("inf")
    if len(source) != len(output):
        error = f"atom-count mismatch: source={len(source)} output={len(output)}"
    else:
        mismatches = [
            (first.identity, second.identity) for first, second in zip(source, output, strict=True)
            if first.identity != second.identity
        ]
        if mismatches:
            error = f"atom identity/order mismatch at {len(mismatches)} positions; first={mismatches[0]}"
        else:
            maximum = max(
                abs(first_value - second_value)
                for first, second in zip(source, output, strict=True)
                for first_value, second_value in zip(
                    (first.x, first.y, first.z), (second.x, second.y, second.z), strict=True
                )
            )
            if maximum > tolerance_angstrom:
                error = f"maximum coordinate delta {maximum:.6f} A exceeds {tolerance_angstrom:.6f} A"
    return CoordinateValidation(
        source_sha256=sha256_file(source_path), output_sha256=sha256_file(output_path),
        atom_count=len(source), coordinate_max_abs_delta_angstrom=maximum,
        coordinate_identity_verified=error is None, error=error,
    )


def require_coordinate_identity(validation: CoordinateValidation) -> None:
    if not validation.coordinate_identity_verified:
        raise ValueError(validation.error or "receptor coordinate identity validation failed")
