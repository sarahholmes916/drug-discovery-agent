from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import json
from typing import Any, Iterable, Mapping


INTERACTION_TYPES = (
    "Hydrophobic interaction",
    "Hydrogen bond",
    "Salt bridge",
    "π-stacking",
    "π-cation interaction",
    "Halogen bond",
)

MANAGED_SHEETS = (
    "Vina PLIP README",
    "Vina PLIP Interactions",
    "Vina PLIP Binding Residues",
    "Vina Residue Distances",
    "Vina PLIP Type Summary",
    "Vina PLIP Ligand Summary",
    "Vina SDF Mapping",
    "Vina PLIP Dashboard",
)


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return value


def _records_table(records: list[dict[str, Any]], leading: tuple[str, ...]) -> list[list[Any]]:
    remaining = sorted({key for row in records for key in row}.difference(leading))
    headers = [*leading, *remaining]
    return [headers, *[[_cell(row.get(header)) for header in headers] for row in records]]


def build_workbook_tables(analysis_rows: Iterable[Mapping[str, Any]]) -> dict[str, list[list[Any]]]:
    """Convert local Vina analysis records to deterministic workbook tables."""
    rows = [dict(value) for value in analysis_rows]
    interactions: list[dict[str, Any]] = []
    binding: list[dict[str, Any]] = []
    distances: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    ligand_summary: list[list[Any]] = []
    type_counts: Counter[str] = Counter()
    type_ligands: dict[str, set[str]] = defaultdict(set)
    type_residues: dict[str, set[str]] = defaultdict(set)
    type_distances: dict[str, list[float]] = defaultdict(list)

    for row in rows:
        ligand_id = str(row.get("ligand_id", ""))
        legacy_name = str(row.get("legacy_name", ""))
        counts: Counter[str] = Counter()
        residues: set[str] = set()
        for raw in row.get("interactions", []) or []:
            item = {"ligand_id": ligand_id, "legacy_name": legacy_name, **dict(raw)}
            interactions.append(item)
            kind = str(item.get("interaction_type", ""))
            residue = str(item.get("residue", ""))
            counts[kind] += 1
            type_counts[kind] += 1
            type_ligands[kind].add(ligand_id)
            if residue:
                residues.add(residue)
                type_residues[kind].add(residue)
            distance = item.get("primary_distance_angstrom")
            if isinstance(distance, (int, float)):
                type_distances[kind].append(float(distance))
        for raw in row.get("binding_site_residues", []) or []:
            binding.append({"ligand_id": ligand_id, "legacy_name": legacy_name, **dict(raw)})
        for raw in row.get("distances", []) or []:
            distances.append({"ligand_id": ligand_id, "legacy_name": legacy_name, **dict(raw)})

        mapping = dict(row.get("mapping") or {})
        mappings.append({
            "ligand_id": ligand_id,
            "legacy_name": legacy_name,
            "status": row.get("status"),
            "error": row.get("error"),
            **mapping,
        })
        ligand_summary.append([
            ligand_id,
            legacy_name,
            row.get("status"),
            sum(counts.values()),
            len(residues),
            *[counts[kind] for kind in INTERACTION_TYPES],
        ])

    all_types = [*INTERACTION_TYPES, *sorted(set(type_counts).difference(INTERACTION_TYPES))]
    type_summary = [[
        kind,
        type_counts[kind],
        len(type_ligands[kind]),
        len(type_residues[kind]),
        min(type_distances[kind]) if type_distances[kind] else None,
        sum(type_distances[kind]) / len(type_distances[kind]) if type_distances[kind] else None,
    ] for kind in all_types]
    dashboard = [
        ["Metric", "Value"],
        ["Ligands analyzed", len(rows)],
        ["Successful ligands", sum(row.get("status") == "SUCCESS" for row in rows)],
        ["Ligands needing review", sum(row.get("status") == "NEEDS_REVIEW" for row in rows)],
        ["Failed ligands", sum(row.get("status") == "FAILED" for row in rows)],
        ["Interaction records", len(interactions)],
        ["Binding-site residue rows", len(binding)],
    ]
    return {
        "Vina PLIP README": [
            ["Vina PLIP-Compatible Interaction Analysis", "Local run output"],
            ["Method", "Source-SDF chemistry reconstructed at Vina mode-1 coordinates"],
            ["Interaction types", ", ".join(INTERACTION_TYPES)],
            ["Native PLIP", "No; native PLIP is used separately for Boltz structures"],
            ["Scope", "No target-specific counts, names, or warnings are embedded in this reporter"],
        ],
        "Vina PLIP Interactions": _records_table(
            interactions, ("ligand_id", "legacy_name", "interaction_type", "residue")
        ),
        "Vina PLIP Binding Residues": _records_table(
            binding, ("ligand_id", "legacy_name", "protein_chain", "residue")
        ),
        "Vina Residue Distances": _records_table(
            distances, ("ligand_id", "legacy_name", "protein_chain", "residue")
        ),
        "Vina PLIP Type Summary": [[
            "Interaction Type", "Count", "Unique Ligands", "Unique Residues",
            "Minimum Distance (angstrom)", "Mean Distance (angstrom)",
        ], *type_summary],
        "Vina PLIP Ligand Summary": [[
            "Ligand ID", "Legacy Name", "Status", "Total Interactions", "Unique Residues",
            *INTERACTION_TYPES,
        ], *ligand_summary],
        "Vina SDF Mapping": _records_table(
            mappings, ("ligand_id", "legacy_name", "status", "mapping_method")
        ),
        "Vina PLIP Dashboard": dashboard,
    }


def append_analysis_workbook(
    source_workbook: str | Path,
    output_workbook: str | Path,
    analysis_rows: Iterable[Mapping[str, Any]],
) -> Path:
    """Preserve an XLSX workbook and replace this reporter's managed sheets."""
    try:
        from openpyxl import load_workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError as exc:
        raise RuntimeError(
            "openpyxl is required for workbook output; install drug-discovery-agent[reporting]"
        ) from exc

    source = Path(source_workbook)
    if not source.is_file():
        raise FileNotFoundError(source)
    output = Path(output_workbook)
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook = load_workbook(source)
    for name in MANAGED_SHEETS:
        if name in workbook.sheetnames:
            workbook.remove(workbook[name])

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for name, table in build_workbook_tables(analysis_rows).items():
        worksheet = workbook.create_sheet(name)
        for row in table:
            worksheet.append([_cell(value) for value in row])
        if table:
            for cell in worksheet[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        for column in worksheet.columns:
            width = min(60, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
            worksheet.column_dimensions[column[0].column_letter].width = width

    temporary = output.with_name(f".{output.name}.tmp.xlsx")
    workbook.save(temporary)
    temporary.replace(output)
    return output
