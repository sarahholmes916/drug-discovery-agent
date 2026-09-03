from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from drug_discovery_agent.config.models import PocketResidue

from .structure import parse_structure


THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M",
}


@dataclass(frozen=True, slots=True)
class ResidueMapping:
    pdb_chain: str
    pdb_residue_number: int
    insertion_code: str
    residue_name: str
    receptor_sequence_ordinal: int
    boltz_sequence_position: int
    one_letter: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExtractedProteinSequence:
    chain: str
    sequence: str
    source: str
    residue_count: int
    available_chains: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def receptor_residues(
    path: str | Path,
    *,
    chain: str | None = None,
) -> list[tuple[str, int, str, str]]:
    seen: set[tuple[str, int, str, str]] = set()
    result = []
    for atom in parse_structure(path):
        key = (atom.chain, atom.residue_number, atom.insertion_code, atom.residue_name)
        if atom.record == "ATOM" and (chain is None or atom.chain == chain) and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def extract_protein_sequence(
    receptor_path: str | Path,
    protein_chain: str,
) -> ExtractedProteinSequence:
    """Reconstruct one selected chain from the receptor's modeled ATOM residues.

    Coordinate records are used deliberately: they are the residue identities
    that downstream pocket mapping can validate against the receptor template.
    The returned value remains user-editable because unresolved residues are not
    represented by ATOM records in many experimental structures.
    """
    all_residues = receptor_residues(receptor_path)
    available_chains = tuple(dict.fromkeys(item[0] for item in all_residues))
    chain = protein_chain.strip()
    residues = [item for item in all_residues if item[0] == chain]
    if not residues:
        displayed = ", ".join(value or "(blank)" for value in available_chains) or "none"
        raise ValueError(
            f"protein chain {chain!r} was not found in receptor ATOM records; "
            f"available chains: {displayed}"
        )
    try:
        sequence = "".join(THREE_TO_ONE[name] for _, _, _, name in residues)
    except KeyError as exc:
        raise ValueError(
            f"unsupported receptor residue for sequence extraction in chain {chain!r}: {exc.args[0]}"
        ) from exc
    return ExtractedProteinSequence(
        chain=chain,
        sequence=sequence,
        source="coordinate_records",
        residue_count=len(residues),
        available_chains=available_chains,
    )


def map_pocket_residues(
    receptor_path: str | Path,
    protein_sequence: str,
    selected: Iterable[PocketResidue],
    *,
    protein_chain: str | None = None,
) -> list[ResidueMapping]:
    residues = receptor_residues(receptor_path, chain=protein_chain)
    try:
        receptor_sequence = "".join(THREE_TO_ONE[name] for _, _, _, name in residues)
    except KeyError as exc:
        raise ValueError(f"unsupported receptor residue for sequence mapping: {exc.args[0]}") from exc
    sequence = "".join(protein_sequence.split()).upper()
    starts = []
    start = sequence.find(receptor_sequence)
    while start >= 0:
        starts.append(start)
        start = sequence.find(receptor_sequence, start + 1)
    if len(starts) != 1:
        raise ValueError(
            f"receptor sequence mapping is {'missing' if not starts else 'ambiguous'}; exact matches={len(starts)}"
        )
    offset = starts[0]
    by_key = {(chain, number, insertion): (ordinal, name) for ordinal, (chain, number, insertion, name)
              in enumerate(residues, start=1)}
    mappings = []
    used_positions: set[int] = set()
    for requested in selected:
        key = (requested.chain, requested.residue_number, requested.insertion_code)
        if key not in by_key:
            raise ValueError(f"selected pocket residue not present in receptor: {key}")
        ordinal, actual_name = by_key[key]
        if actual_name != requested.residue_name.upper():
            raise ValueError(
                f"residue identity mismatch for {key}: configured={requested.residue_name} receptor={actual_name}"
            )
        position = offset + ordinal
        if requested.sequence_position is not None and requested.sequence_position != position:
            raise ValueError(
                f"configured sequence position {requested.sequence_position} conflicts with mapped {position} for {key}"
            )
        if position in used_positions:
            raise ValueError(f"multiple pocket residues map to sequence position {position}")
        used_positions.add(position)
        mappings.append(
            ResidueMapping(requested.chain, requested.residue_number, requested.insertion_code,
                           actual_name, ordinal, position, THREE_TO_ONE[actual_name])
        )
    if not mappings:
        raise ValueError("constrained Boltz requires at least one mapped pocket residue")
    return mappings
