"""Standalone process adapter for the official PocketMiner source checkout.

This file intentionally imports only the standard library until the configured
PocketMiner environment and source tree have been selected.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--receptor")
    parser.add_argument("--checkpoint")
    parser.add_argument("--output")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    source = Path(args.repository).resolve() / "src"
    if not (source / "xtal_predict.py").is_file():
        raise FileNotFoundError(f"official PocketMiner source is missing: {source}")
    sys.path.insert(0, str(source))
    if args.probe:
        import tensorflow
        import mdtraj
        print(json.dumps({
            "python": sys.version,
            "tensorflow": tensorflow.__version__,
            "mdtraj": importlib.metadata.version("mdtraj"),
        }))
        return 0
    if not all((args.receptor, args.checkpoint, args.output)):
        parser.error("--receptor, --checkpoint, and --output are required for inference")
    import numpy as np
    from models import MQAModel
    from xtal_predict import make_predictions

    model = MQAModel(
        node_features=(8, 50), edge_features=(1, 32), hidden_dim=(16, 100),
        num_layers=4, dropout=0.1,
    )
    prediction = make_predictions([str(Path(args.receptor).resolve())], model, str(Path(args.checkpoint).resolve()))
    values = np.asarray(prediction).reshape(-1)
    if not np.all(np.isfinite(values)) or np.any(values < 0) or np.any(values > 1):
        raise ValueError("official PocketMiner produced values outside the expected probability range [0, 1]")
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    np.save(target, values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
