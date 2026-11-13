# Companion installation and releases

## Current status

The release recipe targets the following native hosts. This document distinguishes
implemented build support from installations actually exercised on hardware.

| Archive target | Build runner | Minimum advertised system | Verification in this change |
| --- | --- | --- | --- |
| windows-x64 | windows-2022, x64 Python | Windows 10/11 x64 | Built locally; extracted executable, native imports, localhost/auth rejection, graceful shutdown and restart tested |
| macos-arm64 | macos-15, ARM64 Python | macOS 15+, Apple Silicon | Implemented; no Mac build or installation executed here |
| macos-x64 | macos-15-intel, x64 Python | macOS 15+, Intel | Implemented; no Mac build or installation executed here |
| linux-x64 | ubuntu-22.04, x64 Python | Ubuntu 22.04+ / compatible glibc 2.35+ | Implemented; no Linux build or installation executed here |

No universal Mac binary or Rosetta fallback is claimed. The builder rejects a
target that differs from the executing Python architecture. PyInstaller also
checks native extension architecture during Mac collection. Native import and
resource checks run again in the built executable and in the extracted archive.
Older operating systems, ARM Windows/Linux, and musl Linux are unverified.

**Distribution blocker:** the source repository is private (verified during this
change). Anonymous visitors cannot fetch its GitHub Release assets or metadata.
The website therefore reports unavailable downloads, including when access is
restricted. Repository members can download through authenticated GitHub. A
separately authorized public artifact repository or authenticated distribution
service is needed for general public installation. Do not change source repository
visibility or put a GitHub credential in the static website.

## Installation without Python

1. Visit the website and choose the operating system and processor explicitly.
   On Mac, Apple menu → About This Mac shows either an Apple chip or an Intel
   processor. Browser user agents cannot reliably distinguish them.
2. Download a published archive and its adjacent `.sha256` file from the same
   versioned GitHub Release. Compare the digest before opening it:

   ```powershell
   Get-FileHash .\DrugDiscoveryAgent-Companion-windows-x64.zip -Algorithm SHA256
   ```

   ```bash
   shasum -a 256 -c DrugDiscoveryAgent-Companion-macos-arm64.zip.sha256
   # On Linux: sha256sum -c DrugDiscoveryAgent-Companion-linux-x64.tar.gz.sha256
   ```

3. Windows: extract the **entire** ZIP and open `DrugDiscoveryAgent-Companion.exe`.
   Keep `_internal` beside it and leave its console open. Windows may show a trust
   warning for unsigned builds; verify the release origin and publisher. This
   recipe does not currently provide Authenticode signing.
4. Mac: extract the ZIP, move `DrugDiscoveryAgent-Companion.app` to Applications,
   and open it. Use a Developer ID signed, notarized release. Development builds
   may be blocked by Gatekeeper; do not remove quarantine or disable Gatekeeper.
   The companion is a background app; close it with Activity Monitor's **Quit**
   when no job is running, or launch its executable in Terminal and use Ctrl+C.
5. Linux: extract the tarball and run `./DrugDiscoveryAgent-Companion` from its
   extracted directory. Keep its accompanying files and executable permissions.
6. Click **Connect companion**, review the exact website origin on the local
   approval page, and approve it. No token entry is required. The website hides
   the download panel when the companion is detected.

The companion binds only to `127.0.0.1:8765`. Approval is scoped to the exact
website origin; the first approved origin persists across launches. Sessions
expire and must be approved again. `--origin https://your-site.example` can lock
the companion to a particular deployment. For a command-line diagnostic use
`DrugDiscoveryAgent-Companion --doctor` (add `.exe` on Windows; on Mac use the
executable under `DrugDiscoveryAgent-Companion.app/Contents/MacOS/`).

## Local data and dependencies

Fresh macOS installations use
`~/Library/Application Support/DrugDiscoveryAgent/`, with `projects/`, local
SQLite/registry state, `tools/`, and background-app logs in `logs/companion.log`.
Fresh Linux installations use `$XDG_DATA_HOME/DrugDiscoveryAgent`, defaulting to
`~/.local/share/DrugDiscoveryAgent`. Windows retains `~/DrugDiscoveryAgent` for
projects and `~/.drug-agent/tools` for dependencies.

An existing `~/DrugDiscoveryAgent` or `~/.drug-agent/tools` directory takes
precedence on every platform; nothing is moved or rewritten automatically.
`DRUG_AGENT_HOME` and `DRUG_AGENT_TOOLS_HOME` override these roots. PocketMiner
also retains its existing explicit configuration/environment overrides. Original
registry entries continue to point to the same project directories. Temporary
uploads remain in the local project area; OS temporary directories hold ordinary
temporary files. Boltz retains its upstream `~/.boltz` model cache.

Python, NumPy, SciPy, RDKit, Gemmi, Meeko, OpenPyXL and the local web server are
included. PocketMiner's pinned upstream inference files, checkpoint, manifest,
license, and the external adapter source are included. These optional tools are
installed only after **Install automatically** is selected:

| Tool | Installation / hardware policy |
| --- | --- |
| Vina 1.2.7 | Official architecture-specific binary, pinned SHA-256, version probe; CPU |
| PocketMiner | Private Python 3.10 environment, TensorFlow 2.10 and MDTraj 1.9.7; CPU inference, no GPU required |
| PLIP 3.0.1 | Private environment with Open Babel 3.2.1; InChIKey and CLI probes |
| Boltz 2.2.1 | Private Python 3.12 environment; pinned official wheel and PyTorch 2.7.1; optional NVIDIA CUDA on Windows/Linux |

The native package indexes list TensorFlow 2.10.0, MDTraj 1.9.7, and Open Babel
3.2.1 for both `osx-arm64` and `osx-64`. RDKit 2025.3.6 has CPython 3.12 wheels
for both Mac architectures. Availability of packages is **not** a successful
environment solve, installation, or inference test. The manual native scientific
smoke workflow installs these dependencies and runs one existing PocketMiner
fixture regression. It does not run the large screening benchmarks.

CPU-only Boltz installations that pass tensor/CLI probes are reported as CPU
runtimes, rather than broken CUDA installations. For a new project choose CPU
explicitly in the tools panel, or set `boltz.accelerator: cpu` in an existing
project's YAML. Saved projects and the GPU default are not silently changed.
CPU execution disables CUDA kernels. Mac GPU/MPS requests fail early with an
actionable message; the pinned Boltz 2.2.1 CLI accepts `gpu`, `cpu`, and `tpu`,
not `mps`. Full CPU prediction/affinity execution on Mac remains unverified.

Automatic Boltz installation on Intel Mac is disabled: official macOS x64
PyTorch wheels stop at 2.2.x, while this installer pins 2.7.1. The Boltz package's
broader `torch>=2.2` declaration alone does not validate the older runtime for
this workflow. An independently validated external CPU environment is required.
NVIDIA CUDA availability is never inferred on macOS. There is no validated
universal RAM/VRAM minimum: model/input sizes determine memory needs, and CPU
Boltz can be impractically slow. The companion itself does not require a GPU.

Failed setup reports a local diagnostic and can be retried. Installed
environments and successful project artifacts remain in place. Private setup
command records are stored under `tools/setup-commands/` and
`tools/pocketminer/setup-commands/`; scientific command provenance stays inside
each project. Do not delete project/state directories to repair a tool.

Vercel receives neither molecular files nor detailed results. **Existing privacy
exception:** the validated Boltz default `use_msa_server: true` sends protein
sequences to the upstream public MSA service, as disclosed in the UI. This task
does not change that scientific default. A fully offline Boltz run requires
researcher-supplied compatible MSA inputs and `use_msa_server: false`; do not
interpret local companion execution as an offline MSA guarantee.

## Build and publish

Use Python **3.12.10 of the target architecture** on the target OS:

```bash
python -m venv build/companion-venv
# Activate the venv (Windows: build\companion-venv\Scripts\Activate.ps1)
source build/companion-venv/bin/activate
python -m pip install -r packaging/requirements-build.txt
python -m pytest -q
node --test tests/web/*.test.cjs
python scripts/build_companion.py --target macos-arm64
# Other native hosts: macos-x64, windows-x64, linux-x64
python scripts/prepare_companion_smoke.py --target macos-arm64
# Set COMPANION_EXECUTABLE to the printed extracted executable path, then:
python -m pytest -q tests/integration/test_companion_process.py
```

The PowerShell wrapper remains available: `powershell -File
scripts/build_companion.ps1 -PythonExecutable build/companion-venv/Scripts/python.exe
-SkipInstall`. Artifacts are under `dist/<target>/`. Important build/runtime
dependencies are pinned; all resolved versions, source commit/dirty status,
platform and PocketMiner hashes are recorded in `build-manifest.json`. This is a
repeatable native build recipe, not a claim of byte-identical archives across
changing OS runner images or unpinned transitive dependencies.

The build workflow tests before packaging, then verifies each extracted archive
and launches its executable. It uploads archives, per-archive SHA-256 files,
manifests, and self-check reports. The separate manual scientific smoke workflow
is optional and large downloads may take time; it exercises Vina version, PLIP
import/InChIKey/CLI and one real PocketMiner prediction. Its Boltz option is only
an installation/tensor/CLI probe, not a structure prediction.

The release workflow is manual. All four builds must succeed before any draft
is created. It validates names, target architecture, versions, source identity,
checksums, and signing status, uploads to a draft, verifies the complete asset
inventory, then publishes. Any upload failure leaves a draft, never a partially
published release. Existing releases/drafts are rejected, no tag is moved, and
the workflow never automatically changes GitHub's latest stable release.

After reviewing and committing this change, these are the commands for the next
release (GitHub CLI must be installed/authenticated):

```bash
git push origin HEAD:main
git tag -a v0.1.1 -m "Companion 0.1.1"
git push origin v0.1.1
gh workflow run companion-release.yml --repo sarahholmes916/drug-discovery-agent --ref main -f tag=v0.1.1 -f prerelease=true -f sign_macos=true
gh run list --repo sarahholmes916/drug-discovery-agent --workflow companion-release.yml --limit 5
gh run watch RUN_ID --repo sarahholmes916/drug-discovery-agent --exit-status
```

Use a fresh version/tag if one already exists. Configure environment
`companion-release` with the desired human reviewers before dispatch. After
reviewing the prerelease and native installations, a later stable release uses
`-f prerelease=false`; it requires Mac signing. For CI-only unsigned evaluation,
`-f prerelease=true -f sign_macos=false` is allowed and clearly labeled; it is not
a Gatekeeper-installable Mac release. No workflow was dispatched or release
published from this working session.

Only after publication, change `apps/web/config.js` to the available tag and
deploy the static website normally. Downloads query exact release metadata and
show only uploaded assets with the expected names and versioned URLs. A 404,
private repository, rate limit, network failure, missing architecture or draft
produces an unavailable state, not a guessed URL or incompatible fallback.

## Signing, integrity, and redistribution

For both Mac build jobs, configure these repository/environment secrets:

- `MACOS_CERTIFICATE_P12_BASE64`: Developer ID Application certificate **and
  private key**, exported as a password-protected PKCS#12 file and base64 encoded.
- `MACOS_CERTIFICATE_PASSWORD`: its password.
- `MACOS_SIGNING_IDENTITY`: exact `Developer ID Application: … (TEAMID)` identity.
- `APPLE_API_KEY_BASE64`: base64 encoded App Store Connect notarization API `.p8` key.
- `APPLE_API_KEY_ID` and `APPLE_API_ISSUER`: that key's ID and issuer UUID.

The workflow imports the certificate into a temporary keychain, signs via
PyInstaller, submits to `notarytool --wait`, staples and validates the ticket,
checks Gatekeeper assessment, and regenerates the archive/checksum. Temporary
credentials are removed in an `always()` cleanup step. No signing/notarization
credentials were available or used here. Apple Developer membership and accepted
agreements are prerequisites. Windows Authenticode requires a separately managed
trusted code-signing certificate/service; do not embed private keys in archives.

The staging allowlist contains only the native bundle, project license/notices,
PocketMiner license, build manifest and dependency licenses. It never copies
`legacy/`, project inputs/results, home directories, credentials, `.git` or the
whole workspace. Vina, Boltz, TensorFlow and PLIP are independent downloads,
not copied from this computer into the companion. Preserve their upstream
licenses. PocketMiner's included code and checkpoint are covered by the included
upstream MIT license/manifest; the upstream authors do not endorse this product.
The archive includes Python/wheel license files and native-library notices where
provided by those distributions; release operators should review the inventory
when updating dependency pins.

## Troubleshooting and verification scope

- Cannot connect: launch the companion, check its console/local log, ensure port
  8765 is free and permit the browser's local-network request. HTTP 403 usually
  means the origin differs from an approved/configured origin; do not disable
  origin checks. Start explicitly with the intended `--origin` if needed.
- Wrong architecture / OS too old: choose the correct native build. Do not rely
  on browser processor inference or rename an incompatible archive.
- Missing dependencies: install the specific optional tool; other capabilities
  remain available. Re-run diagnostics and inspect local setup-command logs.
- Mac won't open: obtain the signed/notarized release and verify its digest.
  Quarantine-removal and Gatekeeper-bypass commands are intentionally not provided.
- Existing projects: keep their registry and state. The path policy reuses old
  locations; scientific YAML/output formats and coordinate/selection policies
  are unchanged. Cross-computer project relocation remains a separate operation.

One documented bug fix accompanies packaging: the whole-file RDKit SDF iterator
could omit a short malformed trailing record. Record-by-record ingestion retains
that failure and preserves neighboring record numbers, using the same RDKit
chemistry parser. Regression tests cover malformed trailing/middle records;
valid record chemistry, IDs and output formatting are preserved.

Primary references checked for platform policy:
[GitHub native runner labels](https://github.com/actions/runner-images#available-images),
[Boltz 2.2.1 CLI](https://github.com/jwohlwend/boltz/blob/v2.2.1/src/boltz/main.py),
[Boltz dependency requirements](https://github.com/jwohlwend/boltz/blob/v2.2.1/pyproject.toml),
[PyTorch Intel Mac support](https://pytorch.org/blog/pytorch2-2/),
[TensorFlow packages](https://api.anaconda.org/release/conda-forge/tensorflow/2.10.0),
[MDTraj packages](https://api.anaconda.org/release/conda-forge/mdtraj/1.9.7),
[Open Babel packages](https://api.anaconda.org/release/conda-forge/openbabel/3.2.1),
[RDKit wheels](https://pypi.org/pypi/rdkit/2025.3.6/json),
[PyInstaller native builds](https://pyinstaller.org/en/v6.16.0/feature-notes.html#macos-multi-arch-support),
[Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
