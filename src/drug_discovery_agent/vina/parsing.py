from __future__ import annotations

import re

from .models import VinaMode


MODE_ROW = re.compile(
    r"^\s*(\d+)\s+(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+"
    r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+"
    r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$"
)
SEED = re.compile(r"random seed:\s*([+-]?\d+)", re.IGNORECASE)


def parse_vina_stdout(stdout: str) -> tuple[float | None, int | None, list[VinaMode]]:
    seed_match = SEED.search(stdout)
    seed = int(seed_match.group(1)) if seed_match else None
    modes: list[VinaMode] = []
    for line in stdout.splitlines():
        match = MODE_ROW.match(line)
        if match:
            modes.append(
                VinaMode(
                    mode=int(match.group(1)),
                    affinity_kcal_mol=float(match.group(2)),
                    rmsd_lb=float(match.group(3)),
                    rmsd_ub=float(match.group(4)),
                )
            )
    best = modes[0].affinity_kcal_mol if modes else None
    return best, seed, modes

