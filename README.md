# Drug Discovery Agent

A local-first, resumable implementation of the repository's legacy
drug-discovery workflow. The scientific engine runs on the researcher's machine;
the optional hosted application coordinates opaque jobs and aggregate progress
without receiving molecular data.

The files under `legacy/` remain unchanged and are the behavioral source of
truth. The migration inventory and exact file-to-behavior mapping are in
[`docs/LEGACY_WORKFLOW.md`](docs/LEGACY_WORKFLOW.md).

## What is implemented

- Typed YAML configuration with separate scientific, execution, and
  control-plane settings.
- Local project layout, opaque local references, atomic state, item failures,
  content/config hashes, command records, and run provenance.
- Multi-record SDF and SDF-directory ingestion with legacy naming, original
  identifiers, canonical IDs, duplicate handling, and invalid-record retention.
- Legacy RDKit explicit-H/3D behavior, Meeko preparation, Vina command/parsing,
  all-model PDBQT parsing, QC, and shortlisting.
- An explicit post-Vina gate: all prepared ligands are docked, the full Vina
  ranking is retained, and a user-selected top 1–50 advances to slower stages
  by best affinity, mean pose affinity, or ligand efficiency.
- Source-SDF/Vina coordinate reconstruction, residue distances, and all six
  legacy PLIP-compatible Vina interaction categories.
- Coordinate-preserving receptor validation across PDB/PDBQT/mmCIF and explicit,
  validated receptor-residue to Boltz-sequence mapping.
- Pinned official PocketMiner inference, normalized residue-probability artifacts,
  spatial candidate detection, interpretable ranking, non-cubic box derivation,
  a mandatory human selection gate, and selected-pocket Vina/Boltz propagation.
- Separate constrained and unconstrained Boltz input builders/validators,
  configurable execution, and all-model affinity/confidence parsing.
- Native PLIP compound-by-model execution with isolated failures and XML parsing.
- Protein Kabsch alignment, guarded ligand RMSD, separate contact/interaction
  overlap, configurable consensus ranking, and local JSON/CSV/HTML reports,
  with opt-in append-to-workbook reporting that preserves existing sheets.
- Runner `doctor`, project initialization, local run/resume/status/cancel,
  outbound control-plane polling, restricted localhost bridge, minimal hosted
  FastAPI/SQLite control plane, and a minimal web proof.

## Install

Python 3.11 or newer is required. Install the package and the extras needed on
the machine:

```bash
python -m pip install -e ".[scientific,runner,test]"
```

RDKit, Meeko, AutoDock Vina, Boltz-2, PLIP/Open Babel, CUDA, and GPU drivers have
their own platform constraints. The paired website can install the pinned Vina,
Boltz-2, and PocketMiner runtimes described below; it never uploads research
data to compensate for a missing local tool.

Install `.[reporting]` only when `reporting.source_workbook_ref` is configured.

```bash
drug-agent doctor
```

`doctor` reports every capability independently. A missing optional tool does
not prevent unrelated workflows.

PocketMiner's exact pinned upstream inference code and trained checkpoint are
included with the agent. On Windows, Linux, or macOS, run
`drug-agent pocketminer-setup` once to create its separate compatible
TensorFlow/MDTraj environment; see
[`docs/POCKETMINER.md`](docs/POCKETMINER.md) for pinning, model hashes, methods,
selection behavior, and the Vercel/local-runner deployment boundary.

## Create and run a local project

Copy [`examples/project.example.yaml`](examples/project.example.yaml), replace
the placeholder pocket with a target-specific definition, and register source
paths under opaque local IDs:

```bash
drug-agent init my-project.yaml \
  --ref receptor_structure=/private/receptor.pdb \
  --ref receptor_vina=/private/receptor.pdbqt \
  --ref ligand_set_01=/private/ligands.sdf
```

The command prints the created project directory. Then run its copied
`project.yaml`:

```bash
drug-agent run ~/DrugDiscoveryAgent/projects/example_project/project.yaml
drug-agent status <run_id>
drug-agent resume <run_id>
drug-agent cancel <run_id>
```

The browser may close without stopping the CLI/runner process. Completed items
with matching content/config hashes and present outputs are reused; failed items
retry according to policy.

To run the complete interface locally, start its UI, control API, protected
bridge, and worker with one command. The browser and companion create an
origin-scoped session automatically:

```bash
drug-agent ui
```

The UI opens at `http://127.0.0.1:8000`. Click **Connect companion**, verify the
displayed local origin, and click **Allow this website**. No token is displayed
or entered. The chat runs the open-source Qwen3 1.7B model locally in a WebGPU
browser worker, downloads it on the first message, and caches it for later
visits; no LLM API key or hosted inference is used. It can explain the workflow
and apply validated changes to its visible settings. The guided fallback remains
available when WebGPU cannot run the model. The agent asks for a receptor
PDB/mmCIF, one or more ligand SDF files, preparation preferences, and workflow choices. Recommended mode
creates the Vina PDBQT locally with Meeko; an expert-prepared PDBQT remains an
override. Those bytes go directly to `127.0.0.1`, are copied into the private
local project directory, and never pass through Vercel. For Boltz workflows,
the companion extracts the selected chain's modeled sequence from the receptor
and fills an editable sequence field; the researcher can override it when a
structure has unresolved residues or differs from the intended construct.

After pairing, the UI shows a Local scientific tools panel with live companion
capability checks. Vina has a one-click managed install whose official binary
and pinned SHA-256 are verified before execution. Boltz 2.2.1 also has a
one-click install into a private Python 3.12 environment on supported Windows,
Linux, and macOS systems. Its official wheel checksum is pinned. On Windows and
Linux, the installer detects NVIDIA hardware and selects a pinned official
PyTorch CUDA build compatible with the installed driver; it then verifies
`torch.cuda.is_available()` and records the GPU identity. Linux also receives
Boltz's optional optimized CUDA kernels, whose wheels are not published for
Windows. Boltz downloads model weights on its first prediction. PocketMiner has
one-click private-environment setup on supported Windows, Linux, and macOS
systems. Its exact pinned inference modules and checkpoint are already included,
verified against fixed upstream SHA-256 hashes, and never replaced by a port or
reimplementation. Other missing tools retain official setup links.
The companion download button is removed after a companion is detected.

For constrained Boltz, review the automatically extracted protein sequence and
explicit/imported/derived pocket residues, then select
`vina_to_constrained_boltz` or `vina_to_both_boltz`. For unconstrained Boltz,
select the corresponding workflow and enable `boltz.unconstrained`; its YAML
validator forbids pocket constraints. An explicit coordinate-matched PDB/mmCIF
template is preferred; otherwise the runner creates a coordinate-preserving PDB
from the registered PDBQT receptor and validates every atom before use.

## Static hosted UI with local companion

The most private deployment serves only `apps/web/` from Vercel. Users download
and open the companion; Vercel does not execute the scientific pipeline or
receive molecular data. The companion runs its own loopback control API, local
worker, and restricted scientific bridge:

```bash
drug-agent companion --origin https://your-app.vercel.app
```

The `--origin` value is a release/operator setting, not a user credential. It
locks that companion process to an exact website. When omitted, any HTTPS site
may make the first pairing request; after visible local approval, that exact
origin is saved locally and future requests from other origins are denied.

Build the current Windows companion archive and copy it into the static web
output with:

```powershell
powershell -File scripts/build_companion.ps1
vercel --prod
```

The build creates `dist/DrugDiscoveryAgent-Companion-windows-x64.zip` and copies
it to `apps/web/downloads/`, which is the default download link in
`apps/web/config.js`. Code signing and publication through a trusted release
channel are required before distributing it broadly.

## Optional remote control plane

The API under `apps/api/` stores account/machine/project/run/job IDs, sanitized
workflow settings, and aggregate events only. The runner initiates outbound
HTTPS polling:

```bash
drug-agent connect \
  --endpoint https://control.example/api \
  --machine-id machine_123 \
  --token '<machine-token>'
```

The legacy remote-control mode still accepts a machine credential on the CLI.
Normal companion users do not use that mode or enter either a bridge token or a
control-plane token. See [`docs/PRIVACY_MODEL.md`](docs/PRIVACY_MODEL.md).

## Tests

```bash
python -m pytest -q
```

Tests use the saved Vina, Boltz, mapping, coordinate, and interaction fixtures.
RDKit-dependent tests skip explicitly when RDKit is not installed; they do not
silently substitute approximate chemistry.

## Design documents

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/LEGACY_WORKFLOW.md`](docs/LEGACY_WORKFLOW.md)
- [`docs/SCIENTIFIC_INVARIANTS.md`](docs/SCIENTIFIC_INVARIANTS.md)
- [`docs/PRIVACY_MODEL.md`](docs/PRIVACY_MODEL.md)
- [`docs/MIGRATION_PLAN.md`](docs/MIGRATION_PLAN.md)
- [`docs/PIPELINE_SPEC.md`](docs/PIPELINE_SPEC.md)
- [`docs/POCKETMINER.md`](docs/POCKETMINER.md)
