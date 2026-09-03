from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Iterable, Mapping


def build_report(
    rows: Iterable[Mapping[str, object]],
    output_directory: str | Path,
    *,
    title: str = "Drug Discovery Agent Report",
) -> dict[str, Path]:
    records = [dict(row) for row in rows]
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    json_path, csv_path, html_path = output / "results.json", output / "results.csv", output / "report.html"
    json_path.write_text(json.dumps(records, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    columns = sorted({key for row in records for key in row})
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in records:
            writer.writerow({key: json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in row.items()})
    headings = "".join(f"<th>{html.escape(key)}</th>" for key in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row.get(key, '')))}</td>" for key in columns) + "</tr>"
        for row in records
    )
    html_path.write_text(
        "<!doctype html><meta charset='utf-8'><title>" + html.escape(title) + "</title>"
        "<style>body{font-family:system-ui;margin:2rem}table{border-collapse:collapse}th,td{border:1px solid #ccc;padding:.4rem}th{background:#eef}</style>"
        f"<h1>{html.escape(title)}</h1><p>Detailed scientific report stored locally.</p>"
        f"<table><thead><tr>{headings}</tr></thead><tbody>{body}</tbody></table>",
        encoding="utf-8",
    )
    return {"json": json_path, "csv": csv_path, "html": html_path}

