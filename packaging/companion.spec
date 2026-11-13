# Native build only: architecture is asserted by build_companion.py.
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
sys.path.insert(0, str(root / "src"))
from drug_discovery_agent.distribution import verify_pocketminer_resources
from drug_discovery_agent.macos_compatibility import MACOS_MINIMUM

resources = verify_pocketminer_resources()
vendor = root / "src/drug_discovery_agent/_vendor/pocketminer"
datas = [(str(vendor / name), "drug_discovery_agent/_vendor/pocketminer/" + str(Path(name).parent))
         for name in [*resources, "manifest.json"]]
datas.append((str(root / "src/drug_discovery_agent/pocketminer/_official_adapter.py"), "drug_discovery_agent/pocketminer"))
binaries = []
hiddenimports = collect_submodules("drug_discovery_agent") + ["meeko.cli.mk_prepare_ligand", "meeko.cli.mk_prepare_receptor"]
for package in ("meeko", "rdkit", "gemmi", "uvicorn"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
for package in ("pydantic", "PyYAML", "numpy", "scipy", "rdkit", "gemmi", "meeko", "openpyxl", "fastapi", "uvicorn", "python-multipart"):
    datas += copy_metadata(package)

a = Analysis([str(root / "apps/companion_main.py")], pathex=[str(root), str(root / "src")],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["torch", "tensorflow", "matplotlib", "IPython", "pytest", "tkinter"])
pyz = PYZ(a.pure)
identity = os.environ.get("MACOS_SIGNING_IDENTITY") or None
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="DrugDiscoveryAgent-Companion",
          console=sys.platform != "darwin", upx=False,
          target_arch=os.environ.get("COMPANION_NATIVE_ARCH") if sys.platform == "darwin" else None,
          codesign_identity=identity,
          entitlements_file=str(root / "packaging/macos-entitlements.plist") if identity else None)
coll = COLLECT(exe, a.binaries, a.datas, name="DrugDiscoveryAgent-Companion", upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name="DrugDiscoveryAgent-Companion.app",
                 bundle_identifier="org.drugdiscoveryagent.companion",
                 info_plist={"CFBundleShortVersionString": os.environ.get("COMPANION_VERSION", "0.1.0"),
                             "LSMinimumSystemVersion": MACOS_MINIMUM, "NSHighResolutionCapable": True})
