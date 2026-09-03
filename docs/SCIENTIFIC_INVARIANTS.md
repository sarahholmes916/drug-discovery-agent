1. Vina and Boltz must evaluate the same biological binding site unless otherwise selected during analysis.

2. Vina coordinates must not silently change when creating the
   Boltz receptor template.

3. Residue numbering and Boltz sequence numbering must be explicitly
   mapped and validated.

4. Original ligand IDs must survive every stage.

5. Failed ligand preparations must be logged, never silently skipped.

6. Do not chemically repair malformed molecules without recording
   exactly what was changed.

7. Do not directly compare ligand coordinates from Vina and Boltz
   before aligning their protein coordinate systems.

8. NS1 values such as:
      center = 26.448, 12.021, 27.940
      size = 28,28,28
   are example/reference values ONLY.

9. Ranking thresholds and shortlist sizes must be configuration,
   not hardcoded scientific truths.

10. Existing reference outputs should be used as regression tests.