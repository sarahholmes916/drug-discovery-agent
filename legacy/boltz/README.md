# Boltz legacy reference material

This starter contains **two scientifically distinct Boltz-2 modes**.

## 1. Vina-site-constrained mode

The files at the root of this directory (`example_inputs/`, `pocket_residues.csv`, `yaml_pocket_mapping.csv`, `conversion_validation.json`, etc.) describe the later workflow where Boltz-2 is forced to evaluate the same binding site used for Vina.

## 2. Unconstrained mode

See `unconstrained/`. This preserves the earlier Boltz-2 workflow that supplied the receptor/template and ligand but did not supply a binding-site/pocket constraint.

The production agent should implement both as explicit configuration modes. It should never silently substitute one for the other.
