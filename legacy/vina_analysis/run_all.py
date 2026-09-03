"""Run the complete Vina top-40 analysis pipeline.

Example:
    python run_all.py \
      --base-workbook "analysis_outputs_with_plip(1).xlsx" \
      --top40 vina_top40.csv \
      --docked-zip docked.zip \
      --receptor ns1_ed_receptor.pdbqt \
      --sdf-zip 'split_sdf_files 3.zip' \
      --output analysis_outputs_with_plip_vina_interactions_rebuilt.xlsx
"""
from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import json

from append_workbook import append_interaction_sheets
from extract_and_distance import run as run_extract_and_distance
from interactions import analyze_all
from reconstruct_sdfs import reconstruct_all
from common import read_top40


def parser() -> ArgumentParser:
    p = ArgumentParser(description=__doc__)
    p.add_argument("--base-workbook", required=True)
    p.add_argument("--top40", required=True)
    p.add_argument("--docked-zip", required=True)
    p.add_argument("--receptor", required=True)
    p.add_argument("--sdf-zip", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--work-dir", default="vina_analysis_work")
    p.add_argument(
        "--use-reference-interactions",
        action="store_true",
        help=(
            "Use the exact intermediate interaction rows captured from the original "
            "workbook-producing run. Without this flag, interactions are freshly "
            "recomputed by interactions.py."
        ),
    )
    return p


def main() -> None:
    args = parser().parse_args()
    root = Path(args.work_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    distance_workbook = root / "analysis_outputs_with_plip_and_vina.xlsx"
    pose_workbook = root / "vina_top40_pose_analysis.xlsx"
    selected_zip = root / "vina_top40_docked_files.zip"

    extraction = run_extract_and_distance(
        base_workbook=args.base_workbook,
        top40_csv=args.top40,
        docked_zip=args.docked_zip,
        receptor_path=args.receptor,
        work_dir=root,
        output_workbook=distance_workbook,
        pose_workbook=pose_workbook,
        selected_zip=selected_zip,
    )

    selected_dir = root / "vina_top40_docked"
    reconstructed, validation = reconstruct_all(
        top40_csv=args.top40,
        docked_dir=selected_dir,
        sdf_zip=args.sdf_zip,
        work_dir=root,
        output_zip=root / "vina_top40_mode1_docked_sdfs.zip",
    )

    if args.use_reference_interactions:
        bundle_root = Path(__file__).resolve().parent
        results = json.loads(
            (bundle_root / "reference_outputs" / "reference_interactions.json").read_text(
                encoding="utf-8"
            )
        )
        validation = json.loads(
            (bundle_root / "reference_outputs" / "reference_mapping_validation.json").read_text(
                encoding="utf-8"
            )
        )
    else:
        results = analyze_all(
            reconstructed=reconstructed,
            receptor_path=args.receptor,
            top40_rows=read_top40(args.top40),
            mapping_validation=validation,
            output_json=root / "vina_interaction_results.json",
        )

    append_interaction_sheets(
        source_workbook=distance_workbook,
        output_workbook=args.output,
        results=results,
        validation=validation,
    )

    print(f"Final workbook: {Path(args.output).resolve()}")
    print(f"Pose workbook: {pose_workbook}")
    print(f"Matched docked files: {selected_zip}")
    print(f"Reconstructed SDF poses: {root / 'vina_top40_mode1_docked_sdfs.zip'}")
    print(f"Missing candidates: {', '.join(extraction['missing'])}")


if __name__ == "__main__":
    main()
