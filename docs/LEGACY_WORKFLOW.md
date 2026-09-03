# Legacy workflow inventory

This document records the behavioral source material inspected before the new
package was implemented. Files under `legacy/` are immutable reference material;
the production package wraps or ports their behavior stage by stage.

## Vina screening

| Legacy file | Behavior and data contract |
|---|---|
| `legacy/vina/split_sdf.py` | Reads a multi-record SDF with `Chem.SDMolSupplier(removeHs=False)`, skips unreadable records, uses `_Name` when present, falls back to `structures_<1-based-index>`, replaces characters outside `[^\w.\-]`, truncates to 120 characters, and resolves duplicates with `_2`, `_3`, and so on. Writes one SDF per readable record. |
| `legacy/vina/vina_docking.py` | Processes a directory of one-molecule SDF files. Adds explicit H atoms, preserves an existing 3D conformer, otherwise embeds with seed 42 and attempts UFF optimization. Invokes `mk_prepare_ligand.py`, then Vina; parses seed and mode rows; writes summary/mode workbook sheets. Resumes successful rows by source mtime. Historical NS1 box is `(26.448, 12.021, 27.940)` with size `(28, 28, 28)`. |
| `legacy/vina/dock_all_sdf.py` | Iterates every record in every top-level SDF under `Drugs/` directly. Missing names fall back to `<source_stem>_<1-based-index>`. Duplicate-name resolution is scoped to each source file. Uses the full profile: exhaustiveness 8, three modes, save every 25 molecules. Invalid records become failed result rows rather than being omitted. |
| `legacy/vina/drugbank_MD.py` | Byte-for-byte equivalent to `dock_all_sdf.py` except for the fast profile (exhaustiveness 4, one mode, save every molecule). |

The production implementation keeps both ingestion paths but uses stable
canonical ligand IDs in addition to the legacy display/file name. Modification
records replace silent chemistry changes, and content/config hashes replace
mtime-only resume decisions. The NS1 box and profile numbers are reference
configuration, never generic defaults.

The Vina stdout parser accepts rows containing mode, affinity, RMSD lower bound,
and RMSD upper bound, and extracts `random seed:` from stdout. Prepared artifacts
are named `<legacy_name>.sdf`, `<legacy_name>.pdbqt`, and
`<legacy_name>_out.pdbqt` within their stage directories.

## Vina pose and interaction analysis

| Legacy file | Behavior and data contract |
|---|---|
| `legacy/vina_analysis/common.py` | Fixed-width PDBQT parsing; element normalization; all-model Vina parsing; Meeko `REMARK SMILES IDX` and `REMARK H PARENT` parsing; receptor parsing and inferred local covalent bonds; source-SDF graph matching; Vina-coordinate transfer; bond-length validation; RDKit feature perception and geometry helpers. |
| `legacy/vina_analysis/extract_and_distance.py` | Matches shortlist names to `<name>_out.pdbqt`, records missing candidates, extracts all pose metrics and mode-1 atoms, computes heavy-atom minimum distance to every receptor residue, and calls contacts at `<4.0 A`. |
| `legacy/vina_analysis/reconstruct_sdfs.py` | Reconstructs chemically meaningful mode-1 SDFs from source molecular graphs plus Meeko/Vina coordinates, preserving bond orders, aromaticity, charge, and stereochemistry. Emits mapping validation and a zip archive. |
| `legacy/vina_analysis/interactions.py` | PLIP-compatible, non-native interaction logic for hydrophobic contacts, hydrogen bonds, salt bridges, pi stacking, pi-cation interactions, and halogen bonds. Also calculates a 7.5 A binding-site residue table and ligand/residue summaries. |
| `legacy/vina_analysis/append_workbook.py` | Appends distance, interaction, ligand, residue, mapping, integrated-summary, and dashboard sheets. Some counts and NS1 warnings are historical report text and are not generic scientific defaults. |
| `legacy/vina_analysis/run_all.py` | Orchestrates shortlist extraction, distance analysis, SDF reconstruction, fresh or captured interaction rows, and workbook production. |
| `legacy/vina_analysis/reference_outputs/reference_mapping_validation.json` | Regression reference for 40 requested compounds: 38 mapped, two missing, with one distorted pose (`structures_1756`) explicitly flagged for review. |
| `legacy/vina_analysis/reference_outputs/reference_interactions.json` | Exact captured original run: 361 interactions, 1,130 binding-site residue rows, 38 ligand summaries, and the workbook-oriented aggregate tables. |

The interaction implementation is never described as native PLIP. Its historical
thresholds are preserved as a named configurable profile: hydrophobic 4.0 A;
H-bond D-A 4.1 A and donor angle 100 degrees; salt bridge 5.5 A; pi stack 5.5 A,
30 degrees, 2.0 A offset; pi-cation 6.0 A; and halogen 4.0 A with 135-degree donor
and 90--150-degree acceptor angles.

## Boltz-2: Vina-site-constrained

| Legacy file | Behavior and data contract |
|---|---|
| `legacy/boltz/example_inputs/*.yaml` | Protein `A`, ligand `L`, forced receptor CIF template (threshold 2.0 A), affinity property, and forced pocket constraint with 12 mapped sequence positions and maximum distance 6.0 A. |
| `legacy/boltz/pocket_residues.csv` | Maps NS1 PDB residues 84--89, 135--138, 142--143 to receptor sequence ordinals 6--11, 57--60, 64--65, including residue identity, distance from box center, and heavy atoms inside the Vina box. |
| `legacy/boltz/yaml_pocket_mapping.csv` | Per-input expansion of that explicit residue mapping across 39 YAML files (468 rows). |
| `legacy/boltz/conversion_validation.json` | Validates PDBQT-to-PDB conversion for 1,207 receptor atoms with a maximum coordinate delta of 0.0 A; only PDBQT-only fields were removed. |
| `legacy/boltz/preparation_summary.json` | Records NS1 receptor range, 127-residue sequence, pocket-selection rule (within 8 A of the box center, capped at 12), and forced template/pocket parameters. These are provenance, not defaults. |
| `legacy/boltz/run_boltz_command.txt` | Historical execution: potentials, three recycling steps, 200 sampling steps, five diffusion samples, PDB output, one GPU device, override, and MSA server. |
| `legacy/boltz/example_predictions/` | Five predicted PDB models plus one affinity JSON and one confidence JSON per model for `structures_12233`. |

Constrained preparation is allowed only after coordinate validation and an
unambiguous `(chain, residue number, insertion code, residue name)` to Boltz
sequence-position mapping. Generated YAMLs must retain a pocket constraint.

## Boltz-2: unconstrained

| Legacy file | Behavior and data contract |
|---|---|
| `legacy/boltz/unconstrained/original_inputs/*.yaml` | Historical protein, ligand, optional PDB template, and affinity property with no `constraints` key. |
| `legacy/boltz/unconstrained/generate_unconstrained_inputs.py` | Portable YAML generator; detects PDB versus CIF template keys and intentionally never creates `constraints`. |
| `legacy/boltz/unconstrained/run_unconstrained_boltz2.py` | Portable command builder with the same sampling defaults as the constrained historical run. |
| `legacy/boltz/unconstrained/manifest.csv` | 39 ligand names/SMILES/source records and generated input paths. |
| `legacy/boltz/unconstrained/summary.csv` | 39 successful ligand summaries containing affinity, binary affinity probability, confidence, ligand iPTM, complex pLDDT/iPLDDT, and output references. |
| `legacy/boltz/unconstrained/run_failures.csv` | Empty historical failure table with `input,returncode,yaml` schema. |
| `legacy/boltz/unconstrained/example_predictions/` | Representative unconstrained CIF, affinity metrics, and model-0 confidence for `structures_12233`. |

Unconstrained preparation has its own validator and must reject any pocket or
constraints block. A template does not make the run site-constrained.

## Boltz result conventions

Affinity JSON includes `affinity_pred_value`,
`affinity_probability_binary`, and the corresponding `*1`/`*2` values.
Confidence JSON includes `confidence_score`, `ptm`, `iptm`, `ligand_iptm`,
`protein_iptm`, `complex_plddt`, `complex_iplddt`, `complex_pde`,
`complex_ipde`, `chains_ptm`, and `pair_chains_iptm`. Every model is retained;
model 0 is not assumed to be best.

## Native PLIP

`legacy/plip/run_plip_boltz_batch.py` runs `compound x model` (historically ten
compounds by five models), requires the Open Babel Python binding with InChIKey
support, invokes `plip -f <pdb> -x -t -o <directory>`, and isolates missing or
failed structures. The production port discovers all selected models and parses
structured PLIP XML where available.

## Fixtures and naming links

`structures_12233` is the connected regression case: source 2D SDF, prepared 3D
SDF with explicit H, prepared Meeko PDBQT, three-mode Vina output, constrained
Boltz YAML, five constrained models, and an unconstrained input/model are all
present. `structures_9064` has an empty SDF title, exercising fallback naming;
`UCM` has a named title. Files copied into `tests/fixtures/` are content-identical
to their legacy counterparts where applicable.

## External dependencies

- Python, RDKit, pandas/openpyxl in legacy docking and workbook flows.
- Meeko command `mk_prepare_ligand.py`.
- AutoDock Vina command `vina`.
- NumPy and RDKit for structural/interaction analysis.
- Historical `artifact_tool` for workbook manipulation; production reporting
  uses a replaceable reporter and does not make this private dependency core.
- Boltz-2 command `boltz`, optionally an MSA service, and optionally CUDA/GPU.
- Native PLIP command `plip` and Open Babel.
