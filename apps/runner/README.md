# Local runner

The runner executes science locally, persists run/item state, exposes an
origin/session-restricted localhost companion, and can optionally use outbound
HTTPS polling for a remote control plane. It never needs an inbound internet
port. Run
`drug-agent doctor` before a workflow and use `drug-agent init` to register
opaque local file references without putting paths in hosted project metadata.

For PocketMiner, use **Install automatically** in the paired website on
supported Windows, Linux, or macOS computers, or run
`drug-agent pocketminer-setup` once and then `drug-agent pocketminer-inspect`.
The exact pinned upstream inference modules and checkpoint are included in the
companion and integrity-checked; setup creates only their private compatible
dependency environment. Boltz-2 also has an
**Install automatically** action on supported Windows, Linux, and macOS
computers. It installs the pinned official package into a private environment;
on Windows and Linux it automatically installs CUDA-enabled PyTorch when an
NVIDIA GPU is detected and verifies GPU access before reporting success. The
first prediction downloads model weights. Normal users launch `drug-agent companion`;
the browser receives an invisible, expiring session only after the exact website
origin is approved locally. The older `drug-agent bridge` fixed-token command is
retained for integrations. Fixed PocketMiner routes expose scores, ranked
candidates, the colored receptor, canonical selection, and run resume only.

The bridge intentionally has no arbitrary command, arbitrary path, or directory
browsing endpoint. Its install routes accept only fixed tool identifiers and
download from pinned official locations; they cannot accept a URL or command
from the website.
