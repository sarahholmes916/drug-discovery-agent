Drug Discovery Agent Companion
==============================

No Python installation or repository checkout is required.

Windows x64: Extract the entire ZIP. Open DrugDiscoveryAgent-Companion.exe and
keep _internal beside it. Leave the console open. Ctrl+C shuts it down.
macOS 15+ Apple Silicon / Intel: Choose the matching processor build. Extract
the ZIP, move the app to Applications and open it. Use a Developer ID signed,
notarized release. Do not disable Gatekeeper. To stop an idle companion, use
Activity Monitor > Quit, or run the executable in Terminal and use Ctrl+C.
Linux x64: Extract the tarball and run ./DrugDiscoveryAgent-Companion. The build
targets Ubuntu 22.04+ / glibc 2.35+. Preserve accompanying files and symlinks.

Verify the archive's SHA-256 against the adjacent release checksum before use.
Unsigned Windows builds can show trust warnings; verify origin and publisher.
Mac/Linux support is implemented but native validation must be checked in the
release's workflow results; do not infer it from a Windows test.

Open the Drug Discovery Agent website, click Connect companion, and approve
that exact website on the local confirmation page. No token is copied/typed.
The server listens only on 127.0.0.1:8765. If connection fails, check the running
process, port conflict, browser local-network permission, and approved origin.

Included: Python, RDKit, Meeko, Gemmi, NumPy/SciPy, reporting/server libraries,
and the pinned PocketMiner inference files, checkpoint, manifest and license.
After pairing, Install automatically manages Vina, PocketMiner dependencies,
PLIP/Open Babel, and supported Boltz environments. Failures remain visible and
retryable. Never delete project state to repair a dependency.

Boltz 2.2.1: NVIDIA CUDA is optional on Windows/Linux. No MPS support. On Apple
Silicon, explicitly choose CPU for new projects (slow, predictions unverified).
Intel Mac automatic Boltz installation is unavailable because pinned PyTorch
2.7.1 has no official macOS x64 wheel. Existing projects keep their settings.

Molecular uploads and detailed results go directly to the local companion,
never Vercel. Existing exception: Boltz's default public MSA service receives
the protein sequence. Fully offline use needs compatible local MSAs and explicit
use_msa_server: false; this release preserves the validated defaults.

Data: Windows ~/DrugDiscoveryAgent; fresh Mac ~/Library/Application Support/
DrugDiscoveryAgent; fresh Linux $XDG_DATA_HOME/DrugDiscoveryAgent (default
~/.local/share/DrugDiscoveryAgent). Existing data/tool directories are reused.
Override with DRUG_AGENT_HOME / DRUG_AGENT_TOOLS_HOME. Mac background logs are
in the data directory's logs/companion.log. Setup command logs remain local.

Run the executable with --doctor for dependency diagnostics, --self-check for
bundled-resource checks, or --origin https://your-site.example for an origin lock.
On Mac the executable is inside the app at Contents/MacOS/DrugDiscoveryAgent-Companion.

Release guide: docs/COMPANION_RELEASES.md in the source repository.
Preserve LICENSE, THIRD_PARTY_NOTICES.md, dependency-licenses and
POCKETMINER_LICENSE.txt when redistributing. No signing credentials are bundled.
