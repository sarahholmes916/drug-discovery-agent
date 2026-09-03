from __future__ import annotations

from pathlib import Path

from drug_discovery_agent.receptor.conversion import validate_coordinates
from drug_discovery_agent.receptor.structure import StructureAtom, parse_structure

from .models import ResidueScore


def _line(atom: StructureAtom, probability: float) -> str:
    return (
        f"{atom.record:<6}{atom.serial:>5} {atom.atom_name:>4} {atom.residue_name:>3} "
        f"{atom.chain:1}{atom.residue_number:>4}{atom.insertion_code:1}   "
        f"{atom.x:>8.3f}{atom.y:>8.3f}{atom.z:>8.3f}{1.00:>6.2f}{probability:>6.2f}          "
        f"{atom.element.title():>2}  "
    )


def write_probability_pdb(receptor: str | Path, scores: list[ResidueScore], output: str | Path) -> None:
    """Write active PocketMiner scores (smoothed when enabled) into B-factor fields."""
    source, target = Path(receptor), Path(output)
    by_key = {item.residue.key: item.active_score for item in scores}
    atoms = parse_structure(source)
    lines = [
        "REMARK   Active PocketMiner scores are stored in the B-factor field on a 0..1 scale.",
        "REMARK   Coordinates are copied without transformation; this is not the prepared docking receptor.",
    ]
    for atom in atoms:
        key = (atom.chain, atom.residue_number, atom.insertion_code, atom.residue_name)
        lines.append(_line(atom, by_key.get(key, 0.0) if atom.record == "ATOM" else 0.0))
    lines.extend(["TER", "END"])
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="ascii")
    temporary.replace(target)
    validation = validate_coordinates(source, target, tolerance_angstrom=0.001)
    if not validation.coordinate_identity_verified:
        target.unlink(missing_ok=True)
        raise ValueError(validation.error or "colored PocketMiner receptor changed coordinates")
