from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from drug_discovery_agent.config.models import LigandSourceConfig
from drug_discovery_agent.project.hashing import sha256_file
from drug_discovery_agent.project.manifest import LigandRecord


def _rdkit() -> object:
    try:
        from rdkit import Chem
    except ImportError as exc:
        raise RuntimeError("RDKit is required for SDF ligand ingestion") from exc
    return Chem


def sanitize_name(name: str | None, *, empty: str = "unnamed") -> str:
    value = (name or "").strip()
    if not value:
        return empty
    return re.sub(r"[^\w.\-]+", "_", value)[:120]


def _canonical_id(source_file_id: str, record_index: int, molblock: str | None) -> str:
    digest = hashlib.sha256()
    digest.update(source_file_id.encode("ascii"))
    digest.update(b"\0")
    digest.update(str(record_index).encode("ascii"))
    digest.update(b"\0")
    if molblock:
        digest.update(molblock.encode("utf-8", errors="replace"))
    return f"lig_{digest.hexdigest()[:20]}"


@dataclass(slots=True)
class LigandIngestResult:
    records: list[LigandRecord]
    output_files: dict[str, Path]

    @property
    def failed(self) -> list[LigandRecord]:
        return [record for record in self.records if record.status == "FAILED"]


def _source_files(source: LigandSourceConfig, resolved_path: Path) -> list[Path]:
    if source.kind == "multi_sdf":
        if not resolved_path.is_file():
            raise FileNotFoundError(resolved_path)
        return [resolved_path]
    if not resolved_path.is_dir():
        raise NotADirectoryError(resolved_path)
    files = sorted(path for path in resolved_path.iterdir() if path.is_file() and path.suffix.lower() == ".sdf")
    if not files:
        raise FileNotFoundError(f"no .sdf files found in {resolved_path}")
    return files


def ingest_ligands(
    sources: Iterable[tuple[LigandSourceConfig, str | Path]],
    output_directory: str | Path,
) -> LigandIngestResult:
    """Ingest SDF sources while preserving legacy names and all failed records."""
    Chem = _rdkit()
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    records: list[LigandRecord] = []
    output_files: dict[str, Path] = {}
    used_names: set[str] = set()

    for source_config, resolved in sources:
        for source_file in _source_files(source_config, Path(resolved).expanduser().resolve()):
            source_file_id = f"source_{sha256_file(source_file)[:20]}"
            supplier = Chem.SDMolSupplier(str(source_file), removeHs=False)
            if supplier is None:
                raise ValueError(f"RDKit could not open {source_file}")
            for record_index, molecule in enumerate(supplier, start=1):
                raw_name = None
                if molecule is not None and molecule.HasProp("_Name"):
                    raw_name = molecule.GetProp("_Name")
                # Preserve the historical split_sdf.py fallback exactly.  The
                # source file was named structures.sdf in that workflow, so
                # blank titles became structures_<1-based-record-index>.
                fallback = f"structures_{record_index}"
                base_name = sanitize_name(raw_name, empty=fallback) if raw_name else fallback
                legacy_name = base_name
                duplicate = 2
                while legacy_name in used_names:
                    legacy_name = f"{base_name}_{duplicate}"
                    duplicate += 1
                used_names.add(legacy_name)

                molblock = Chem.MolToMolBlock(molecule) if molecule is not None else None
                ligand_id = _canonical_id(source_file_id, record_index, molblock)
                if molecule is None:
                    records.append(
                        LigandRecord(
                            ligand_id=ligand_id,
                            original_name=raw_name or None,
                            legacy_name=legacy_name,
                            source_file_id=source_file_id,
                            source_record_index=record_index,
                            status="FAILED",
                            error=f"RDKit could not read record {record_index}",
                        )
                    )
                    continue

                target = output / f"{legacy_name}.sdf"
                writer = Chem.SDWriter(str(target))
                try:
                    writer.write(molecule)
                finally:
                    writer.close()
                canonical_smiles = Chem.MolToSmiles(molecule, isomericSmiles=True)
                records.append(
                    LigandRecord(
                        ligand_id=ligand_id,
                        original_name=raw_name or None,
                        legacy_name=legacy_name,
                        source_file_id=source_file_id,
                        source_record_index=record_index,
                        canonical_smiles=canonical_smiles,
                        status="SUCCESS",
                    )
                )
                output_files[ligand_id] = target
    return LigandIngestResult(records=records, output_files=output_files)
