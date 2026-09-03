from __future__ import annotations

import importlib
import sys

from apps.runner.cli import main as cli_main


def main() -> int:
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
    raise SystemExit(main())
