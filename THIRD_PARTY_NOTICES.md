# Third-party notices

## PocketMiner

This distribution includes the inference code and trained PocketMiner checkpoint
from [`Mickdub/gvp`](https://github.com/Mickdub/gvp/tree/pocket_pred), branch
`pocket_pred`, pinned at commit
`187062df3c94127e991669768009141a08fd5d8b`.

PocketMiner is distributed under the MIT License. The complete, unmodified
upstream license—including the notices for the PocketMiner authors, the GVP
authors, and the portions adapted from Ingraham et al.—is included at
`src/drug_discovery_agent/_vendor/pocketminer/LICENSE` and must remain with any
redistribution containing this component.

Drug Discovery Agent adds an argument-driven inference adapter, integrity
verification, managed dependency setup, provenance capture, and Windows
compatibility around the unmodified pinned inference modules and checkpoint.
The upstream authors do not endorse this integration.

## Companion runtime

Native companion archives include a Python interpreter and the pinned packages
listed in `packaging/requirements-build.txt`. `PYTHON_LICENSE.txt` preserves the
interpreter's redistribution notice. The build copies wheel-provided licenses
and native-library notices into `dependency-licenses/` and records exact resolved
versions in `build-manifest.json`. Preserve those notices with the archive.
PyInstaller's bootloader is distributed under its GPL license with the upstream
exception for generated bundles; see the included PyInstaller notice.

Vina, Boltz, TensorFlow, MDTraj, PLIP and Open Babel are independent dependencies
installed locally from upstream distributions, not copied from a developer's
machine into companion releases. Their original licenses remain applicable.
No third-party affiliation or endorsement is implied.
