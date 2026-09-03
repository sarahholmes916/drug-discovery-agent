Drug Discovery Agent Companion
==============================

1. Run DrugDiscoveryAgent-Companion.exe.
2. Leave its window open while using the Drug Discovery Agent website.
3. On the website, click Connect companion.
4. Approve the exact website address in the local confirmation page.

No pairing token needs to be copied or entered. The companion listens only on
127.0.0.1 and scientific files remain on this computer.

The companion includes local Meeko receptor preparation. In recommended mode,
the website asks how to handle water, heterogens, and alternate locations;
ambiguous structures stop for review. Experts can upload their own PDBQT.

After pairing, the website can install the pinned AutoDock Vina executable into
the companion's private tools directory. The file is downloaded from the
official release and verified before it is used. PocketMiner automatic setup is
available on supported Windows, Linux, and macOS computers. Its exact pinned
upstream inference code and checkpoint are included and integrity-checked;
setup installs only a private compatible scientific environment.
Boltz-2 can also be installed automatically into a private environment on
supported Windows, Linux, and macOS computers. Its model weights download on
the first prediction. On Windows and Linux, automatic setup detects NVIDIA
hardware, installs CUDA-enabled PyTorch, and verifies GPU access.

Run the executable with --origin https://your-site.example to lock a release to
one exact website origin. Repeat --origin to trust more than one website.
