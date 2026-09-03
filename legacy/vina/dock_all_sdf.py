from pathlib import Path
from datetime import datetime
import subprocess
import re
import pandas as pd
from rdkit import Chem
from rdkit.Chem import AllChem

DRUGS_DIR = Path("Drugs")
RECEPTOR_PDBQT = Path("ns1_ed_receptor.pdbqt")
RESULTS_XLSX = Path("docking_results.xlsx")

CENTER = (26.448, 12.021, 27.940)
SIZE = (28, 28, 28)

# Stats for large first-pass screen
EXHAUSTIVENESS = 8
NUM_MODES = 3

FORCE_REDOCK = False
SAVE_EVERY = 25  # save progress every N ligands

SDF_DIR = DRUGS_DIR / "prepared_sdf"
PDBQT_DIR = DRUGS_DIR / "prepared_pdbqt"
DOCK_DIR = DRUGS_DIR / "docked"

for d in (SDF_DIR, PDBQT_DIR, DOCK_DIR):
    d.mkdir(parents=True, exist_ok=True)

if not RECEPTOR_PDBQT.exists():
    raise FileNotFoundError(f"Missing receptor PDBQT: {RECEPTOR_PDBQT}")


def load_existing_results(xlsx_path: Path):
    if not xlsx_path.exists():
        return pd.DataFrame(), pd.DataFrame()
    try:
        summary = pd.read_excel(xlsx_path, sheet_name="Summary")
    except Exception:
        summary = pd.DataFrame()
    try:
        modes = pd.read_excel(xlsx_path, sheet_name="Modes")
    except Exception:
        modes = pd.DataFrame()
    return summary, modes


def save_results(xlsx_path: Path, summary_df: pd.DataFrame, modes_df: pd.DataFrame):
    if not summary_df.empty:
        summary_df = summary_df.sort_values(
            by=["status", "best_affinity_kcal_mol", "molecule"],
            ascending=[True, True, True],
            na_position="last"
        ).reset_index(drop=True)

    if not modes_df.empty:
        modes_df = modes_df.sort_values(
            by=["molecule", "mode"]
        ).reset_index(drop=True)

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        modes_df.to_excel(writer, sheet_name="Modes", index=False)


def run_cmd(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def parse_vina_output(stdout_text):
    rows = []
    best_affinity = None
    seed = None

    seed_match = re.search(r"random seed:\s*(\d+)", stdout_text)
    if seed_match:
        seed = int(seed_match.group(1))

    for line in stdout_text.splitlines():
        m = re.match(
            r"^\s*(\d+)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*$",
            line
        )
        if m:
            mode = int(m.group(1))
            affinity = float(m.group(2))
            rmsd_lb = float(m.group(3))
            rmsd_ub = float(m.group(4))
            rows.append({
                "mode": mode,
                "affinity_kcal_mol": affinity,
                "rmsd_lb": rmsd_lb,
                "rmsd_ub": rmsd_ub
            })

    if rows:
        best_affinity = rows[0]["affinity_kcal_mol"]

    return best_affinity, seed, rows


def sanitize_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "unnamed"
    name = re.sub(r"[^\w.\-]+", "_", name)
    return name[:120]


def prepare_3d_sdf_from_molecule(mol, output_sdf_path: Path, mol_label: str):
    if mol is None:
        raise ValueError(f"RDKit could not read molecule {mol_label}")

    mol = Chem.AddHs(mol, addCoords=True)

    needs_3d = True
    if mol.GetNumConformers() > 0:
        try:
            conf = mol.GetConformer()
            if conf.Is3D():
                needs_3d = False
        except Exception:
            pass

    if needs_3d:
        status = AllChem.EmbedMolecule(mol, randomSeed=42)
        if status != 0:
            raise ValueError(f"3D embedding failed for {mol_label}")
        try:
            AllChem.UFFOptimizeMolecule(mol)
        except Exception:
            pass

    writer = Chem.SDWriter(str(output_sdf_path))
    writer.write(mol)
    writer.close()

    num_h = sum(1 for a in mol.GetAtoms() if a.GetAtomicNum() == 1)
    if num_h == 0:
        raise ValueError(f"No explicit H atoms found after processing {mol_label}")


def should_process(molecule_name: str, source_mtime: str, existing_summary: pd.DataFrame):
    if FORCE_REDOCK or existing_summary.empty:
        return True

    if "molecule" not in existing_summary.columns:
        return True

    row = existing_summary.loc[existing_summary["molecule"] == molecule_name]
    if row.empty:
        return True

    row = row.iloc[0]
    prev_status = str(row.get("status", ""))
    prev_mtime = str(row.get("source_mtime", ""))

    if prev_status != "SUCCESS":
        return True
    if prev_mtime != source_mtime:
        return True

    return False


def upsert_summary(existing_summary: pd.DataFrame, new_row: dict):
    df = existing_summary.copy()
    if df.empty:
        return pd.DataFrame([new_row])

    name = new_row["molecule"]
    if "molecule" in df.columns:
        df = df[df["molecule"] != name]

    return pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)


def replace_modes(existing_modes: pd.DataFrame, molecule_name: str, new_modes: list):
    df = existing_modes.copy()

    if not df.empty and "molecule" in df.columns:
        df = df[df["molecule"] != molecule_name]

    if new_modes:
        add_df = pd.DataFrame(new_modes)
        df = pd.concat([df, add_df], ignore_index=True)

    return df


summary_df, modes_df = load_existing_results(RESULTS_XLSX)

sdf_files = sorted(DRUGS_DIR.glob("*.sdf"))
if not sdf_files:
    raise FileNotFoundError(f"No .sdf files found in {DRUGS_DIR}")

processed_now = []
skipped_now = []
n_since_save = 0

for sdf_input_path in sdf_files:
    print("Reading SDF:", sdf_input_path.name)
    source_mtime = datetime.fromtimestamp(sdf_input_path.stat().st_mtime).isoformat(timespec="seconds")

    supplier = Chem.SDMolSupplier(str(sdf_input_path), removeHs=False)
    if supplier is None:
        print(f"Could not open {sdf_input_path}")
        continue

    used_names = set()

    for idx, mol in enumerate(supplier, start=1):
        raw_name = None
        if mol is not None and mol.HasProp("_Name"):
            raw_name = mol.GetProp("_Name")

        base_name = sanitize_name(raw_name) if raw_name else f"{sdf_input_path.stem}_{idx}"
        molecule = base_name

        duplicate_counter = 2
        while molecule in used_names:
            molecule = f"{base_name}_{duplicate_counter}"
            duplicate_counter += 1
        used_names.add(molecule)

        print(f"Processing: {molecule}")

        if not should_process(molecule, source_mtime, summary_df):
            skipped_now.append(molecule)
            continue

        sdf_path = SDF_DIR / f"{molecule}.sdf"
        ligand_pdbqt = PDBQT_DIR / f"{molecule}.pdbqt"
        docked_pdbqt = DOCK_DIR / f"{molecule}_out.pdbqt"

        summary_row = {
            "molecule": molecule,
            "source_sdf": str(sdf_input_path),
            "source_index": idx,
            "source_name": raw_name,
            "source_mtime": source_mtime,
            "prepared_sdf": str(sdf_path),
            "ligand_pdbqt": str(ligand_pdbqt),
            "receptor_pdbqt": str(RECEPTOR_PDBQT),
            "docked_pdbqt": str(docked_pdbqt),
            "status": "FAILED",
            "best_affinity_kcal_mol": None,
            "num_modes": None,
            "vina_seed": None,
            "last_run": datetime.now().isoformat(timespec="seconds"),
            "error": None,
        }

        try:
            if mol is None:
                raise ValueError(f"RDKit returned None for entry {idx} in {sdf_input_path.name}")

            prepare_3d_sdf_from_molecule(mol, sdf_path, molecule)

            ligand_cmd = [
                "mk_prepare_ligand.py",
                "-i", str(sdf_path),
                "-o", str(ligand_pdbqt),
            ]
            rc, out, err = run_cmd(ligand_cmd)
            if rc != 0 or not ligand_pdbqt.exists():
                raise RuntimeError(f"mk_prepare_ligand.py failed\nSTDOUT:\n{out}\nSTDERR:\n{err}")

            vina_cmd = [
                "vina",
                "--receptor", str(RECEPTOR_PDBQT),
                "--ligand", str(ligand_pdbqt),
                "--center_x", str(CENTER[0]),
                "--center_y", str(CENTER[1]),
                "--center_z", str(CENTER[2]),
                "--size_x", str(SIZE[0]),
                "--size_y", str(SIZE[1]),
                "--size_z", str(SIZE[2]),
                "--exhaustiveness", str(EXHAUSTIVENESS),
                "--num_modes", str(NUM_MODES),
                "--out", str(docked_pdbqt),
            ]
            rc, out, err = run_cmd(vina_cmd)
            if rc != 0 or not docked_pdbqt.exists():
                raise RuntimeError(f"vina failed\nSTDOUT:\n{out}\nSTDERR:\n{err}")

            best_affinity, seed, mode_rows = parse_vina_output(out)

            summary_row["status"] = "SUCCESS"
            summary_row["best_affinity_kcal_mol"] = best_affinity
            summary_row["num_modes"] = len(mode_rows)
            summary_row["vina_seed"] = seed
            summary_row["error"] = None

            mode_rows_for_sheet = []
            for row in mode_rows:
                mode_rows_for_sheet.append({
                    "molecule": molecule,
                    "mode": row["mode"],
                    "affinity_kcal_mol": row["affinity_kcal_mol"],
                    "rmsd_lb": row["rmsd_lb"],
                    "rmsd_ub": row["rmsd_ub"],
                    "docked_pdbqt": str(docked_pdbqt),
                    "last_run": summary_row["last_run"],
                })

            modes_df = replace_modes(modes_df, molecule, mode_rows_for_sheet)

        except Exception as e:
            summary_row["status"] = "FAILED"
            summary_row["error"] = str(e)
            modes_df = replace_modes(modes_df, molecule, [])

        summary_df = upsert_summary(summary_df, summary_row)
        processed_now.append((molecule, summary_row["status"], summary_row["best_affinity_kcal_mol"]))

        n_since_save += 1
        if n_since_save >= SAVE_EVERY:
            save_results(RESULTS_XLSX, summary_df, modes_df)
            print(f"Progress saved to: {RESULTS_XLSX.resolve()}")
            n_since_save = 0

# final save
save_results(RESULTS_XLSX, summary_df, modes_df)

print(f"Saved: {RESULTS_XLSX.resolve()}")
print(f"Processed this run: {len(processed_now)}")
print(f"Skipped (already up to date): {len(skipped_now)}")

if processed_now:
    print("\nProcessed molecules:")
    for name, status, score in processed_now:
        print(f"  {name:25s}  {status:7s}  best_affinity={score}")

if skipped_now:
    print("\nSkipped molecules:")
    for name in skipped_now:
        print(f"  {name}")

