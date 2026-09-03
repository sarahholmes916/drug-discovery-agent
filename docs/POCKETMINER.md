# PocketMiner integration

## What PocketMiner does

PocketMiner predicts a cryptic-pocket propensity for each protein residue from
one structure. It does **not** emit docking boxes or a ranked list of complete
pockets. The Drug Discovery Agent parses those propensities, attaches them to
exact receptor residue identities, spatially clusters high-scoring residues,
ranks the resulting regions, and constructs per-axis Vina boxes.

The adapter targets the authors' official
[`Mickdub/gvp` `pocket_pred` branch](https://github.com/Mickdub/gvp/tree/pocket_pred),
pinned to commit `187062df3c94127e991669768009141a08fd5d8b`. That implementation uses
TensorFlow and MDTraj, requires no GPU for inference, and exposes a Python demo
script rather than an installable command-line interface. The agent runs a
small argument-driven adapter in a separate managed environment; it does not
pretend PocketMiner is a Torch package or silently substitute another model.

## Included upstream runtime and one-time environment setup

The release contains the minimum PocketMiner inference runtime copied
byte-for-byte from the pinned upstream commit: `gvp.py`, `models.py`, `util.py`,
`xtal_predict.py`, `validate_performance_on_xtals.py`, the two checkpoint files,
and the complete upstream license. A fixed manifest records the upstream commit
and SHA-256 of every included file. The agent refuses to run if any byte differs.

On supported Windows, Linux, or macOS computers, use **Install automatically**
in the paired website. The equivalent command-line setup is:

```bash
drug-agent pocketminer-setup
drug-agent pocketminer-inspect
drug-agent doctor
```

`pocketminer-setup` does not download or modify PocketMiner code. It verifies the
included files, creates a private compatible conda environment, checks required
imports, hashes every inference/checkpoint file, and caches the verified result.
Native Windows uses the last official native-Windows TensorFlow line in that
private CPU-capable environment; PocketMiner inference does not require a GPU.
Set
`DRUG_AGENT_POCKETMINER_HOME` or `pocketminer.runtime.installation_root` to use
an explicit external upstream checkout instead of the included copy. An already
managed Python can be named with `pocketminer.runtime.python_executable`.
`doctor` reports the implementation, commit, exact checkpoint-file hashes,
TensorFlow version, MDTraj version, and any integrity failure.

## Vercel deployment boundary

Do not download PocketMiner, TensorFlow, model checkpoints, Vina, or Boltz into
a Vercel deployment. Vercel hosts only the static web UI; orchestration,
long-running scientific execution, and all molecular data remain in the
downloaded companion. The release operator can lock the companion to the exact
Vercel origin:

```bash
drug-agent companion --origin https://your-app.vercel.app
```

The browser fetches orchestration state, scores, candidates, and the colored
receptor directly from `127.0.0.1`; those artifacts never pass through Vercel.
The companion opens a local approval page and supplies the browser an invisible,
expiring, origin-scoped session. Each machine that executes the pipeline still
needs its own companion and private dependency environment, but PocketMiner
source and weights are already inside the companion.

## Configuration and deterministic methods

Set `pocket.mode: pocketminer`. Vina center/size are intentionally absent until
selection. Every method and threshold below is an ordinary typed project setting:

```yaml
pocket:
  mode: pocketminer
pocketminer:
  smoothing:
    enabled: true
    neighbor_count: 10
    radius_angstrom: 10.0
  clustering:
    method: spatial_graph
    score_threshold: 0.5
    edge_distance_angstrom: 8.0
    minimum_residues: 2
    hotspot_radius_angstrom: 8.0
    maximum_core_residues: 12
  ranking:
    method: weighted_interpretable
    weights: {mean_score: 0.40, max_score: 0.20, residue_count: 0.20, compactness: 0.20}
    count_saturation: 12
    compactness_scale_angstrom: 8.0
  box:
    method: score_weighted_centroid_heavy_atom_extent
    padding_angstrom: 7.0
    minimum_size: [18.0, 18.0, 18.0]
    maximum_size: [40.0, 40.0, 40.0]
  max_displayed_candidates: 5
```

Residues are keyed by chain, PDB residue number, insertion code, and residue
name. Their representative point is the side-chain heavy-atom centroid; glycine
or an incomplete side chain falls back to the residue heavy-atom centroid, then
to C-alpha only if necessary. Smoothing averages a residue and its configured
number of nearest representative points inside the configured radius.

Candidate detection makes a graph over residues meeting the configured score
threshold and adds edges by 3D representative-point distance. To prevent a chain
of above-threshold residues from producing a whole-protein docking box, each
connected component is reduced to a configurable local core around its
highest-scoring residue before box construction. The core includes at most
`maximum_core_residues` within `hotspot_radius_angstrom` and must still meet
`minimum_residues`. Sequence adjacency does not join distant residues. Ranking
exposes active-score mean, maximum score, residue count, RMS
compactness, 3D extent, each normalized contribution, and the weighted total.

The initial box center is the propensity-weighted representative-point centroid.
Each axis is independently sized from the selected residues' heavy-atom extent,
twice the configured padding, and per-axis min/max bounds; boxes are not forced
to be cubic.

## Human selection gate

The pipeline always reaches `AWAIT_POCKET_SELECTION` and stops with
`AWAITING_USER_SELECTION`, including when there is exactly one candidate. No
candidate is preselected. The viewer shows a blue-to-red active-score heatmap,
hover details, ranked metrics, and a dark wireframe for the exact live box.
Selecting a candidate keeps the protein in cartoon view and focuses the camera
on the box instead of expanding its residues into atom spheres and sticks.

The user may confirm a candidate, edit its center/size, or define a custom box.
When a box edit has no explicit residues, protein residues with a heavy atom in
that final box are deterministically derived for constrained Boltz. The canonical
`state/selected_pocket.json` records source, residue identities and scores,
metrics, original/final center, per-axis size and bounds, edit flag, timestamp,
candidate-set hash, receptor hash, and PocketMiner configuration hash.

Selection persists across resume and browser restarts. It becomes stale only
when the receptor, PocketMiner scientific configuration, or resulting candidate
set changes. Editing the selection invalidates the selection gate and downstream
Vina/constrained-Boltz branches. Unconstrained Boltz has no selected-pocket
dependency.

## Local artifacts

```text
pocketminer/
  raw/predictions.npy
  raw/run_metadata.json
  scores/residue_scores.json
  scores/residue_scores.csv
  candidates/detected_pockets.json
  candidates/ranked_pockets.json
  visualization/receptor_pocketminer_scores.pdb
state/selected_pocket.json
```

The visualization PDB is distinct from the original and prepared receptor. It
stores the active PocketMiner score (smoothed when smoothing is enabled, 0–1)
in each protein atom's B-factor field so the displayed hotspot and candidate
box use the same score. It is rejected if atom identity/order or coordinates
change by more than 0.001 Å.

## NS1 regression and troubleshooting

`tests/regression/test_ns1_pocketminer.py` runs the actual pinned model whenever
the managed runtime is installed. It reports candidate center distance, box
intersection-over-union, and whether a candidate shares a residue hotspot with
the historical manual NS1 box (center `26.448, 12.021, 27.940`; size
`28, 28, 28` Å). These are sanity comparisons, not an expectation that a learned
cryptic-site prediction reproduce a manually selected docking box exactly.

Common failures are reported explicitly:

- unsupported operating system/CPU: follow the upstream manual instructions;
- missing environment manager: use the website's automatic setup, which manages
  micromamba for you;
- included file integrity failure: reinstall the official companion archive;
- score/residue count mismatch: use the same unchanged receptor for inference
  and parsing, with standard protein residues and complete backbone atoms;
- no candidates at the configured threshold: inspect the heatmap, revise the
  documented threshold deliberately, or define a custom manual box.
