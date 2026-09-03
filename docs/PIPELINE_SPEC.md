INPUT
researcher's protein target
researcher's ligand dataset
optional known/predicted pocket information

        ↓

1. receptor ingestion + validation

        ↓

2. pocket definition
   derive a target-specific site
   DO NOT reuse NS1 coordinates

        ↓

3. ligand ingestion
   SDF / multi-SDF / directory

        ↓

4. ligand normalization + PDBQT preparation

        ↓

5. Vina
   FAST_SCREEN or FULL_SCREEN

        ↓

6. rank + shortlist

        ↓

7. convert same Vina receptor to Boltz template
   verify coordinate preservation

        ↓

8. map Vina pocket → receptor residues
   map receptor residue IDs → Boltz sequence indexes

        ↓

9. generate forced-pocket Boltz YAMLs

        ↓

10. Boltz predictions, multiple diffusion samples

        ↓

11. Vina structural/contact analysis

        ↓

12. Boltz PLIP analysis

        ↓

13. protein alignment

        ↓

14. pose/contact comparison

        ↓

15. consensus ranking + report