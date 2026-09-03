from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from uuid import uuid4

from drug_discovery_agent.config.models import ProjectConfig, ReceptorPreparationConfig
from drug_discovery_agent.execution.commands import CommandExecutor
from drug_discovery_agent.project.layout import ProjectLayout, create_project
from drug_discovery_agent.receptor.mapping import ExtractedProteinSequence, extract_protein_sequence
from drug_discovery_agent.receptor.preparation import prepare_receptor_pdbqt

from .registry import RunnerRegistry


class BrowserUpload(Protocol):
    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True)
class ProjectUploadOptions:
    project_id: str
    display_name: str
    pocketminer: bool
    boltz_constrained: bool
    boltz_unconstrained: bool
    downstream_ligand_count: int = 50
    downstream_selection_metric: str = "best_affinity"
    protein_sequence: str | None = None
    protein_chain: str = "A"
    receptor_preparation: str = "provided_pdbqt"
    remove_waters: bool = True
    heterogens: str = "review"
    alternate_locations: str = "review"
    preparation_instructions: str | None = None
    agent_notes: str | None = None


_STRUCTURE_EXTENSIONS = {".pdb", ".ent", ".cif", ".mmcif"}
_RECEPTOR_LIMIT = 100 * 1024 * 1024
MAX_LIGAND_FILES = 5000
_LIGAND_FILE_LIMIT = 512 * 1024 * 1024
_LIGAND_TOTAL_LIMIT = 2 * 1024 * 1024 * 1024


def _extension(upload: BrowserUpload, allowed: set[str], label: str) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{label} must use one of these extensions: {choices}")
    return suffix


async def _save_upload(upload: BrowserUpload, target: Path, limit: int) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with target.open("xb") as destination:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > limit:
                raise ValueError(f"uploaded file exceeds the {limit // (1024 * 1024)} MB limit")
            destination.write(chunk)
    if written == 0:
        raise ValueError("uploaded files cannot be empty")
    return written


async def _read_upload(upload: BrowserUpload, limit: int) -> bytes:
    content = bytearray()
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > limit:
            raise ValueError(f"uploaded file exceeds the {limit // (1024 * 1024)} MB limit")
    if not content:
        raise ValueError("uploaded files cannot be empty")
    return bytes(content)


def _write_bytes(content: bytes, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as destination:
        destination.write(content)
    return len(content)


def _extract_uploaded_sequence(
    filename: str,
    content: bytes,
    protein_chain: str,
) -> ExtractedProteinSequence:
    suffix = Path(filename).suffix.lower()
    with TemporaryDirectory(prefix="drug-agent-receptor-") as directory:
        receptor = Path(directory) / f"receptor{suffix}"
        receptor.write_bytes(content)
        return extract_protein_sequence(receptor, protein_chain)


async def inspect_receptor_upload(
    upload: BrowserUpload,
    protein_chain: str,
) -> ExtractedProteinSequence:
    """Inspect a browser upload without retaining the molecular file."""
    _extension(upload, _STRUCTURE_EXTENSIONS, "receptor structure")
    content = await _read_upload(upload, _RECEPTOR_LIMIT)
    return _extract_uploaded_sequence(upload.filename or "receptor.pdb", content, protein_chain)


def _workflow(constrained: bool, unconstrained: bool) -> str:
    if constrained and unconstrained:
        return "vina_to_both_boltz"
    if constrained:
        return "vina_to_constrained_boltz"
    if unconstrained:
        return "vina_to_unconstrained_boltz"
    return "vina_only"


async def create_project_from_uploads(
    *,
    options: ProjectUploadOptions,
    receptor_structure: BrowserUpload,
    receptor_pdbqt: BrowserUpload | None,
    ligand_files: list[BrowserUpload],
    projects_root: str | Path,
    registry: RunnerRegistry,
) -> tuple[ProjectLayout, ProjectConfig, int]:
    structure_suffix = _extension(
        receptor_structure, _STRUCTURE_EXTENSIONS, "receptor structure",
    )
    preparation = ReceptorPreparationConfig.model_validate({
        "method": options.receptor_preparation,
        "remove_waters": options.remove_waters,
        "heterogens": options.heterogens,
        "alternate_locations": options.alternate_locations,
        "custom_instructions": (options.preparation_instructions or "").strip() or None,
    })
    if preparation.method == "provided_pdbqt":
        if receptor_pdbqt is None:
            raise ValueError("upload a prepared receptor PDBQT or choose automatic Meeko preparation")
        _extension(receptor_pdbqt, {".pdbqt"}, "prepared Vina receptor")
    if not ligand_files:
        raise ValueError("at least one ligand SDF is required")
    if len(ligand_files) > MAX_LIGAND_FILES:
        raise ValueError(f"no more than {MAX_LIGAND_FILES:,} ligand SDF files are allowed")
    for ligand in ligand_files:
        _extension(ligand, {".sdf"}, "ligand file")

    sequence = "".join((options.protein_sequence or "").split()).upper() or None
    protein_chain = options.protein_chain.strip() or "A"
    boltz_enabled = options.boltz_constrained or options.boltz_unconstrained
    prefetched_structure: bytes | None = None
    if boltz_enabled and not sequence:
        prefetched_structure = await _read_upload(receptor_structure, _RECEPTOR_LIMIT)
        try:
            extracted = _extract_uploaded_sequence(
                receptor_structure.filename or f"receptor{structure_suffix}",
                prefetched_structure,
                protein_chain,
            )
        except ValueError as exc:
            raise ValueError(
                "could not extract a protein sequence from the selected receptor chain; "
                f"choose the correct chain or enter the sequence manually: {exc}"
            ) from exc
        sequence = extracted.sequence
        protein_chain = extracted.chain

    config = ProjectConfig.model_validate({
        "project": {
            "id": options.project_id,
            "display_name": options.display_name,
            "guidance_notes": [options.agent_notes.strip()] if options.agent_notes and options.agent_notes.strip() else [],
        },
        "workflow": _workflow(options.boltz_constrained, options.boltz_unconstrained),
        "target": {
            "receptor_ref": "receptor_structure",
            "receptor_pdbqt_ref": "receptor_vina",
            "receptor_template_ref": (
                "receptor_structure"
                if boltz_enabled and preparation.method == "provided_pdbqt"
                else None
            ),
            "protein_sequence": sequence,
            "protein_chain": protein_chain,
            "preparation": preparation.model_dump(mode="json"),
        },
        "pocket": {"mode": "pocketminer" if options.pocketminer else "manual"},
        "ligands": [{
            "source_ref": "ligand_set_01",
            "kind": "multi_sdf" if len(ligand_files) == 1 else "sdf_directory",
        }],
        "vina": {"enabled": True},
        "boltz": {
            "constrained": {"enabled": options.boltz_constrained},
            "unconstrained": {"enabled": options.boltz_unconstrained},
        },
        "analysis": {
            "vina_shortlist": options.downstream_ligand_count,
            "vina_selection_metric": options.downstream_selection_metric,
        },
    })

    root = Path(projects_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    final_root = root / config.project.id
    if final_root.exists():
        raise FileExistsError(f"project already exists: {config.project.id}")
    incoming_parent = root / f".incoming_{uuid4().hex}"
    staged_root = incoming_parent / config.project.id
    final_structure = final_root / "inputs" / "receptor" / f"receptor{structure_suffix}"
    final_pdbqt = final_root / "inputs" / "receptor" / "receptor.pdbqt"
    final_ligand_directory = final_root / "inputs" / "ligands"
    final_ligands = [
        final_ligand_directory / f"ligand_source_{index:04d}.sdf"
        for index in range(1, len(ligand_files) + 1)
    ]
    references = {
        "receptor_structure": final_structure,
        "receptor_vina": final_pdbqt,
        "ligand_set_01": final_ligands[0] if len(final_ligands) == 1 else final_ligand_directory,
    }

    try:
        layout = create_project(incoming_parent, config, references)
        staged_structure = layout.root / final_structure.relative_to(final_root)
        staged_pdbqt = layout.root / final_pdbqt.relative_to(final_root)
        total_bytes = (
            _write_bytes(prefetched_structure, staged_structure)
            if prefetched_structure is not None
            else await _save_upload(receptor_structure, staged_structure, _RECEPTOR_LIMIT)
        )
        if preparation.method == "provided_pdbqt":
            assert receptor_pdbqt is not None
            total_bytes += await _save_upload(receptor_pdbqt, staged_pdbqt, _RECEPTOR_LIMIT)
        else:
            selected = layout.root / "inputs" / "receptor" / "receptor_selected.pdb"
            prepare_receptor_pdbqt(
                staged_structure,
                selected,
                staged_pdbqt,
                protein_chain=config.target.protein_chain,
                settings=preparation,
                executor=CommandExecutor(layout.state / "commands"),
            )
        ligand_bytes = 0
        for upload, final_ligand in zip(ligand_files, final_ligands, strict=True):
            staged_ligand = layout.root / final_ligand.relative_to(final_root)
            ligand_bytes += await _save_upload(upload, staged_ligand, _LIGAND_FILE_LIMIT)
            if ligand_bytes > _LIGAND_TOTAL_LIMIT:
                raise ValueError("combined ligand uploads exceed the 2 GB limit")
        total_bytes += ligand_bytes
        staged_root.replace(final_root)
        incoming_parent.rmdir()
        registry.register_project(config.project.id, final_root)
        return ProjectLayout(final_root), config, total_bytes
    except Exception:
        if incoming_parent.exists():
            shutil.rmtree(incoming_parent)
        # A registry failure after the atomic move should not leave a project
        # that appears successfully imported to the browser.
        if final_root.exists():
            shutil.rmtree(final_root)
        raise
