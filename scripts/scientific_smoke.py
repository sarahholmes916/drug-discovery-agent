"""Explicit native dependency installation and one small real PocketMiner test."""
import argparse
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root / "src")]
from apps.runner.tool_install import install_vina, install_plip, install_pocketminer, install_boltz
from drug_discovery_agent.config.models import PocketMinerRuntimeConfig
from drug_discovery_agent.pocketminer.runtime import inspect_installation

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--boltz-runtime", action="store_true")
args = parser.parse_args()
for installer in (install_vina, install_plip, install_pocketminer):
    print(installer(print), flush=True)
report = inspect_installation(PocketMinerRuntimeConfig())
if not report["available"]:
    raise RuntimeError("Managed PocketMiner runtime did not verify; refusing a skipped smoke test")
subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/regression/test_ns1_pocketminer.py"], check=True, cwd=root)
if args.boltz_runtime:
    print(install_boltz(print))
    print("Boltz import/CLI/tensor probe only; no structure prediction was executed.")
