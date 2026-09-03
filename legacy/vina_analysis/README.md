# Vina top-40 / NS1 analysis code

This bundle contains the complete cleaned pipeline used to build the Vina additions to the Boltz-2/PLIP workbook.

## Important provenance note

The work was performed in several notebook-style execution cells rather than in one saved script.

- `extract_and_distance.py` is a direct cleanup/refactor of the executed pose-extraction and receptor-distance code.
- `append_workbook.py` is a direct cleanup/refactor of the executed workbook-append code.
- `reconstruct_sdfs.py` and `interactions.py` consolidate the SDF mapping and PLIP-compatible interaction cells into reusable functions.
- The interaction notebook cells were not persisted as a standalone source file. To preserve the **exact rows and counts from the run that created the delivered workbook**, this bundle includes:
  - `reference_outputs/reference_interactions.json`
  - `reference_outputs/reference_mapping_validation.json`

Running with `--use-reference-interactions` regenerates the exact interaction tables from that original run. Running without it freshly recomputes interactions from the structural inputs. Fresh recomputation can differ slightly because symmetric atom mappings and hydrophobic-contact redundancy handling can select chemically equivalent atoms differently.

The interaction stage is **PLIP-compatible**, not native PLIP: it uses RDKit chemistry, the prepared receptor PDBQT, explicit polar hydrogens, and PLIP-style geometric thresholds. It does not generate real PLIP XML files.

## Files

- `common.py` — PDBQT parsing, receptor parsing, geometry, SDF/PDBQT atom mapping.
- `extract_and_distance.py` — extracts the top-40 docking files, summarizes all Vina poses, computes mode-1 residue distances and contacts under 4 Å, and appends distance sheets.
- `reconstruct_sdfs.py` — transfers Vina mode-1 coordinates to the corresponding source-SDF molecular graphs and writes chemically complete docked SDFs.
- `interactions.py` — PLIP-compatible hydrophobic, hydrogen-bond, salt-bridge, pi-stacking, pi-cation, and halogen-bond calculations and summaries.
- `append_workbook.py` — appends the interaction-level, ligand-level, residue-level, mapping, integrated-summary, and dashboard sheets.
- `run_all.py` — command-line orchestration.
- `reference_outputs/` — exact intermediate tables captured from the original workbook-producing run.

## Inputs

The command expects:

- `analysis_outputs_with_plip(1).xlsx`
- `vina_top40.csv`
- `docked.zip`
- `ns1_ed_receptor.pdbqt`
- `split_sdf_files 3.zip`

## Exact reproduction command

```bash
python run_all.py \
  --base-workbook "/path/analysis_outputs_with_plip(1).xlsx" \
  --top40 /path/vina_top40.csv \
  --docked-zip /path/docked.zip \
  --receptor /path/ns1_ed_receptor.pdbqt \
  --sdf-zip "/path/split_sdf_files 3.zip" \
  --work-dir ./vina_analysis_work \
  --output ./analysis_outputs_with_plip_vina_interactions.xlsx \
  --use-reference-interactions
```

## Fresh recomputation command

Remove `--use-reference-interactions`:

```bash
python run_all.py \
  --base-workbook "/path/analysis_outputs_with_plip(1).xlsx" \
  --top40 /path/vina_top40.csv \
  --docked-zip /path/docked.zip \
  --receptor /path/ns1_ed_receptor.pdbqt \
  --sdf-zip "/path/split_sdf_files 3.zip" \
  --work-dir ./vina_analysis_work \
  --output ./analysis_outputs_with_plip_vina_interactions_recomputed.xlsx
```

## Original-run interaction thresholds

- Ligand–residue contact: `< 4.0 Å`
- Hydrophobic atom contact: `≤ 4.0 Å`
- Hydrogen-bond donor–acceptor distance: `≤ 4.1 Å`
- Hydrogen-bond D–H–A angle: `≥ 100°`
- Salt bridge: `≤ 5.5 Å`
- Pi-stacking centroid distance: `≤ 5.5 Å`
- Pi-stacking angular deviation: `≤ 30°`
- Pi-stacking offset: `≤ 2.0 Å`
- Pi-cation: `≤ 6.0 Å`
- Halogen bond: `≤ 4.0 Å`, donor angle `≥ 135°`, acceptor angle `90–150°`

## Outputs

The pipeline writes:

- Final combined workbook
- `vina_top40_pose_analysis.xlsx`
- `vina_top40_docked_files.zip`
- `vina_top40_mode1_docked_sdfs.zip`
- JSON intermediates and mapping validation in the work directory

The top-40 list contained two unavailable entries: `midostaurin_fixed` and `midostaurin`.
