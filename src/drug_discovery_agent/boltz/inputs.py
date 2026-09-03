from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from drug_discovery_agent.receptor.mapping import ResidueMapping


def _template_document(
    template: str | Path,
    chain_id: str,
    *,
    force: bool | None = None,
    threshold: float | None = None,
) -> dict[str, object]:
    path = Path(template)
    suffix = path.suffix.lower()
    if suffix in {".cif", ".mmcif"}:
        key = "cif"
    elif suffix in {".pdb", ".ent"}:
        key = "pdb"
    else:
        raise ValueError(f"Boltz template must be PDB or CIF/mmCIF, got: {template}")
    result: dict[str, object] = {key: str(template), "chain_id": chain_id}
    if force is not None:
        result["force"] = force
    if threshold is not None:
        if threshold <= 0:
            raise ValueError("template threshold must be positive")
        result["threshold"] = threshold
    return result


def _base_input(
    *,
    protein_sequence: str,
    ligand_smiles: str,
    protein_id: str,
    ligand_id: str,
) -> dict[str, Any]:
    sequence = "".join(protein_sequence.split()).upper()
    smiles = ligand_smiles.strip()
    if not sequence or not smiles:
        raise ValueError("Boltz input requires non-empty protein sequence and ligand SMILES")
    return {
        "version": 1,
        "sequences": [
            {"protein": {"id": protein_id, "sequence": sequence}},
            {"ligand": {"id": ligand_id, "smiles": smiles}},
        ],
    }


def build_constrained_input(
    *,
    protein_sequence: str,
    ligand_smiles: str,
    receptor_template: str | Path,
    template_chain: str,
    mapped_pocket_residues: Iterable[ResidueMapping],
    protein_id: str = "A",
    ligand_id: str = "L",
    template_force: bool = True,
    template_threshold: float = 2.0,
    pocket_force: bool = True,
    pocket_max_distance: float = 6.0,
) -> dict[str, Any]:
    mappings = list(mapped_pocket_residues)
    if not mappings:
        raise ValueError("constrained Boltz input requires mapped pocket residues")
    positions = [(protein_id, mapping.boltz_sequence_position) for mapping in mappings]
    if len(set(positions)) != len(positions):
        raise ValueError("constrained pocket contains duplicate mapped positions")
    document = _base_input(
        protein_sequence=protein_sequence, ligand_smiles=ligand_smiles,
        protein_id=protein_id, ligand_id=ligand_id,
    )
    document["templates"] = [
        _template_document(receptor_template, template_chain, force=template_force,
                           threshold=template_threshold)
    ]
    document["properties"] = [{"affinity": {"binder": ligand_id}}]
    document["constraints"] = [{
        "pocket": {
            "binder": ligand_id,
            "contacts": [[chain, position] for chain, position in positions],
            "max_distance": pocket_max_distance,
            "force": pocket_force,
        }
    }]
    validate_constrained_input(document, expected_positions=positions, ligand_id=ligand_id)
    return document


def build_unconstrained_input(
    *,
    protein_sequence: str,
    ligand_smiles: str,
    receptor_template: str | Path | None = None,
    template_chain: str = "A",
    protein_id: str = "A",
    ligand_id: str = "L",
    template_force: bool | None = None,
    template_threshold: float | None = None,
) -> dict[str, Any]:
    document = _base_input(
        protein_sequence=protein_sequence, ligand_smiles=ligand_smiles,
        protein_id=protein_id, ligand_id=ligand_id,
    )
    if receptor_template is not None:
        document["templates"] = [
            _template_document(receptor_template, template_chain, force=template_force,
                               threshold=template_threshold)
        ]
    document["properties"] = [{"affinity": {"binder": ligand_id}}]
    validate_unconstrained_input(document, ligand_id=ligand_id)
    return document


def _affinity_binders(document: dict[str, Any]) -> list[str]:
    return [
        value["affinity"].get("binder")
        for value in document.get("properties", [])
        if isinstance(value, dict) and isinstance(value.get("affinity"), dict)
    ]


def validate_unconstrained_input(document: dict[str, Any], *, ligand_id: str = "L") -> None:
    if "constraints" in document:
        raise ValueError("unconstrained Boltz input must not contain a constraints key")
    serialized = yaml.safe_dump(document, sort_keys=False)
    if "pocket:" in serialized:
        raise ValueError("unconstrained Boltz input must not contain a pocket block")
    if ligand_id not in _affinity_binders(document):
        raise ValueError("unconstrained Boltz input is missing the ligand affinity property")
    sequences = document.get("sequences", [])
    if not any(isinstance(item, dict) and "protein" in item for item in sequences):
        raise ValueError("Boltz input is missing protein sequence")
    if not any(isinstance(item, dict) and "ligand" in item for item in sequences):
        raise ValueError("Boltz input is missing ligand")


def validate_constrained_input(
    document: dict[str, Any],
    *,
    expected_positions: Iterable[tuple[str, int]] | None = None,
    ligand_id: str = "L",
) -> None:
    constraints = document.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        raise ValueError("constrained Boltz input must contain constraints")
    pockets = [item["pocket"] for item in constraints if isinstance(item, dict) and isinstance(item.get("pocket"), dict)]
    if len(pockets) != 1:
        raise ValueError("constrained Boltz input must contain exactly one pocket constraint")
    pocket = pockets[0]
    if pocket.get("binder") != ligand_id or not pocket.get("force"):
        raise ValueError("constrained Boltz pocket must be forced for the configured ligand")
    contacts = [tuple(value) for value in pocket.get("contacts", [])]
    if not contacts:
        raise ValueError("constrained Boltz pocket must contain mapped contacts")
    if expected_positions is not None and contacts != list(expected_positions):
        raise ValueError(f"pocket contacts do not match the validated residue mapping: {contacts}")
    if ligand_id not in _affinity_binders(document):
        raise ValueError("constrained Boltz input is missing the ligand affinity property")
    templates = document.get("templates", [])
    if len(templates) != 1 or not templates[0].get("force"):
        raise ValueError("constrained Boltz input requires one forced receptor template")


def write_boltz_input(document: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")
    temporary.replace(target)


def load_boltz_input(path: str | Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"Boltz input must be a YAML mapping: {path}")
    return document

