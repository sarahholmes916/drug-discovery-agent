#!/usr/bin/env python3
"""Generate Boltz-2 protein/ligand YAML inputs with NO binding-site constraint.

This is a portable reconstruction based on the user's earlier unconstrained
Boltz-2 input archive. It intentionally omits the ``constraints``/``pocket``
section. A receptor template may still be supplied; the ligand is not told
where on that receptor to bind.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import yaml


def sanitize_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "unnamed"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:120]


def make_input(
    protein_sequence: str,
    ligand_smiles: str,
    template: Path | None,
    template_chain: str,
    protein_id: str = "A",
    ligand_id: str = "L",
) -> dict:
    doc: dict = {
        "version": 1,
        "sequences": [
            {"protein": {"id": protein_id, "sequence": protein_sequence}},
            {"ligand": {"id": ligand_id, "smiles": ligand_smiles}},
        ],
    }

    if template is not None:
        suffix = template.suffix.lower()
        if suffix in {".cif", ".mmcif"}:
            template_key = "cif"
        elif suffix in {".pdb", ".ent"}:
            template_key = "pdb"
        else:
            raise ValueError(
                f"Template must be PDB or CIF/mmCIF, got: {template}"
            )
        doc["templates"] = [
            {
                template_key: str(template),
                "chain_id": template_chain,
            }
        ]

    doc["properties"] = [{"affinity": {"binder": ligand_id}}]

    # IMPORTANT: no `constraints` key is created here. This is the defining
    # difference from the Vina-site-constrained Boltz mode.
    return doc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ligands-csv",
        required=True,
        type=Path,
        help="CSV containing ligand_name and smiles columns.",
    )
    parser.add_argument("--protein-sequence", required=True)
    parser.add_argument("--template", type=Path, default=None)
    parser.add_argument("--template-chain", default="A")
    parser.add_argument("--protein-id", default="A")
    parser.add_argument("--ligand-id", default="L")
    parser.add_argument("--prefix", default="")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    with args.ligands_csv.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"ligand_name", "smiles"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Missing CSV columns: {', '.join(sorted(missing))}"
            )

        count = 0
        for row in reader:
            ligand_name = sanitize_name(row["ligand_name"])
            smiles = (row["smiles"] or "").strip()
            if not smiles:
                raise ValueError(f"Empty SMILES for ligand {ligand_name}")

            doc = make_input(
                protein_sequence=args.protein_sequence,
                ligand_smiles=smiles,
                template=args.template,
                template_chain=args.template_chain,
                protein_id=args.protein_id,
                ligand_id=args.ligand_id,
            )
            output = args.out_dir / f"{args.prefix}{ligand_name}.yaml"
            with output.open("w", encoding="utf-8") as out:
                yaml.safe_dump(doc, out, sort_keys=False)
            count += 1

    print(f"Wrote {count} unconstrained Boltz-2 YAML file(s) to {args.out_dir}")


if __name__ == "__main__":
    main()
