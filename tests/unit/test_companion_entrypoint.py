from __future__ import annotations

from types import SimpleNamespace

from apps import companion_main


def test_internal_ligand_preparation_dispatches_to_exact_meeko_cli(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_import(name: str):
        captured["module"] = name

        def run():
            captured["argv"] = list(companion_main.sys.argv)
            return 0

        return SimpleNamespace(main=run)

    monkeypatch.setattr(companion_main.importlib, "import_module", fake_import)
    monkeypatch.setattr(
        companion_main.sys,
        "argv",
        ["companion.exe", "--internal-prepare-ligand", "-i", "input.sdf", "-o", "output.pdbqt"],
    )

    assert companion_main.main() == 0
    assert captured == {
        "module": "meeko.cli.mk_prepare_ligand",
        "argv": ["mk_prepare_ligand.py", "-i", "input.sdf", "-o", "output.pdbqt"],
    }
