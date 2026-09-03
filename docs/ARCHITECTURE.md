# Architecture

## Boundaries

```text
static hosted web -> browser-local WebLLM worker
       |
       +-----------> origin-approved loopback companion
                                      |       |
                                      |       +-> local SQLite control plane
                                      v
                            drug_discovery_agent
                                      |
        PocketMiner / RDKit / Meeko / Vina / Boltz-2 / PLIP
```

The Python package is the scientific engine. It imports neither hosted API nor
web code. `apps/runner` adapts local CLI, downloadable companion, localhost
bridge, and optional outbound control-plane transports to the package.
`apps/api` stores coordination metadata and runs locally in the default
companion deployment. `apps/web` is static and obtains orchestration state and
scientific artifacts from the automatically paired loopback companion. Its
Qwen3/WebLLM chat model runs in a browser worker and can modify only validated,
allowlisted controls; it cannot start jobs or access browser file-input bytes.

## Package responsibilities

| Area | Responsibility |
|---|---|
| `config` | Typed YAML configuration, separation of scientific/execution/control-plane settings, validation, sanitized cloud projection. |
| `project` | Local directory layout, opaque local references, atomic JSON state, item manifests, provenance, and hashes. |
| `execution` | Argument-array subprocess execution, streaming callbacks, cancellation, timeout, structured command records, and resource-aware limits. |
| `receptor` | PDBQT conversion validation, PDB/mmCIF coordinate parsing, pocket selection/import, and residue-to-sequence mapping. |
| `pocketminer` | Pinned official inference adapter/setup, score normalization, spatial clustering, ranking, box geometry, visualization, selection, and NS1 comparison. |
| `ligands` | SDF source abstraction, canonical/original IDs, legacy naming, RDKit preparation, explicit-H and modification records, Meeko preparation. |
| `vina` | Command construction, stdout/PDBQT parsing, item-level resume, QC, ranking, shortlist, pose reconstruction, distances, and legacy-compatible interaction logic. |
| `boltz` | Separate constrained/unconstrained document builders and validators, command construction, and model/affinity/confidence parsing. |
| `plip` | Per-compound/per-model native PLIP execution and structured XML parsing. |
| `comparison` | Protein correspondence, Kabsch alignment, ligand transform/RMSD, contact and interaction overlap, and explicit non-comparability. |
| `ranking` | Composable raw metrics and opt-in configured weighted policies. |
| `reporting` | Local JSON/CSV/HTML reports and an opt-in legacy-oriented XLSX appender; detailed contents never enter cloud progress messages. |

## Local project layout

The project root contains `project.yaml`, immutable/copied or referenced inputs,
stage artifact directories, and `state/`. State writes use a temporary sibling
and atomic replace. Manifest paths are project-relative artifact IDs. A separate
local reference map may point to researcher-selected source paths and is never
included in a cloud DTO.

```text
project/
  project.yaml
  inputs/{receptor,ligands}/
  receptor/  pocketminer/  ligands/  vina/
  boltz_constrained/  boltz_unconstrained/
  interactions/  comparison/  reports/
  state/{project.json,run.json,manifest.json,provenance.json,local_refs.json}
```

## Stages and workflows

The orchestrator exposes 24 executable nodes from `INGEST_PROJECT` through
`BUILD_REPORT`, including six PocketMiner/selection nodes and the two expanded
Boltz preparation/execution branches. Workflows are selections over a
dependency graph, not separate hard-coded pipelines. Constrained and
unconstrained branches can run together but write to different directories and
result namespaces.

`SHORTLIST_VINA` is the single post-docking fan-out gate. Vina runs before that
gate for every successfully prepared ligand, and `state/vina_ranking.json`
retains the complete scored population. The user-selected top 1–50 is written
to `state/vina_shortlist.json` by best affinity, mean pose affinity, or
heavy-atom-normalized ligand efficiency; only that subset is consumed by every
subsequent analysis and Boltz branch.

Each stage and item has an explicit state and an `input_hash`. The hash combines
content hashes of scientific inputs, the relevant configuration projection,
and implementation/tool identity. A prior success is reusable only when the
hash matches and declared outputs still exist. Failures retry by default;
cancelled and review items require explicit policy.

`AWAIT_POCKET_SELECTION` is an intentional resumable terminal state. A valid
local selection requeues the same hosted job using metadata only; its candidate,
residues, metrics, and box remain local. The selected-pocket hash propagates to
Vina and constrained Boltz, but not to unconstrained Boltz.

## Companion pairing contract

The website detects the loopback service without a credential. Connecting
creates a short-lived request and opens a local confirmation page that displays
the exact requesting origin. Approval issues a random session credential scoped
to that exact origin; JavaScript keeps it in session storage and never displays
it. The long-lived internal worker credential remains only in companion memory.
An unconfigured companion persists the first approved origin and rejects other
origins on later launches; release builds can supply an exact origin explicitly.

## Remote control plane contract

Cloud-bound objects contain opaque user/project/machine/run/job IDs,
non-sensitive capability flags, stage/state, counts, timestamps, and sanitized
configuration such as enabled workflow branches and worker limits. They exclude
names, structures, sequences, SMILES, detailed results, and local paths.
Transport is abstracted behind a runner client; HTTPS polling is the initial
implementation and secure WebSocket can replace it without changing science.

## Dependency and failure policy

Scientific libraries and tools are detected lazily. `doctor` reports each
capability independently. A missing optional tool disables dependent workflows
without breaking inspection, configuration, or other workflows. External jobs
share one executor, and item failures do not erase successful sibling results.
