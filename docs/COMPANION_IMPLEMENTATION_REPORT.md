# Companion compatibility implementation report

Implemented in the existing working tree. No commit, push, CI dispatch, website
deployment or GitHub Release publication was performed. The source repository
remains private. `legacy/` is unchanged.

## Changes

- Shared native PyInstaller specification/builder for Windows x64, macOS ARM64,
  macOS x64 and Linux x64, with pinned important dependencies, version inventory,
  original licenses, resource integrity checks and SHA-256 sidecars.
- Separate native build, explicit release, and optional scientific smoke workflows.
  Release validation requires every target and keeps failed uploads in a draft.
  Stable Mac releases require signing/notarization; existing releases are rejected.
- Explicit processor selection and verified versioned GitHub asset links in the
  website, accurate unavailable states, installation steps, and detection-based
  hiding of the download panel. Origin-scoped local approval remains intact.
- Mac/Linux user data directories with precedence for legacy locations and
  environment overrides. Explicit CPU Boltz selection, truthful CPU/CUDA
  capability reports and Intel Mac installation limits. MPS is unsupported by
  the pinned upstream CLI; no automatic GPU-to-CPU configuration rewrite occurs.
- Standalone PocketMiner adapter source now included in the bundle. Setup command
  records remain local. Graceful Windows signal handling permits clean restart.
- Documented SDF bug fix: malformed short records omitted by RDKit's whole-file
  iterator are retained as failures. Regression tests compare valid-record
  molecule blocks, canonical SMILES and IDs against the previous reader.

## Artifacts produced locally

`dist/windows-x64/` contains:

- `DrugDiscoveryAgent-Companion-windows-x64.zip` ? 108,146,109 bytes, unsigned
  development build of version 0.1.1 from the modified working tree.
- `DrugDiscoveryAgent-Companion-windows-x64.zip.sha256`
- `build-manifest.json`
- `self-check.json`

SHA-256:

```text
25d97cd5df16fe4164693f073fd889e4f5f6a51ebc910868704407ddaf31a9fa
```

The 1,475 archive entries were checked for required licenses and excluded
workspace/private-data directories and credential/database extensions. This
allowlist check is not a claim of a comprehensive third-party security audit.
The production release workflow refuses artifacts marked `source_dirty: true`.
Mac/Linux archives were not built here, and no assets were published.

## Tests executed

| Check | Result | Scope |
| --- | --- | --- |
| Initial existing suite, system Python | 102 passed, 7 skipped | RDKit/Gemmi absent from this Python environment |
| Final suite, isolated pinned build environment | **132 passed**, no skips | Windows; one Starlette/AnyIO deprecation warning |
| `node --test tests/web/*.test.cjs` | **4 passed** | Platform selection, exact published URLs, both Mac choices, private/unavailable release behavior; DOM adapter tests, not a real browser session |
| Windows native build | **exit 0** | Python 3.12.10, PyInstaller 6.16.0; frozen imports and all pinned PocketMiner hashes verified |
| Extracted archive tests | **2 passed** | Real HTTP startup, origin rejection, auth rejection, graceful shutdown/restart, old registry retention, paths with spaces, real Meeko ligand preparation, receptor CLI startup |
| Extracted `--doctor` | **exit 0** | Bundled chemistry libraries, installed Vina and external PocketMiner probe succeeded; Boltz/PLIP managed identity reports also read cached installation metadata |
| Single-fixture real PocketMiner regression | **passed within the full suite** | Existing managed Windows runtime; no full benchmark or large screen |
| SDF valid-record regression | **passed** | Same molecule blocks, canonical SMILES and IDs as previous parser for supplied valid fixtures |
| Pairing/approval, project import, privacy, resumability/cancellation suite | **passed within the full suite** | Existing ASGI/integration tests; these do not imply a browser/Gatekeeper test |
| Workflow YAML parse, inline JavaScript syntax, `git diff --check` | **passed** | Structural/syntax checks only; GitHub workflows have not executed |

Exact main commands used:

```powershell
build/companion-venv/Scripts/python.exe -m pytest -q
node --test tests/web/*.test.cjs
build/companion-venv/Scripts/python.exe scripts/build_companion.py --target windows-x64
$env:COMPANION_EXECUTABLE = (& build/companion-venv/Scripts/python.exe scripts/prepare_companion_smoke.py --target windows-x64 | Select-Object -Last 1)
build/companion-venv/Scripts/python.exe -m pytest -q tests/integration/test_companion_process.py
& $env:COMPANION_EXECUTABLE --doctor
```

Scientific installer tests for Mac platforms use mocked commands. They are not
successful native installations or predictions. There was no Vina docking,
Boltz prediction or native PLIP interaction run in this session; existing output
regressions and capability checks do not establish those executions.

## Remaining release blockers

1. Run native macOS ARM64/x64 and Linux workflows, then validate signed Mac
   launch/pairing on actual user machines. No Mac/Linux execution occurred here.
2. Supply the six Apple certificate/notarization secrets listed in
   [COMPANION_RELEASES.md](COMPANION_RELEASES.md). Code signing, notarization,
   Gatekeeper and Windows Authenticode trust have not been tested here.
3. Authorize a public artifact distribution location or authenticated distribution
   service. The private source repository's release metadata/assets are unavailable
   to anonymous website visitors. No visibility change or embedded token is used.
4. Full Boltz CPU predictions on Apple Silicon remain unverified; Intel Mac
   automatic Boltz setup is intentionally unavailable. No MPS path is claimed.

Scientific algorithms, coordinate policies, pocket parameters, ranking defaults
and saved project formats are unchanged apart from the documented malformed-SDF
failure accounting fix. CPU execution is an explicit execution setting.

The existing public MSA-service default is preserved and now documented as an
exception to offline execution: protein sequences can go to the upstream MSA
service, never to Vercel. Fully offline use requires explicit compatible local
MSA inputs/configuration.

## Publishing the next release

After review and committing these files, with GitHub CLI installed/authenticated
and the Apple secrets configured:

```bash
git push origin HEAD:main
git tag -a v0.1.1 -m "Companion 0.1.1"
git push origin v0.1.1
gh workflow run companion-release.yml --repo sarahholmes916/drug-discovery-agent --ref main -f tag=v0.1.1 -f prerelease=true -f sign_macos=true
gh run list --repo sarahholmes916/drug-discovery-agent --workflow companion-release.yml --limit 5
gh run watch RUN_ID --repo sarahholmes916/drug-discovery-agent --exit-status
```

Use a fresh tag if v0.1.1 already exists. Update the website's configured tag only
after all assets have been published. The complete release/signing/installation
instructions are in [COMPANION_RELEASES.md](COMPANION_RELEASES.md).

## Files added or modified

- `.github/workflows/companion-build.yml`
- `.github/workflows/companion-release.yml`
- `.github/workflows/companion-scientific-smoke.yml`
- `.vercelignore`
- `README.md`
- `THIRD_PARTY_NOTICES.md`
- `apps/companion_main.py`
- `apps/local_ui.py`
- `apps/runner/companion.py`
- `apps/runner/doctor.py`
- `apps/runner/project_uploads.py`
- `apps/runner/registry.py`
- `apps/runner/tool_install.py`
- `apps/runner/tool_paths.py`
- `apps/web/README.md`
- `apps/web/companion-downloads.js`
- `apps/web/config.js`
- `apps/web/downloads/README.md`
- `apps/web/index.html`
- `docs/ARCHITECTURE.md`
- `docs/COMPANION_IMPLEMENTATION_REPORT.md`
- `docs/COMPANION_RELEASES.md`
- `docs/POCKETMINER.md`
- `docs/PRIVACY_MODEL.md`
- `packaging/COMPANION_README.txt`
- `packaging/companion.spec`
- `packaging/macos-entitlements.plist`
- `packaging/requirements-build.txt`
- `pyproject.toml`
- `scripts/build_companion.ps1`
- `scripts/build_companion.py`
- `scripts/macos_signing.py`
- `scripts/prepare_companion_smoke.py`
- `scripts/publish_companion.py`
- `scripts/scientific_smoke.py`
- `src/drug_discovery_agent/__init__.py`
- `src/drug_discovery_agent/boltz/runner.py`
- `src/drug_discovery_agent/distribution.py`
- `src/drug_discovery_agent/execution/commands.py`
- `src/drug_discovery_agent/ligands/ingest.py`
- `src/drug_discovery_agent/platform_support.py`
- `src/drug_discovery_agent/pocketminer/runtime.py`
- `tests/integration/test_companion.py`
- `tests/integration/test_companion_process.py`
- `tests/integration/test_ligands.py`
- `tests/integration/test_local_ui.py`
- `tests/unit/test_distribution.py`
- `tests/unit/test_platform_support.py`
- `tests/unit/test_pocketminer_runtime.py`
- `tests/unit/test_release_publication.py`
- `tests/unit/test_tool_install.py`
- `tests/web/companion-downloads.test.cjs`
