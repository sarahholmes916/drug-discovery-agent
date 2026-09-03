# Migration plan

Migration is incremental and fixture-backed. Legacy files are not edited.

1. **Architecture and traceability.** Inventory scripts, outputs, naming,
   assumptions, dependencies, and scientific invariants in the required docs.
2. **Core infrastructure.** Add typed configuration, local project layout,
   atomic manifest/state/provenance, content hashing, structured logs, and one
   cancellable external-command executor.
3. **Ligands.** Port multi-SDF and directory ingestion with legacy naming plus
   stable IDs. Port explicit-H/3D/Meeko preparation with modification records.
4. **Vina.** Port argument construction, stdout and multi-model parsing,
   item-level hash resume, QC, ranking, and shortlist policies. Preserve named
   fast/full reference profiles without making them mandatory defaults.
5. **Vina analysis.** Port PDBQT parsing, source-graph coordinate reconstruction,
   minimum distances, contacts, and the PLIP-compatible categories. Compare the
   connected `structures_12233` fixture and captured JSON tables, accounting for
   symmetry-equivalent atom maps.
6. **Boltz preparation.** Convert receptor formats without moving coordinates;
   emit validation metrics and explicit residue maps. Generate and separately
   validate constrained and unconstrained inputs against legacy YAMLs.
7. **Boltz execution.** Centralize the command and parse every discovered model,
   confidence JSON, and affinity JSON. Keep model-level and ligand-level data.
8. **PLIP.** Generalize the historical compound-by-five-model loop to every
   selected compound/model, isolate failures, and parse report XML.
9. **Comparison.** Establish protein correspondence, align, transform ligand,
   then calculate comparable RMSD and distinct contact/interaction overlap.
10. **Ranking/reporting.** Preserve raw metrics and add only configured,
    auditable policies. Produce local machine-readable and human-readable output.
11. **Runner.** Add doctor/run/resume/status/cancel/connect commands, persistent
    local jobs, outbound control-plane abstraction, restricted localhost bridge,
    and conservative worker limits.
12. **Hosted proof.** Add a minimal metadata-only API/database and a minimal web
    UI for machines, workflow, progress, and localhost result access.

## Intentional improvements over legacy behavior

- Hashes and declared outputs replace mtime-only resume validity.
- Stable canonical ligand IDs coexist with preserved original/legacy names.
- Invalid compounds and failed external commands receive durable item records.
- Commands use argument arrays and retain structured timing/stdout/stderr.
- NS1 constants and report counts move to project configuration or fixtures.
- Boltz modes have separate builders/validators and output namespaces.
- Coordinate, residue, and atom mapping ambiguity becomes failure/review.
- Cloud serialization is an allowlist boundary, not a convention.

These changes improve auditability and safety without changing the intended
scientific algorithms. Any future algorithmic difference must add a fixture,
versioned profile, rationale, and migration note here.

## Known source limitations

The repository has no saved Vina stdout transcript, receptor PDBQT fixture,
native PLIP XML, original constrained-input generator, or full original
workbook inputs. Tests therefore use the available docked PDBQT result remarks,
captured mapping/interaction JSON, Boltz YAML/result fixtures, and mocked
external commands. Missing scientifically meaningful choices remain required
configuration or `NEEDS_REVIEW`; they are not inferred from NS1.

