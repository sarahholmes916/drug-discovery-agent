from pathlib import Path
import re
from rdkit import Chem


INPUT_SDF = Path("structures.sdf")
OUTPUT_DIR = Path("split_sdf_files")


def sanitize_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "_NO_NAME_"
    name = re.sub(r"[^\w.\-]+", "_", name)
    return name[:120]


def main():
    if not INPUT_SDF.exists():
        raise FileNotFoundError(f"Could not find input file: {INPUT_SDF}")

    OUTPUT_DIR.mkdir(exist_ok=True)

    supplier = Chem.SDMolSupplier(str(INPUT_SDF), removeHs=False)
    if supplier is None:
        raise ValueError(f"Could not open SDF file: {INPUT_SDF}")

    used_names = set()
    written = 0
    failed = 0

    for idx, mol in enumerate(supplier, start=1):
        if mol is None:
            failed += 1
            print(f"Skipping entry {idx}: RDKit could not read it")
            continue

        raw_name = mol.GetProp("_Name") if mol.HasProp("_Name") else ""
        base_name = sanitize_name(raw_name) if raw_name else f"structures_{idx}"
        name = base_name

        counter = 2
        while name in used_names:
            name = f"{base_name}_{counter}"
            counter += 1
        used_names.add(name)

        out_path = OUTPUT_DIR / f"{name}.sdf"

        writer = Chem.SDWriter(str(out_path))
        writer.write(mol)
        writer.close()

        written += 1

        if written % 100 == 0:
            print(f"Wrote {written} molecules...")

    print(f"\nDone.")
    print(f"Wrote {written} SDF files to: {OUTPUT_DIR.resolve()}")
    print(f"Failed entries: {failed}")


if __name__ == "__main__":
    main()