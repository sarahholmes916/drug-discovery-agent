// Override these URLs in the deployed copy when release artifacts are published.
// The pairing credential is generated locally and is intentionally not configured here.
window.DRUG_AGENT_CONFIG = Object.freeze({
  companionBase: "http://127.0.0.1:8765",
  localLlm: Object.freeze({
    enabled: true,
    model: "Qwen3-1.7B-q4f16_1-MLC",
  }),
  toolSetup: Object.freeze({
    "AutoDock Vina": "https://github.com/ccsb-scripps/AutoDock-Vina/releases/latest",
    "Boltz-2": "https://github.com/jwohlwend/boltz#installation",
    "PocketMiner": "https://github.com/Mickdub/gvp/tree/pocket_pred",
    "RDKit": "https://www.rdkit.org/docs/Install.html",
    "Meeko": "https://meeko.readthedocs.io/en/release/installation.html",
    "PLIP": "https://github.com/pharmai/plip",
  }),
  downloads: Object.freeze({
    repository: "sarahholmes916/drug-discovery-agent",
    tag: "v0.1.0", // Change only after the complete next release is published.
  }),
});
