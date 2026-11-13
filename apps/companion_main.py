from __future__ import annotations

import importlib
import sys
import json
import multiprocessing
from pathlib import Path

from apps.runner.cli import main as cli_main


def main() -> int:
    multiprocessing.freeze_support()
    if sys.argv[1:2] == ["--doctor"]:
        return cli_main(["doctor"])
    if sys.argv[1:2] == ["--self-check"]:
        from drug_discovery_agent.distribution import self_check
        report = json.dumps(self_check(), indent=2)
        if len(sys.argv) > 2:
            Path(sys.argv[2]).write_text(report + "\n", encoding="utf-8")
        else:
            print(report)
        return 0
    if sys.argv[1:2] == ["--internal-prepare-ligand"]:
        try:
            meeko_main = importlib.import_module("meeko.cli.mk_prepare_ligand").main
        except ImportError as exc:
            raise RuntimeError("the companion was built without Meeko ligand preparation") from exc
        sys.argv = ["mk_prepare_ligand.py", *sys.argv[2:]]
        result = meeko_main()
        return int(result or 0)
    if sys.argv[1:2] == ["--internal-prepare-receptor"]:
        try:
            from meeko.cli.mk_prepare_receptor import main as meeko_main
        except ImportError as exc:
            raise RuntimeError("the companion was built without Meeko receptor preparation") from exc
        sys.argv = ["mk_prepare_receptor.py", *sys.argv[2:]]
        result = meeko_main()
        return int(result or 0)
    return cli_main(["companion", *sys.argv[1:]])


if __name__ == "__main__":
    if sys.stdout is None or sys.stderr is None:
        from drug_discovery_agent.platform_support import data_home
        logs = data_home() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = (logs / "companion.log").open("a", encoding="utf-8", buffering=1)
    raise SystemExit(main())
