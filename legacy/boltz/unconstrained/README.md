# Boltz-2 unconstrained binding mode

This directory preserves the earlier NS1 Boltz-2 workflow in which **no binding site was specified**.

## What "unconstrained" means here

The actual historical YAMLs under `original_inputs/` contain:

- the NS1 protein sequence;
- one ligand SMILES;
- a receptor structure template;
- an affinity prediction request.

They **do not contain a `constraints:` section or a `pocket:` constraint**. Boltz therefore receives the receptor/template but is not told which residues define the ligand binding site.

This is distinct from the later Vina-site-constrained workflow one directory above, where a forced pocket maps Vina-site residues into Boltz sequence positions.

## Contents

- `original_inputs/`: actual earlier unconstrained YAMLs from `boltz2.zip`.
- `manifest.csv`, `summary.csv`, `run_failures.csv`: actual tables from the earlier run.
- `example_predictions/ns1_structures_12233/`: actual representative old unconstrained prediction output.
- `generate_unconstrained_inputs.py`: portable reconstruction for generating new YAMLs with no pocket constraint.
- `run_unconstrained_boltz2.py`: portable runner. Its default sampling settings intentionally mirror the later constrained run so a future agent can compare modes while changing only the site constraint.

## Agent design rule

The new agent should expose these as two explicit modes rather than treating one as an implementation detail:

- `boltz.mode = unconstrained`
- `boltz.mode = vina_site_constrained`

For `unconstrained`, it must not add a pocket constraint unless the user/research protocol explicitly requests one.

For `vina_site_constrained`, it must validate receptor-coordinate preservation and residue-to-sequence mapping before prediction.

Both modes should preserve the same ligand IDs and should record the mode and full Boltz command/configuration in provenance.

## Historical vs reconstructed material

`original_inputs/`, the CSV tables, and `example_predictions/` are copied from the actual earlier run. The two Python utilities are reconstructed portable helpers based on that archive; they are not claimed to be the original runner source code.
