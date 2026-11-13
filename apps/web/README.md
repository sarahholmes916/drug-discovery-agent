# Hosted web control plane

Serve this directory as a static site. `config.js` selects the loopback
companion address and exact GitHub release repository/tag. Published assets are
verified before downloads are enabled, and users explicitly select the processor. The page detects the companion,
starts a one-time local approval, and stores the resulting origin-scoped session
credential in browser session storage without displaying it to the user.

After pairing, both orchestration and scientific-data calls go directly to the
local companion. Chat uses the open-source Qwen3 1.7B model through WebLLM in a
dedicated browser worker, so neither an API key nor server-side inference is
needed. The first chat message downloads the model artifacts and the browser
caches them for later visits; the selected quantization requires about 2 GB of
GPU memory. Browsers without usable WebGPU automatically retain the original
guided parser as a fallback.

Once paired, the Local scientific tools panel reads the companion's sanitized
capability report and shows availability for Vina, RDKit, Meeko, PocketMiner,
Boltz-2, and PLIP. Vina can be installed directly through the companion; its
platform binary is fetched from the pinned official release, checked against a
pinned SHA-256, version-probed, and immediately activated. Boltz 2.2.1 receives
the same one-click treatment in a private Python 3.12 environment on supported
Windows, Linux, and Apple Silicon macOS systems; Intel Mac automatic setup is
unavailable. Its official wheel checksum is pinned. On
Windows and Linux, the installer detects NVIDIA hardware and installs a pinned
official PyTorch CUDA build selected for the driver's supported CUDA runtime.
It verifies GPU access when NVIDIA hardware is detected, or CPU tensor execution
otherwise. Full CPU prediction on macOS is unverified; the pinned CLI has no MPS
support. CPU must be chosen explicitly for new projects. Linux also receives
Boltz's optimized CUDA-kernel extra; those kernel wheels are not published for
Windows, but Windows predictions still use the NVIDIA GPU through PyTorch.
Boltz model weights download on first use. PocketMiner receives one-click setup
on supported Windows, Linux, and macOS computers. Its exact pinned upstream
inference files and checkpoint are already inside the companion and checked
against fixed SHA-256 hashes; setup creates a private compatible scientific
environment and does not download or rewrite PocketMiner source. Other missing
entries retain their official setup documentation. The companion download action is hidden whenever a running
companion has already been detected.

The model receives the user's chat text and a summary of visible workflow
settings, never receptor, ligand, sequence, result, or local-path data. It can
answer questions and propose changes only to an explicit allowlist of controls;
the page validates ranges and enum values before applying them, and the
companion performs authoritative project validation before execution. The page
also provides progress and a 3Dmol.js PocketMiner selection workbench. Scores,
the colored receptor, candidate metrics, and confirmation never pass through
the hosted origin.

Every successfully prepared ligand is docked with Vina. The guided workflow
then applies one explicit downstream gate of 1–50 ligands (50 is the recommended
maximum) ranked by best Vina affinity, mean affinity across returned poses, or
heavy-atom-normalized ligand efficiency. The full Vina ranking remains in the
report, while only the selected subset proceeds to interaction analysis, Boltz,
PLIP, and pose comparison.

The guided setup uses ordinary browser file pickers, including a ligand-folder
picker that collects SDF files from nested folders, but submits the selected
receptor/SDF bytes only to `http://127.0.0.1:8765`. Recommended mode creates the
receptor PDBQT locally with Meeko and stops for review on heterogens or alternate
locations; experts can instead upload a prepared PDBQT. The companion streams
inputs into a temporary local project and atomically registers it after all
extensions, sizes, configuration, and required fields validate.

The Recent local projects panel reloads metadata from that companion registry
after every connection. It can reopen a project, resume an eligible saved
run, start a fresh run with the stored inputs, or download registered result
artifacts and provenance as a ZIP. Local filesystem paths and raw molecular
inputs are never returned by the project-list endpoint.

See [the release guide](../../docs/COMPANION_RELEASES.md) for native build status,
local data paths, private-repository download limits, and signing requirements.
