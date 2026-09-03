from pathlib import Path
import subprocess
import sys

PREDICTIONS = Path("predictions")
OUTPUT = Path("plip_results_top10")

TOP10 = [
    "ns1_structures_3958",
    "ns1_UCM",
    "ns1_structures_639",
    "ns1_structures_11478",
    "ns1_structures_4966",
    "ns1_structures_12233",
    "ns1_KSA",
    "ns1_structures_12249",
    "ns1_J67",
    "ns1_structures_9161",
]

OUTPUT.mkdir(exist_ok=True)

# Check Open Babel
try:
    from openbabel import pybel

    if "inchikey" not in pybel.outformats:
        print("ERROR: Open Babel does not support InChIKey.")
        sys.exit(1)

except ImportError:
    print("ERROR: Open Babel Python bindings are not installed.")
    sys.exit(1)


successes = []
failures = []

# 10 compounds × 5 models = up to 50 PLIP analyses
for structure_id in TOP10:

    for model_num in range(5):

        pdb_file = (
            PREDICTIONS
            / structure_id
            / f"{structure_id}_model_{model_num}.pdb"
        )

        output_dir = (
            OUTPUT
            / structure_id
            / f"model_{model_num}"
        )

        output_dir.mkdir(parents=True, exist_ok=True)

        label = f"{structure_id} model_{model_num}"

        print("=" * 70)
        print(f"Running PLIP: {label}")
        print(f"Input:  {pdb_file}")
        print(f"Output: {output_dir}")

        if not pdb_file.exists():
            print("SKIPPED: file not found")
            failures.append((label, "file not found"))
            continue

        command = [
            "plip",
            "-f", str(pdb_file),
            "-x",
            "-t",
            "-o", str(output_dir),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            print("SUCCESS")
            successes.append(label)

        else:
            print("FAILED")
            print(result.stderr)
            failures.append((label, result.stderr))


print("\n" + "=" * 70)
print("FINISHED")
print("=" * 70)

print(f"Successful: {len(successes)}")
print(f"Failed:     {len(failures)}")