#!/usr/bin/env python3
"""Run a directory of Boltz-2 inputs that contain no pocket constraints.

The default execution knobs mirror the later constrained run so an agent can
compare constrained and unconstrained modes while changing the binding-site
constraint rather than silently changing sampling settings too.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--recycling-steps", type=int, default=3)
    parser.add_argument("--sampling-steps", type=int, default=200)
    parser.add_argument("--diffusion-samples", type=int, default=5)
    parser.add_argument("--output-format", default="pdb")
    parser.add_argument("--accelerator", default="gpu")
    parser.add_argument("--devices", default="1")
    parser.add_argument("--no-potentials", action="store_true")
    parser.add_argument("--no-msa-server", action="store_true")
    parser.add_argument("--no-override", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cmd = [
        "boltz",
        "predict",
        str(args.inputs),
        "--out_dir",
        str(args.out_dir),
    ]
    if not args.no_potentials:
        cmd.append("--use_potentials")
    cmd.extend(
        [
            "--recycling_steps",
            str(args.recycling_steps),
            "--sampling_steps",
            str(args.sampling_steps),
            "--diffusion_samples",
            str(args.diffusion_samples),
            "--output_format",
            args.output_format,
            "--accelerator",
            args.accelerator,
            "--devices",
            str(args.devices),
        ]
    )
    if not args.no_override:
        cmd.append("--override")
    if not args.no_msa_server:
        cmd.append("--use_msa_server")

    print("Command:")
    print(" ".join(cmd))
    if not args.dry_run:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
