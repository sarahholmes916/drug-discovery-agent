from __future__ import annotations

import asyncio

import pytest

from apps.runner.project_uploads import (
    MAX_LIGAND_FILES,
    ProjectUploadOptions,
    create_project_from_uploads,
)
from apps.runner.registry import RunnerRegistry
from drug_discovery_agent.project.io import read_json


class Upload:
    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self._content = content
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._content) - self._offset
        chunk = self._content[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_multiple_ligand_uploads_create_a_local_directory_project(tmp_path) -> None:
    registry = RunnerRegistry(tmp_path / "registry.json")
    layout, config, uploaded_bytes = asyncio.run(create_project_from_uploads(
        options=ProjectUploadOptions(
            project_id="browser_project",
            display_name="Browser project",
            pocketminer=True,
            boltz_constrained=True,
            boltz_unconstrained=True,
            protein_sequence="AAAA",
        ),
        receptor_structure=Upload("receptor.cif", b"data_target\n"),
        receptor_pdbqt=Upload("receptor.pdbqt", b"ATOM\n"),
        ligand_files=[Upload("one.sdf", b"one\n$$$$\n"), Upload("two.sdf", b"two\n$$$$\n")],
        projects_root=tmp_path / "projects",
        registry=registry,
    ))
    assert config.workflow.value == "vina_to_both_boltz"
    assert config.ligands[0].kind == "sdf_directory"
    assert config.analysis.vina_shortlist == 50
    assert config.analysis.vina_selection_metric == "best_affinity"
    assert uploaded_bytes > 0
    references = read_json(layout.local_references)["references"]
    ligand_directory = layout.root / "inputs" / "ligands"
    assert references["ligand_set_01"] == str(ligand_directory)
    assert sorted(path.name for path in ligand_directory.glob("*.sdf")) == [
        "ligand_source_0001.sdf", "ligand_source_0002.sdf",
    ]
    assert registry.project_root("browser_project") == layout.root


def test_boltz_upload_extracts_sequence_from_receptor_when_not_provided(tmp_path) -> None:
    registry = RunnerRegistry(tmp_path / "registry.json")
    _, config, _ = asyncio.run(create_project_from_uploads(
        options=ProjectUploadOptions(
            project_id="extracted_sequence",
            display_name="Extracted sequence",
            pocketminer=False,
            boltz_constrained=True,
            boltz_unconstrained=False,
        ),
        receptor_structure=Upload(
            "receptor.pdb",
            b"ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 20.00           C  \n"
            b"ATOM      2  CA  GLY A   2       2.000   2.000   3.000  1.00 20.00           C  \nEND\n",
        ),
        receptor_pdbqt=Upload("receptor.pdbqt", b"ATOM\n"),
        ligand_files=[Upload("ligands.sdf", b"$$$$\n")],
        projects_root=tmp_path / "projects",
        registry=registry,
    ))

    assert config.target.protein_chain == "A"
    assert config.target.protein_sequence == "AG"


def test_boltz_upload_reports_failed_extraction_without_leaving_partial_project(tmp_path) -> None:
    with pytest.raises(ValueError, match="could not extract a protein sequence"):
        asyncio.run(create_project_from_uploads(
            options=ProjectUploadOptions(
                project_id="missing_sequence",
                display_name="Missing sequence",
                pocketminer=False,
                boltz_constrained=True,
                boltz_unconstrained=False,
            ),
            receptor_structure=Upload("receptor.pdb", b"ATOM\n"),
            receptor_pdbqt=Upload("receptor.pdbqt", b"ATOM\n"),
            ligand_files=[Upload("ligands.sdf", b"$$$$\n")],
            projects_root=tmp_path / "projects",
            registry=RunnerRegistry(tmp_path / "registry.json"),
        ))
    assert not (tmp_path / "projects").exists()


def test_ligand_folder_file_count_is_bounded_before_writing(tmp_path) -> None:
    ligand = Upload("ligand.sdf", b"$$$$\n")
    with pytest.raises(ValueError, match="5,000"):
        asyncio.run(create_project_from_uploads(
            options=ProjectUploadOptions(
                project_id="too_many_ligands",
                display_name="Too many ligands",
                pocketminer=False,
                boltz_constrained=False,
                boltz_unconstrained=False,
            ),
            receptor_structure=Upload("receptor.pdb", b"ATOM\n"),
            receptor_pdbqt=Upload("receptor.pdbqt", b"ATOM\n"),
            ligand_files=[ligand] * (MAX_LIGAND_FILES + 1),
            projects_root=tmp_path / "projects",
            registry=RunnerRegistry(tmp_path / "registry.json"),
        ))
    assert not (tmp_path / "projects").exists()


def test_recommended_receptor_preparation_generates_pdbqt_without_upload(tmp_path, monkeypatch) -> None:
    def fake_prepare(source, selected, pdbqt, **kwargs):
        selected.write_text("ATOM\n", encoding="utf-8")
        pdbqt.write_text("ATOM\n", encoding="utf-8")

    monkeypatch.setattr("apps.runner.project_uploads.prepare_receptor_pdbqt", fake_prepare)
    registry = RunnerRegistry(tmp_path / "registry.json")
    layout, config, _ = asyncio.run(create_project_from_uploads(
        options=ProjectUploadOptions(
            project_id="automatic_prep",
            display_name="Automatic prep",
            pocketminer=False,
            boltz_constrained=False,
            boltz_unconstrained=False,
            receptor_preparation="meeko",
            agent_notes="Keep the catalytic context under review.",
        ),
        receptor_structure=Upload("receptor.pdb", b"ATOM\n"),
        receptor_pdbqt=None,
        ligand_files=[Upload("ligands.sdf", b"$$$$\n")],
        projects_root=tmp_path / "projects",
        registry=registry,
    ))
    assert config.target.preparation.method == "meeko"
    assert config.project.guidance_notes == ["Keep the catalytic context under review."]
    assert (layout.root / "inputs" / "receptor" / "receptor.pdbqt").read_text() == "ATOM\n"
